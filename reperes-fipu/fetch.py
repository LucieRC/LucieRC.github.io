"""Collecte les données décrites dans config.json et écrit data/data.json (+ data/jorf.json).

Chaque bloc est collecté indépendamment : si une source échoue, la dernière version
valide est conservée, marquée comme telle, et signalée dans la page.

    python3 fetch.py                     # tout
    python3 fetch.py --only figures jorf # certains blocs
"""
import argparse
import html
import json
import re
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path

import requests

import jorf
import wiki

ROOT = Path(__file__).parent
CONFIG = ROOT / "config.json"
DATA = ROOT / "data" / "data.json"
JORF_STORE = ROOT / "data" / "jorf.json"
CHANGELOG = ROOT / "data" / "changelog.json"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
INSEE = "https://bdm.insee.fr/series/sdmx/data/SERIES_BDM/"
BLOCKS = ["history", "government", "officials", "budgets", "figures", "jorf", "reference"]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


# =================================================================== history

def _col(header, *names, last=False):
    idx = [i for i, c in enumerate(header) if any(c["text"].startswith(n) for n in names)]
    if not idx:
        return None
    return idx[-1] if last else idx[0]


def _is_banner(row):
    return len({c["text"] for c in row}) == 1


def _person(cell):
    return {"name": cell["text"] or (cell["link"] or [""])[0],
            "url": cell["link"][1] if cell["link"] else None}


def _tables(page, header_text):
    title, soup = wiki.html(page)
    found = []
    for tb in soup.select("table.wikitable"):
        g = wiki.grid(tb)
        if g and any(header_text in c["text"] for c in g[0]):
            found.append(g)
    if not found:
        raise RuntimeError(f"aucun tableau avec la colonne « {header_text} » dans {title}")
    return title, found


def _dedupe(rows, *keys):
    seen, out = set(), []
    for r in rows:
        k = tuple(r[x] for x in keys)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def history_governments(cfg, since):
    title, tables = _tables(cfg["page"], cfg["table_header"])
    g = tables[-1]
    h = g[0]
    ci = dict(name=_col(h, "Gouvernement", last=True), dates=_col(h, "Dates"),
              pm=_col(h, "Premier ministre"), party=_col(h, "Parti"),
              pres=_col(h, "Président"), size=_col(h, "Nombre"))
    if None in ci.values():
        raise RuntimeError(f"colonnes inattendues : {[c['text'] for c in h]}")
    out = []
    for r in g[1:]:
        if len(r) <= max(ci.values()) or _is_banner(r) or r[ci["name"]]["text"] == h[ci["name"]]["text"]:
            continue
        ds = wiki.dates_in(r[ci["dates"]]["text"])
        if not ds or int(ds[0][:4]) < since:
            continue
        pres = re.sub(r"^Présidence d[e']\s*", "", r[ci["pres"]]["text"])
        out.append({
            "name": r[ci["name"]]["text"], "url": (r[ci["name"]]["link"] or [None, None])[1],
            "start": ds[0], "end": ds[1] if len(ds) > 1 else None,
            "pm": _person(r[ci["pm"]]), "party": r[ci["party"]]["text"],
            "president": re.split(r"\s+(?:[A-Z]{2,}\b|depuis|du \d)", pres)[0],
            "president_since": (wiki.dates_in(r[ci["pres"]]["text"]) or [None])[0],
            "size": r[ci["size"]]["text"],
        })
    # la page répète certaines lignes (gouvernement à cheval sur deux législatures)
    return {"rows": _dedupe(out, "name", "start", "end"), "source": wiki.page_url(title), "page": title}


def history_economy(cfg, since):
    title, tables = _tables(cfg["page"], cfg["table_header"])
    out = []
    for g in tables:
        h = g[0]
        ci = dict(name=_col(h, "Ministre", last=True), title=_col(h, "Intitulé"),
                  party=_col(h, "Parti"), gov=_col(h, "Gouvernement"))
        if None in ci.values():
            continue
        dcols = [i for i, c in enumerate(h) if c["text"] in ("Début", "Fin", "Période")]
        for r in g[1:]:
            if len(r) <= max(ci.values()) or _is_banner(r) or r[ci["name"]]["th"]:
                continue
            ds = wiki.dates_in(" ".join(r[i]["text"] for i in dict.fromkeys(dcols)))
            if not ds or int(ds[0][:4]) < since:
                continue
            out.append({**_person(r[ci["name"]]), "title": r[ci["title"]]["text"],
                        "party": r[ci["party"]]["text"], "gov": r[ci["gov"]]["text"],
                        "start": ds[0], "end": ds[1] if len(ds) > 1 else None})
    if not out:
        raise RuntimeError(f"aucune ligne depuis {since} dans {title}")
    out.sort(key=lambda x: x["start"])
    return {"rows": _dedupe(out, "name", "start", "title"), "source": wiki.page_url(title), "page": title}


def history_budget(cfg, since):
    title, tables = _tables(cfg["page"], cfg["table_header"])
    out = []
    for g in tables:
        h = g[0]
        ci = dict(name=0, title=1, boss=_col(h, "Ministre de tutelle"), gov=_col(h, "Gouvernement"), date=_col(h, "Date"))
        if None in ci.values():
            continue
        for r in g[1:]:
            if len(r) <= max(ci.values()) or _is_banner(r) or r[0]["th"]:
                continue
            ds = wiki.dates_in(r[ci["date"]]["text"])
            if not ds or int(ds[0][:4]) < since:
                continue
            boss = r[ci["boss"]]["text"]
            full = boss.lower() == "plein exercice"
            out.append({**_person(r[ci["name"]]), "title": r[ci["title"]]["text"],
                        "full_rank": full, "boss": None if full else boss,
                        "gov": r[ci["gov"]]["text"],
                        "start": ds[0], "end": ds[1] if len(ds) > 1 else None})
    if not out:
        raise RuntimeError(f"aucune ligne depuis {since} dans {title}")
    out.sort(key=lambda x: x["start"])
    return {"rows": _dedupe(out, "name", "start", "title"), "source": wiki.page_url(title), "page": title}


def _since(rows, name):
    """Début du mandat continu en cours de `name` (les gouvernements successifs sont fusionnés)."""
    start = None
    for r in reversed(rows):
        if r["name"] != name:
            if start:
                break
            continue
        start = r["start"]
    return start


# =================================================================== government

MINISTRY_RE = re.compile(r"^'''(.+?)'''\s*$", re.M)
BULLET_RE = re.compile(r"^\*\s*(.+)$", re.M)
DECREE_RE = re.compile(r"\{\{Légifrance\|[^}]*?numéro=([A-Z0-9]+)\|texte=([^}]+)\}\}")


def government(current_title):
    title, wt = wiki.wikitext(current_title)
    orgs = [(h, b) for h, b in wiki.sections(wt, 3) if h.startswith("Organisation fonctionnelle")]
    if not orgs:
        raise RuntimeError(f"pas de section « Organisation fonctionnelle » dans {title}")
    head, body = orgs[-1]
    ministries = []
    parts = MINISTRY_RE.split(body)
    for name, block in zip(parts[1::2], parts[2::2]):
        members = []
        for line in BULLET_RE.findall(block):
            ls = wiki.links(line)
            if not ls:
                continue
            target, label = ls[0]
            role = wiki.plain(line.split("]]", 1)[1]).lstrip(", ").strip()
            members.append({"name": label, "url": wiki.page_url(target), "role": role})
        ministries.append({"name": wiki.plain(name), "members": members})
    if not any(m["members"] for m in ministries):
        raise RuntimeError(f"organisation fonctionnelle vide dans {title}")

    changes = []
    evo = re.search(r"^==\s*Évolution de la composition\s*==\s*$(.*?)(?=^==[^=]|\Z)", wt, re.M | re.S)
    if evo:
        for h, b in wiki.sections(evo.group(1), 3):
            ds = wiki.dates_in(wiki.plain(h))
            changes.append({"title": wiki.plain(h), "date": ds[0] if ds else None,
                            "text": wiki.plain(re.sub(r"\n+", " ", b)),
                            "decrees": [{"nor": n, "label": wiki.plain(t)} for n, t in DECREE_RE.findall(b)]})
    org_dates = wiki.dates_in(wiki.plain(head))
    return {"page": title, "source": wiki.page_url(title), "org_label": wiki.plain(head),
            "org_since": org_dates[0] if org_dates else None,
            "ministries": ministries, "changes": changes,
            "page_updated": wiki.last_edits([title]).get(title, {}).get("updated")}


# =================================================================== officials

def _clean_name(s):
    return re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()


def _from_infobox(o):
    title, wt = wiki.wikitext(o["page"], section=0)
    v = wiki.infobox_field(wt, o["field"])
    if not v or not wiki.plain(v):
        raise RuntimeError(f"champ « {o['field']} » vide ou absent de {title}")
    ls = wiki.links(v)
    txt = wiki.plain(v)
    since = (wiki.dates_in(txt) or [wiki.month_year(txt)])[0]
    if not since:
        y = re.search(r"\((\d{4})\)", txt)
        since = y.group(1) if y else None
    if ls:
        target, label = ls[0]
        return {"name": label, "url": wiki.page_url(target), "since": since, "page": title}
    # nom sans lien : on le garde tel quel, sans chercher de page (risque d'homonyme)
    return {"name": _clean_name(txt), "url": None, "since": since, "page": title}


def _from_government(o, gov):
    for m in gov["ministries"]:
        for x in m["members"]:
            if re.search(o["pattern"], x["role"], re.I):
                return {"name": x["name"], "url": x["url"], "title": x["role"], "page": gov["page"]}
    raise RuntimeError(f"aucun membre du gouvernement ne correspond à /{o['pattern']}/")


def _from_prose(o):
    title, wt = wiki.wikitext(o["page"])
    m = re.search(o["regex"], wt)
    if not m:
        raise RuntimeError(f"motif introuvable dans {title}")
    tail = wiki.plain(m.group(3)) if m.lastindex and m.lastindex >= 3 else ""
    return {"name": m.group(2) or m.group(1), "url": wiki.page_url(m.group(1)),
            "since": (wiki.dates_in(tail) or [wiki.month_year(tail)])[0], "page": title}


def _from_list_last_row(o):
    title, soup = wiki.html(o["page"])
    for tb in soup.select("table.wikitable"):
        g = wiki.grid(tb)
        ni, di = _col(g[0], o["name_header"]), _col(g[0], o["date_header"])
        if ni is None or di is None:
            continue
        r = g[-1]
        ds = wiki.dates_in(r[di]["text"])
        return {**_person(r[ni]), "since": ds[0] if ds else None, "page": title}
    raise RuntimeError(f"tableau introuvable dans {title}")


def officials(cfg, hist, gov):
    out, errors = [], []
    for o in cfg["officials"]:
        try:
            kind = o["kind"]
            if kind == "infobox":
                p = _from_infobox(o)
            elif kind == "government_role":
                if not gov:
                    raise RuntimeError("bloc gouvernement indisponible")
                p = _from_government(o, gov)
            elif kind == "prose":
                p = _from_prose(o)
            elif kind == "list_last_row":
                p = _from_list_last_row(o)
            else:
                raise RuntimeError(f"type inconnu : {kind}")
            sf = o.get("since_from")
            if sf and hist:
                if sf == "president":
                    rows = [r for r in hist["governments"]["rows"] if r["president"] == p["name"]]
                    p["since"] = p.get("since") or (rows[0]["president_since"] if rows else None)
                elif sf == "pm":
                    rows = [{"name": r["pm"]["name"], "start": r["start"]} for r in hist["governments"]["rows"]]
                    p["since"] = _since(rows, p["name"])
                    p["detail"] = hist["governments"]["rows"][-1]["name"]
                else:
                    p["since"] = _since(hist[sf]["rows"], p["name"]) or p.get("since")
            p.update(key=o["key"], label=o["label"], group=o["group"], source=wiki.page_url(p["page"]))
            out.append(p)
        except Exception as e:  # noqa: BLE001 — un poste en échec ne bloque pas les autres
            errors.append({"key": o["key"], "label": o["label"], "error": f"{type(e).__name__}: {e}"})

    # fiche de la personne — seulement si la source donne un lien vers sa page
    edits = wiki.last_edits([p["page"] for p in out])
    info = wiki.pages_info([wiki.title_from_url(p["url"]) for p in out if p.get("url")])
    for p in out:
        p["page_updated"] = edits.get(p["page"], {}).get("updated")
        i = info.get(wiki.title_from_url(p.get("url")))
        if i:
            p["bio"] = i["extract"]
            if i["thumb_url"]:
                try:
                    p["photo"] = wiki.data_uri(i["thumb_url"])
                except Exception:  # noqa: BLE001 — photo facultative
                    pass
    return out, errors


# =================================================================== budgets, reference

def budgets(cfg):
    y = date.today().year
    out = []
    for pattern in cfg["budget_pages"]:
        for yy in (y, y + 1):
            want = pattern.format(year=yy)
            title, ext = wiki.extract(want)
            out.append({"year": yy, "wanted": want, "page": title,
                        "url": wiki.page_url(title) if title else None, "extract": ext})
    edits = wiki.last_edits([b["page"] for b in out if b["page"]])
    for b in out:
        b["page_updated"] = edits.get(b["page"], {}).get("updated")
    return out


def reference(cfg):
    groups, missing = [], []
    for grp in cfg["reference"]:
        info = wiki.pages_info(grp["pages"], sentences=None, thumb=None)
        items = []
        for t in grp["pages"]:
            i = info.get(t)
            if not i:
                missing.append(t)
                continue
            items.append({"page": i["title"], "url": wiki.page_url(i["title"]),
                          "extract": i["extract"], "page_updated": i["updated"]})
        groups.append({"group": grp["group"], "items": items})
    calendar = []
    for c in cfg["calendar"]:
        try:
            title, blocks = wiki.section_blocks(c["page"], c["section"])
            calendar.append({"page": title, "section": c["section"], "url": wiki.page_url(title),
                             "blocks": blocks})
        except Exception as e:  # noqa: BLE001
            missing.append(f"{c['page']} § {c['section']} ({e})")
    edits = wiki.last_edits([c["page"] for c in calendar])
    for c in calendar:
        c["page_updated"] = edits.get(c["page"], {}).get("updated")
    return {"groups": groups, "calendar": calendar, "missing": missing}


# =================================================================== figures

def eurostat(dataset, filters, since):
    params = [("lang", "fr"), ("sinceTimePeriod", since)]
    params += [(k, v) for k, vs in filters.items() for v in (vs if isinstance(vs, list) else [vs])]
    r = requests.get(EUROSTAT + dataset, params=params, timeout=60)
    r.raise_for_status()
    d = r.json()
    if "error" in d:
        raise RuntimeError(str(d["error"]))
    ids, size = d["id"], d["size"]
    strides = [1] * len(size)
    for i in range(len(size) - 2, -1, -1):
        strides[i] = strides[i + 1] * size[i + 1]
    cats = {k: {v: kk for kk, v in d["dimension"][k]["category"]["index"].items()} for k in ids}
    series = {}
    for flat, val in d["value"].items():
        flat = int(flat)
        coord = {k: cats[k][(flat // s) % n] for k, s, n in zip(ids, strides, size)}
        series.setdefault(coord.get("geo", "_"), []).append([coord["time"], val])
    for v in series.values():
        v.sort()
    # libellés officiels des dimensions fixées (indicateur, unité, secteur…)
    labels = []
    for k in ids:
        if k in ("geo", "time", "freq"):
            continue
        cl = d["dimension"][k]["category"].get("label", {})
        if len(cl) == 1:
            labels.append(next(iter(cl.values())))
    return series, d.get("updated"), d.get("label"), labels


def insee(idbank, since, tries=3):
    """Une série de la BDM Insee (SDMX), par son idbank. L'Insee coupe parfois les connexions
    venant des serveurs de GitHub : on réessaie avant de déclarer la source en échec."""
    for i in range(tries):
        try:
            r = requests.get(INSEE + idbank, params={"startPeriod": since}, timeout=60)
            r.raise_for_status()
            break
        except requests.RequestException:
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))
    s = next((e for e in ET.fromstring(r.content).iter() if e.tag.endswith("Series")), None)
    if s is None:
        raise RuntimeError(f"série Insee introuvable : {idbank}")
    pts = sorted([o.get("TIME_PERIOD"), float(o.get("OBS_VALUE"))] for o in s
                 if o.get("OBS_VALUE") not in (None, "", "NaN"))
    upd = s.get("LAST_UPDATE")  # date seule : rendue comparable aux dates Eurostat
    return pts, (upd + "T00:00:00+00:00" if upd else None), s.get("TITLE_FR", "")


def insee_table(url, table):
    """Tableau d'une page insee.fr, repris tel quel : {libellé de ligne: [[année, valeur], …]}, date de parution, titre."""
    for i in range(3):
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            break
        except requests.RequestException:
            if i == 2:
                raise
            time.sleep(5 * (i + 1))
    page = r.text
    cell = lambda c: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
    tb = next((t for t in re.findall(r"<table.*?</table>", page, re.S) if re.search(table, cell(t), re.I)), None)
    if tb is None:
        raise RuntimeError(f"tableau Insee « {table} » introuvable : {url}")
    trs = [[cell(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)] for tr in re.findall(r"<tr.*?</tr>", tb, re.S)]
    years = trs[0][1:]
    rows = {re.sub(r"\s*\(\d+\)\s*", " ", tr[0]).strip(): [[y, float(v.replace(",", "."))] for y, v in zip(years, tr[1:])
                                                          if re.fullmatch(r"-?\d+(,\d+)?", v)] for tr in trs[1:]}
    m = re.search(r"Paru le(?:&nbsp;|\s)*:(?:\s|<[^>]+>)*(\d{2})/(\d{2})/(\d{4})", page)
    title = cell(re.search(r"<title>(.*?)</title>", page, re.S)[1])
    return rows, (f"{m[3]}-{m[2]}-{m[1]}T00:00:00+00:00" if m else None), title


def figures(cfg):
    out, pages = {}, {}
    for s in cfg["eurostat"]:
        if s.get("provider") == "insee":
            pts, upd, title = insee(s["idbank"], s["since"])
            if not pts:
                raise RuntimeError(f"série vide : {s['key']}")
            out[s["key"]] = {**{k: s.get(k) for k in ("label", "unit", "decimals", "tile")},
                             "points": pts, "updated": upd, "source": "Insee", "dataset": s["idbank"],
                             "dataset_label": "Banque de données macroéconomiques", "official_labels": [title],
                             "url": f"https://www.insee.fr/fr/statistiques/serie/{s['idbank']}"}
            continue
        series, upd, ds_label, labels = eurostat(s["dataset"], s["filters"], s["since"])
        if s.get("spread"):
            a, b = s["spread"]
            bb = dict(series[b])
            pts = [[t, round((v - bb[t]) * s.get("scale", 1), 2)] for t, v in series[a] if t in bb]
        else:
            geo = s["filters"].get("geo", "_")
            pts = series[geo if isinstance(geo, str) else geo[0]]
        if not pts:
            raise RuntimeError(f"série vide : {s['key']}")
        fig = {**{k: s.get(k) for k in ("label", "unit", "decimals", "tile")},
               "points": pts, "updated": upd, "source": "Eurostat", "dataset": s["dataset"],
               "dataset_label": ds_label, "official_labels": labels,
               "url": f"https://ec.europa.eu/eurostat/databrowser/view/{s['dataset']}/default/table?lang=fr"}
        if s.get("insee"):
            # L'Insee publie les comptes annuels des APU avant Eurostat, qui les reprend : ses valeurs
            # remplacent celles d'Eurostat sur les années qu'il couvre ; Eurostat garde les années
            # antérieures, et les plus récentes s'il les publie en premier (avril-mai, avant l'édition Insee).
            ins = s["insee"]
            pg = cfg["insee_pages"][ins["page"]]
            if ins["page"] not in pages:
                pages[ins["page"]] = insee_table(pg["url"], pg["table"])
            rows, ins_upd, title = pages[ins["page"]]
            row = next((k for k in rows if re.search(ins["row"], k)), None)
            if row is None:
                raise RuntimeError(f"ligne « {ins['row']} » absente du tableau Insee")
            ipts = [[y, -v if ins.get("negate") else v] for y, v in rows[row]]
            merged = dict(pts) | dict(ipts)
            last_y = max(merged)
            from_insee = last_y in dict(ipts)
            fig["points"] = sorted([list(x) for x in merged.items()])
            fig["insee"] = {"row": row, "first": ipts[0][0], "last": ipts[-1][0], "updated": ins_upd, "title": title,
                            "url": pg["url"], "eurostat_last": pts[-1][0]}
            if from_insee:
                fig.update(source="Insee", dataset="Comptes de la Nation", url=pg["url"], updated=ins_upd,
                           dataset_label=title, official_labels=[row + (" (signe inversé)" if ins.get("negate") else "")])
        out[s["key"]] = fig
    return out


# =================================================================== checks

def checks(cfg, data, jorf_store):
    """Contrôles de cohérence entre sources : signalent un extracteur cassé ou une source en retard."""
    B, out = data["blocks"], []

    def add(name, ok, detail, level="error"):
        out.append({"name": name, "ok": bool(ok), "level": "ok" if ok else level, "detail": detail})

    for b in BLOCKS:
        st = data["status"].get(b, {})
        add(f"Collecte « {b} »", st.get("ok"), st.get("error") or "OK")

    hist, gov = B.get("history"), B.get("government")
    people = {p["key"]: p for p in (B.get("officials") or [])}
    if hist:
        open_govs = [r for r in hist["governments"]["rows"] if not r["end"]]
        add("Un seul gouvernement en fonction dans l'historique", len(open_govs) == 1,
            ", ".join(r["name"] for r in open_govs) or "aucun")
        if gov and open_govs:
            add("Gouvernement suivi = gouvernement en fonction", gov["page"] == open_govs[-1]["name"],
                f"{gov['page']} / {open_govs[-1]['name']}")
        if "pm" in people and open_govs:
            add("Premier ministre : infobox = historique", people["pm"]["name"] == open_govs[-1]["pm"]["name"],
                f"{people['pm']['name']} / {open_govs[-1]['pm']['name']}")
        for key, hk in (("eco", "economy"), ("budget", "budget")):
            if key in people:
                cur = [r["name"] for r in hist[hk]["rows"] if not r["end"]]
                add(f"{people[key]['label']} : gouvernement = historique", people[key]["name"] in cur,
                    f"{people[key]['name']} / {', '.join(cur) or 'aucun en fonction'}", "warn")
    for e in data["status"].get("officials_errors", []):
        add(f"Poste « {e['label']} »", False, e["error"])

    if jorf_store:
        latest = max((e["date"] for e in jorf_store["entries"].values() if e.get("date")), default=None)
        age = (date.today() - date.fromisoformat(latest)).days if latest else None
        add("Journal officiel récent (≤ 4 jours)", age is not None and age <= 4,
            f"dernier numéro lu : {latest}", "warn")
        comp = sorted((e for e in jorf_store["entries"].values()
                       if re.search(r"composition du Gouvernement", e["title"], re.I)), key=lambda e: e["date"])
        if comp and gov:
            last = comp[-1]
            decree_day = (wiki.dates_in(last["title"]) or [last["date"]])[0]
            ref = gov.get("org_since") or ""
            add("Wikipédia à jour du dernier décret de composition du Gouvernement", not ref or decree_day <= ref,
                f"décret du {decree_day} (JO du {last['date']}) ; organisation Wikipédia depuis le {ref or '?'}", "warn")

    stale = int(cfg["stale_page_days"])
    old = [p for p in people.values() if p.get("page_updated") and
           (datetime.now(timezone.utc) - datetime.fromisoformat(p["page_updated"].replace("Z", "+00:00"))).days > stale]
    add(f"Pages sources modifiées depuis moins de {stale} jours", not old,
        ", ".join(f"{p['label']} ({p['page_updated'][:10]})" for p in old) or "toutes", "warn")

    for s in (B.get("figures") or {}).values():
        ins = s.get("insee")
        if ins and date.today() >= date(date.today().year, 6, 15) and ins["last"] < str(date.today().year - 1):
            add(f"Édition Insee des Comptes de la Nation à jour (« {s['label']} »)", False,
                f"dernière année {ins['last']} : mettre à jour insee_pages dans config.json", "warn")
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(s["updated"])).days if s.get("updated") else 999
        if age > 400:
            add(f"Série {s.get('source', 'Eurostat')} « {s['label']} » mise à jour depuis moins de 400 jours", False, s.get("updated"), "warn")
    ref = B.get("reference") or {}
    if ref.get("missing"):
        add("Pages de référence trouvées", False, " ; ".join(ref["missing"]), "warn")
    return out


# =================================================================== main

def run_all(only=None, progress=print):
    cfg = json.loads(CONFIG.read_text())
    DATA.parent.mkdir(exist_ok=True)
    prev = load(DATA, {})
    data = {"blocks": prev.get("blocks", {}), "status": prev.get("status", {})}
    before = {p["key"]: p["name"] for p in (prev.get("blocks", {}).get("officials") or []) if not p.get("stale")}

    def run(name, label, fn):
        if only and name not in only:
            return data["blocks"].get(name)
        progress(label)
        try:
            data["blocks"][name] = fn()
            data["status"][name] = {"ok": True, "fetched_at": now(), "error": None}
        except Exception as e:  # noqa: BLE001
            st = data["status"].get(name, {})
            data["status"][name] = {"ok": False, "fetched_at": st.get("fetched_at"),
                                    "error": f"{type(e).__name__}: {e}"}
            progress(f"  ✗ {name} : {e}")
            traceback.print_exc(limit=3, file=sys.stderr)
        return data["blocks"].get(name)

    since = int(cfg["history_since"])
    H = cfg["history"]
    hist = run("history", "Historiques (Wikipédia)", lambda: {
        "governments": history_governments(H["governments"], since),
        "economy": history_economy(H["economy"], since),
        "budget": history_budget(H["budget"], since)})
    gov = run("government", "Gouvernement en fonction (Wikipédia)",
              lambda: government([r for r in hist["governments"]["rows"] if not r["end"]][-1]["name"]))

    def off():
        people, errors = officials(cfg, hist, gov)
        data["status"]["officials_errors"] = errors
        # un poste en échec garde sa dernière valeur connue, signalée comme telle
        old = {p["key"]: p for p in (prev.get("blocks", {}).get("officials") or [])}
        got = {p["key"] for p in people}
        people += [dict(old[e["key"]], stale=True) for e in errors if e["key"] in old and e["key"] not in got]
        order = [o["key"] for o in cfg["officials"]]
        return sorted(people, key=lambda p: order.index(p["key"]) if p["key"] in order else 99)
    people = run("officials", "Titulaires des postes (Wikipédia)", off)
    run("budgets", "Budgets (Wikipédia)", lambda: budgets(cfg))
    run("reference", "Textes de référence (Wikipédia)", lambda: reference(cfg))
    run("figures", "Chiffres (Eurostat, Insee)", lambda: figures(cfg))
    jstore = None

    def jo():
        nonlocal jstore
        jstore = jorf.update(JORF_STORE, cfg["jorf"], progress)
        return {"coverage_from": jstore.get("coverage_from"), "latest_bundle": jstore.get("latest_bundle"),
                "count": len(jstore["entries"])}
    run("jorf", "Journal officiel (DILA)", jo)
    if jstore is None:
        jstore = load(JORF_STORE, None)

    log = load(CHANGELOG, [])
    if before and people:
        for p in people:
            if p["key"] in before and before[p["key"]] != p["name"] and not p.get("stale"):
                log.append({"detected": now(), "label": p["label"], "from": before[p["key"]], "to": p["name"]})
    CHANGELOG.write_text(json.dumps(log, ensure_ascii=False, indent=1))
    data["changelog"] = log[-100:]
    data["generated_at"] = now()
    data["checks"] = checks(cfg, data, jstore)
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    bad = [c for c in data["checks"] if not c["ok"]]
    progress(f"Contrôles : {len(data['checks']) - len(bad)} OK, {len(bad)} à regarder")
    return data


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", choices=BLOCKS, help="blocs à rafraîchir")
    args = ap.parse_args(argv)
    data = run_all(args.only)
    for c in data["checks"]:
        if not c["ok"]:
            print(f"  ! {c['name']} — {c['detail']}")


if __name__ == "__main__":
    main()
