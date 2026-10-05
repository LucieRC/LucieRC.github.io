"""Assemble data/veille.sqlite + config.json + template.html → dist/veille-fipu.html (un seul fichier).

Les mots-clés, seuils et durées sont appliqués ici : modifier config.json puis relancer
build.py suffit pour reclasser, sans recollecter.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import score
import store
from sources import normalize

ROOT = Path(__file__).parent
OUT = ROOT / "dist" / "veille-fipu.html"


def _ts(iso):
    d = datetime.fromisoformat(iso.replace("Z", "+00:00")) if "T" in iso else datetime.fromisoformat(iso + "T12:00:00")
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def brief_since(runs, min_hours):
    """Début du brief affiché : la dernière collecte antérieure d'au moins `min_hours` à la plus
    récente (les collectes rapprochées d'une même matinée forment un seul brief) ; à défaut, 24 h."""
    if not runs:
        return None
    latest = _ts(runs[0]["started"])
    for r in runs[1:]:
        if _ts(r["started"]) <= latest - timedelta(hours=min_hours):
            return r["started"]
    return (latest - timedelta(hours=24)).isoformat(timespec="seconds")


STOP = set("""les des une pour par sur dans avec son ses aux est sont qui que quoi plus pas elle ils
leur leurs cette ces comme mais selon entre apres avant encore tout tous the and for with from that this
its has have are was will what how why quand comment pourquoi faut fait etre avoir deja""".split())


def tokens(title):
    """Mots significatifs d'un titre : sert à regrouper les articles qui traitent du même sujet."""
    return {w for w in re.findall(r"[a-z0-9]+", normalize(title)) if (len(w) >= 3 or w.isdigit()) and w not in STOP}


def similar(a, b, overlap):
    if len(a) < 3 or len(b) < 3:
        return a == b
    return len(a & b) / min(len(a), len(b)) >= overlap


def collect(cfg):
    conn = store.connect()
    runs = [dict(r) for r in conn.execute("SELECT * FROM runs WHERE finished IS NOT NULL ORDER BY started DESC LIMIT 30")]
    status = {r["key"]: dict(r) for r in conn.execute("SELECT * FROM status")}
    now = datetime.now(timezone.utc)
    horizon = (now - timedelta(days=cfg["retention_days"])).isoformat(timespec="seconds")
    rows = conn.execute("SELECT * FROM items WHERE first_seen >= ? ORDER BY first_seen, url", (horizon,)).fetchall()
    totals = {r[0]: r[1] for r in conn.execute("SELECT source, COUNT(*) FROM items GROUP BY source")}
    conn.close()

    srcs = {s["key"]: s for s in cfg["sources"]}
    lines = score.compile_keywords(cfg)
    since = brief_since(runs, cfg["brief_min_hours"])
    too_old = now - timedelta(days=cfg["new_max_age_days"])
    backfill_ok = now - timedelta(days=cfg["backfill_recent_days"])

    cat_boost = {c["id"]: c.get("boost", 0) for c in cfg["categories"]}
    scored, hidden = [], 0
    for r in rows:
        src = srcs.get(r["source"])
        if not src:
            continue
        boost = src.get("boost", 0) + cat_boost.get(src["category"], 0)
        sc, terms, groups = score.score(r["title"], r["summary"] or "", boost, lines, cfg["title_weight"])
        if sc <= 0:
            hidden += 1
            continue
        pub = _ts(r["published"]) if r["published"] else None
        is_new = bool(since) and r["first_seen"] > since and (pub is None or pub >= too_old) \
            and (not r["backfill"] or (pub is not None and pub >= backfill_ok))
        scored.append({"u": r["url"], "t": r["title"], "s": r["summary"] or "", "v": r["via"], "p": r["published"],
                       "f": r["first_seen"], "k": r["source"], "c": src["category"], "sc": sc, "m": terms,
                       "g": groups, "n": is_new, "b": r["backfill"], "_d": pub or _ts(r["first_seen"]), "_w": tokens(r["title"]),
                       "_agg": src["type"] == "gnews"})

    # Un même sujet repris par plusieurs médias : on garde l'élément le mieux classé (source
    # directe de préférence) et on range les autres dessous (« articles similaires »).
    scored.sort(key=lambda i: (-i["sc"], i["_agg"], i["f"]))
    items, window = [], timedelta(days=cfg["similar_days"])
    for it in scored:
        lead = next((k for k in items if abs(k["_d"] - it["_d"]) <= window
                     and similar(k["_w"], it["_w"], cfg["similar_overlap"])), None)
        if lead is None:
            items.append(it)
            continue
        lead.setdefault("also", []).append({"t": it["t"], "u": it["u"], "src": it["v"] or srcs[it["k"]]["label"]})
        lead["n"] = lead["n"] or it["n"]
    for it in items:
        for k in ("_d", "_w", "_agg"):
            del it[k]

    out_sources = []
    for s in cfg["sources"]:
        st = status.get(s["key"], {})
        out_sources.append({"key": s["key"], "label": s["label"], "category": s["category"], "type": s["type"],
                            "url": s.get("url") or ("https://news.google.com/search?q=" + s.get("query", "")),
                            "enabled": s.get("enabled", True), "note": s.get("note"), "boost": s.get("boost", 0),
                            "ok": st.get("ok"), "last_ok": st.get("last_ok"), "last_try": st.get("last_try"),
                            "n_items": st.get("n_items"), "n_new": st.get("n_new"), "error": st.get("error"),
                            "total": totals.get(s["key"], 0)})
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "brief_since": since,
        "runs": runs[:10],
        "items": items,
        "hidden": hidden,
        "sources": out_sources,
        "categories": cfg["categories"],
        "keywords": cfg["keywords"],
        "settings": {k: cfg[k] for k in ("min_score", "title_weight", "retention_days", "new_max_age_days", "reperes_url")}
                    | ({"reperes_url": os.environ["VEILLE_REPERES_URL"]} if "VEILLE_REPERES_URL" in os.environ else {}),
    }


def main():
    cfg = json.loads((ROOT / "config.json").read_text())
    data = collect(cfg)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = (ROOT / "template.html").read_text()
    if "/*__DATA__*/null" not in html:
        raise SystemExit("marqueur /*__DATA__*/null absent du template")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html.replace("/*__DATA__*/null", payload))
    n_new = sum(1 for i in data["items"] if i["n"])
    print(f"→ {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} Ko) : {n_new} nouveauté(s), "
          f"{len(data['items'])} élément(s) pertinents en archive, {data['hidden']} écarté(s) (score nul)")


if __name__ == "__main__":
    main()
