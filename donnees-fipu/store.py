"""Base locale (SQLite) qui conserve chaque version publiée des séries.

Une observation n'est réécrite que lorsque sa valeur change : la table `obs` contient donc
l'historique des révisions. `vintage` = date de la collecte où la valeur a été vue pour la
première fois (et non date de publication par la source, enregistrée à part dans `series.updated`).
"""
import math
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

DB = Path(__file__).parent / "data" / "donnees.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    key TEXT PRIMARY KEY, source TEXT, label TEXT, unit TEXT, freq TEXT, ref TEXT,
    updated TEXT, first_seen TEXT, last_checked TEXT
);
CREATE TABLE IF NOT EXISTS obs (
    key TEXT, period TEXT, value REAL, vintage TEXT,
    PRIMARY KEY (key, period, vintage)
);
CREATE TABLE IF NOT EXISTS runs (
    source TEXT, at TEXT, ok INTEGER, n_series INTEGER, n_changed INTEGER, error TEXT
);
"""


def connect(path=None):
    path = path or DB
    path.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def _same(a, b):
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


def save(con, source_id, series, today=None):
    """Enregistre les séries d'une source ; renvoie le nombre d'observations nouvelles ou révisées."""
    today = today or date.today().isoformat()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    changed = 0
    for s in series:
        con.execute(
            """INSERT INTO series VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET source=excluded.source, label=excluded.label, unit=excluded.unit,
               freq=excluded.freq, ref=excluded.ref, updated=excluded.updated, last_checked=excluded.last_checked""",
            (s["key"], source_id, s["label"], s["unit"], s["freq"], s["ref"], s["updated"], today, now))
        latest = dict(con.execute(
            """SELECT period, value FROM obs o WHERE key=? AND vintage=(
                   SELECT MAX(vintage) FROM obs WHERE key=o.key AND period=o.period)""", (s["key"],)))
        rows = [(s["key"], p, v, today) for p, v in s["obs"].items() if p not in latest or not _same(latest[p], v)]
        # Une seconde collecte le même jour remplace la version du jour (INSERT OR REPLACE).
        con.executemany("INSERT OR REPLACE INTO obs VALUES (?,?,?,?)", rows)
        changed += len(rows)
    return changed


def log_run(con, source_id, ok, n_series=0, n_changed=0, error=None):
    con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)",
                (source_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), int(ok), n_series, n_changed, error))


def meta(con, key):
    row = con.execute("SELECT key, source, label, unit, freq, ref, updated, first_seen, last_checked FROM series WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    return dict(zip(["key", "source", "label", "unit", "freq", "ref", "updated", "first_seen", "last_checked"], row))

