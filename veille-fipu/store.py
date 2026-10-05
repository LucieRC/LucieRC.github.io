"""Base locale (SQLite, bibliothèque standard) : data/veille.sqlite.

items   : un élément par adresse, avec la date à laquelle l'outil l'a vu pour la première fois
runs    : une ligne par collecte (sert à délimiter « le dernier brief »)
status  : état de chaque source à la dernière collecte
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent
DB = ROOT / "data" / "veille.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    url TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    via TEXT,
    published TEXT,
    first_seen TEXT NOT NULL,
    run_id INTEGER,
    backfill INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS items_first_seen ON items(first_seen);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started TEXT NOT NULL,
    finished TEXT,
    n_new INTEGER,
    n_errors INTEGER
);
CREATE TABLE IF NOT EXISTS status (
    key TEXT PRIMARY KEY,
    ok INTEGER,
    last_try TEXT,
    last_ok TEXT,
    n_items INTEGER,
    n_new INTEGER,
    error TEXT
);
"""


def connect(path=DB):
    path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
