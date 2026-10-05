"""Collecte les sources décrites dans config.json et les range dans data/veille.sqlite.

Chaque source est lue indépendamment : une source en échec n'empêche pas les autres,
son erreur est enregistrée et affichée dans la page (bandeau + tableau des sources).

    python3 fetch.py                        # toutes les sources actives
    python3 fetch.py --only hcfp fipeco     # certaines sources
"""
import argparse
import json
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sources
import store

ROOT = Path(__file__).parent
CONFIG = ROOT / "config.json"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_config():
    return json.loads(CONFIG.read_text())


def _read(src, ua):
    try:
        return src, sources.read(src, ua), None
    except Exception as e:  # noqa: BLE001
        traceback.print_exc(limit=2, file=sys.stderr)
        return src, None, f"{type(e).__name__}: {e}"[:300]


def run_all(only=None, progress=print):
    cfg = load_config()
    todo = [s for s in cfg["sources"] if s.get("enabled", True) and (not only or s["key"] in only)]
    conn = store.connect()
    started = now()
    run_id = conn.execute("INSERT INTO runs(started) VALUES (?)", (started,)).lastrowid
    conn.commit()
    progress(f"Collecte de {len(todo)} source(s)")

    total_new = errors = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for src, items, err in ex.map(lambda s: _read(s, cfg["user_agent"]), todo):
            key = src["key"]
            prev = conn.execute("SELECT last_ok FROM status WHERE key = ?", (key,)).fetchone()
            if err:
                errors += 1
                conn.execute("""INSERT INTO status(key, ok, last_try, error) VALUES (?, 0, ?, ?)
                                ON CONFLICT(key) DO UPDATE SET ok = 0, last_try = excluded.last_try, error = excluded.error""",
                             (key, started, err))
                progress(f"  ✗ {src['label']} : {err}")
                continue
            # Première collecte réussie d'une source : ce qu'elle liste déjà n'est pas « nouveau ».
            backfill = 0 if prev and prev["last_ok"] else 1
            n_new = 0
            for it in items:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO items(url, source, title, summary, via, published, first_seen, run_id, backfill)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (it["url"], key, it["title"], it["summary"], it["via"], it["published"], started, run_id, backfill))
                if cur.rowcount:
                    n_new += 1
                elif it["published"]:
                    conn.execute("UPDATE items SET published = ? WHERE url = ? AND published IS NULL",
                                 (it["published"], it["url"]))
            conn.execute("""INSERT INTO status(key, ok, last_try, last_ok, n_items, n_new, error) VALUES (?, 1, ?, ?, ?, ?, NULL)
                            ON CONFLICT(key) DO UPDATE SET ok = 1, last_try = excluded.last_try, last_ok = excluded.last_ok,
                            n_items = excluded.n_items, n_new = excluded.n_new, error = NULL""",
                         (key, started, started, len(items), n_new))
            conn.commit()
            total_new += 0 if backfill else n_new
            progress(f"  ✓ {src['label']} : {len(items)} élément(s), {n_new} nouveau(x)"
                     + (" — première collecte" if backfill else ""))

    # Au-delà de la durée d'archivage, on ne garde que l'adresse et le titre (pour ne pas les
    # signaler de nouveau comme nouveautés si une source les liste encore).
    limit = (datetime.now(timezone.utc) - timedelta(days=cfg["retention_days"])).isoformat(timespec="seconds")
    conn.execute("UPDATE items SET summary = NULL WHERE first_seen < ? AND summary IS NOT NULL", (limit,))
    conn.execute("UPDATE runs SET finished = ?, n_new = ?, n_errors = ? WHERE id = ?", (now(), total_new, errors, run_id))
    conn.commit()
    conn.close()
    progress(f"Collecte terminée : {total_new} nouvel(s) élément(s), {errors} source(s) en échec")
    return {"new": total_new, "errors": errors}


def main(argv=None):
    cfg = load_config()
    keys = [s["key"] for s in cfg["sources"]]
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", choices=keys, metavar="SOURCE", help="clés de sources (voir config.json)")
    args = ap.parse_args(argv)
    run_all(args.only)


if __name__ == "__main__":
    main()
