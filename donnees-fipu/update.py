"""Collecte toutes les sources de config.json et enregistre les nouvelles valeurs.

    python3 update.py                      # tout
    python3 update.py --only pib budget_etat

Une source en échec n'empêche pas les autres ; l'erreur est journalisée (table `runs`)
et la base garde les dernières valeurs connues.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import sources
import store

ROOT = Path(__file__).parent


def load_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def run(only=None, progress=print):
    cfg = load_config()
    todo = [s for s in cfg["sources"] if not only or s["id"] in only]
    unknown = set(only or []) - {s["id"] for s in cfg["sources"]}
    if unknown:
        raise SystemExit(f"source(s) inconnue(s) : {', '.join(sorted(unknown))}")
    con = store.connect()
    failed = []
    for src in todo:
        t0 = time.time()
        try:
            series = sources.fetch(src, cfg)
            n = store.save(con, src["id"], series)
            store.log_run(con, src["id"], True, len(series), n)
            progress(f"  ok      {src['id']:<18} {len(series):>5} séries, {n:>6} valeurs nouvelles ou révisées ({time.time() - t0:.0f} s)")
        except Exception as e:  # noqa: BLE001 — une source en échec ne bloque pas les autres
            store.log_run(con, src["id"], False, error=f"{type(e).__name__}: {e}")
            failed.append(src["id"])
            progress(f"  ÉCHEC   {src['id']:<18} {type(e).__name__}: {str(e)[:200]}")
        con.commit()
    con.close()
    progress(f"{len(todo) - len(failed)}/{len(todo)} sources à jour" + (f" ; en échec : {', '.join(failed)}" if failed else ""))
    return failed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", metavar="SOURCE", help="identifiants de sources (voir config.json)")
    args = ap.parse_args(argv)
    sys.exit(1 if run(args.only) else 0)


if __name__ == "__main__":
    main()
