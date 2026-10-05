"""Interroger la base : depuis Python (import donnees) ou en ligne de commande.

    python3 donnees.py cherche tva recettes          # trouver des séries (mots du libellé ou de la clé)
    python3 donnees.py voir deficit dette --depuis 2015
    python3 donnees.py voir deficit --au 2026-04-22  # valeurs telles que connues à cette date
    python3 donnees.py revisions deficit --depuis 2019
    python3 donnees.py export deficit dette po -o chiffres.xlsx
    python3 donnees.py etat                           # dernière collecte de chaque source

Depuis Python :

    import donnees as d
    d.serie("deficit")                  # pandas.Series indexée par période
    d.tableau(["deficit", "dette"], depuis="2015")
    d.revisions("deficit")              # une colonne par version enregistrée
    d.cherche("gov_10a_exp", "enseignement", ".FR")

Une série se désigne par sa clé (colonne « key » de `cherche`) ou par un alias de config.json.
"""
import argparse
import json
import sys
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd

import store

ROOT = Path(__file__).parent


def _alias():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("alias", {})


def resolve(name):
    """Clé de la série désignée par une clé ou un alias ; erreur explicite sinon."""
    key = _alias().get(name, name)
    with store.connect() as con:
        if not con.execute("SELECT 1 FROM series WHERE key=?", (key,)).fetchone():
            raise KeyError(f"série inconnue : {name!r} (chercher avec : python3 donnees.py cherche <mots>)")
    return key


def serie(name, au=None, depuis=None):
    """Valeurs de la série telles que connues à la date `au` (AAAA-MM-JJ ; par défaut : dernière version)."""
    key = resolve(name)
    au = au or "9999-12-31"
    with store.connect() as con:
        rows = con.execute(
            """SELECT period, value FROM obs o WHERE key=? AND vintage=(
                   SELECT MAX(vintage) FROM obs WHERE key=o.key AND period=o.period AND vintage<=?)
               ORDER BY period""", (key, au)).fetchall()
        m = store.meta(con, key)
    s = pd.Series({p: v for p, v in rows}, name=name, dtype="float64")
    if depuis:
        s = s[s.index >= str(depuis)]
    s.attrs = m
    return s


def tableau(names, au=None, depuis=None):
    """Plusieurs séries côte à côte (une colonne par série, dans l'ordre demandé)."""
    df = pd.concat([serie(n, au, depuis) for n in names], axis=1)
    return df.sort_index()


def revisions(name, depuis=None):
    """Historique des versions : une ligne par période, une colonne par date de collecte où la série a changé."""
    key = resolve(name)
    with store.connect() as con:
        rows = con.execute("SELECT period, vintage, value FROM obs WHERE key=?", (key,)).fetchall()
    df = pd.DataFrame(rows, columns=["period", "vintage", "value"]).pivot(index="period", columns="vintage", values="value")
    # Une valeur non révisée reste valable dans les versions suivantes.
    df = df.sort_index(axis=1).ffill(axis=1).sort_index()
    if depuis:
        df = df[df.index >= str(depuis)]
    df.columns.name = "version du"
    return df


def _fold(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def cherche(*mots, source=None):
    """Séries dont la clé ou le libellé contient tous les mots (sans tenir compte des accents ni de la casse)."""
    with store.connect() as con:
        rows = con.execute("SELECT key, source, label, unit, freq FROM series ORDER BY key").fetchall()
    mots = [_fold(m) for m in mots]
    keep = [r for r in rows
            if (source is None or r[1] == source)
            and all(m in _fold(r[0] + " " + r[2] + " " + r[3]) for m in mots)]
    alias = {v: k for k, v in _alias().items()}
    df = pd.DataFrame(keep, columns=["key", "source", "label", "unit", "freq"])
    df.insert(1, "alias", [alias.get(k, "") for k in df["key"]])
    return df


def etat():
    """Dernière collecte de chaque source (succès ou erreur)."""
    with store.connect() as con:
        rows = con.execute(
            """SELECT source, MAX(at), ok, n_series, n_changed, error FROM runs GROUP BY source ORDER BY source""").fetchall()
    return pd.DataFrame(rows, columns=["source", "dernière collecte", "ok", "séries", "valeurs changées", "erreur"])


def export(names, path, au=None, depuis=None):
    """Classeur Excel : une feuille « données », une feuille « sources » (libellé, unité, origine, version).

    `path` : chemin de fichier ou flux binaire (io.BytesIO)."""
    df = tableau(names, au, depuis)
    with store.connect() as con:
        metas = [store.meta(con, resolve(n)) for n in names]
    src = pd.DataFrame([{
        "colonne": n, "clé": m["key"], "libellé": m["label"], "unité": m["unit"], "origine": m["ref"],
        "mise à jour par la source": m["updated"], "valeurs telles que connues au": au or date.today().isoformat(),
    } for n, m in zip(names, metas)])
    with pd.ExcelWriter(path) as xw:
        df.to_excel(xw, sheet_name="données", index_label="période")
        src.to_excel(xw, sheet_name="sources", index=False)
    return path


def _print(df):
    with pd.option_context("display.max_rows", 500, "display.max_columns", 30, "display.width", 200,
                           "display.max_colwidth", 110):
        print(df.to_string())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("cherche", help="trouver des séries")
    p.add_argument("mots", nargs="+")
    p.add_argument("--source", help="identifiant de source (config.json)")
    for name in ("voir", "export"):
        p = sub.add_parser(name, help="afficher" if name == "voir" else "exporter en .xlsx")
        p.add_argument("series", nargs="+", help="clés ou alias")
        p.add_argument("--depuis", help="première période, ex. 2015 ou 2020-Q1")
        p.add_argument("--au", help="date de version AAAA-MM-JJ (par défaut : la plus récente)")
        if name == "export":
            p.add_argument("-o", "--sortie", required=True, help="fichier .xlsx")
    p = sub.add_parser("revisions", help="versions successives d'une série")
    p.add_argument("serie")
    p.add_argument("--depuis")
    sub.add_parser("etat", help="dernière collecte de chaque source")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "cherche":
            df = cherche(*a.mots, source=a.source)
            _print(df[["key", "alias", "label", "unit"]] if len(df) else "aucune série")
            if len(df):
                print(f"\n{len(df)} série(s)")
        elif a.cmd == "voir":
            df = tableau(a.series, a.au, a.depuis)
            _print(df)
            for n in a.series:
                m = serie(n).attrs
                print(f"\n{n} : {m['label']} [{m['unit']}] — {m['ref']}")
        elif a.cmd == "revisions":
            _print(revisions(a.serie, a.depuis))
        elif a.cmd == "export":
            print(f"→ {export(a.series, a.sortie, a.au, a.depuis)}")
        elif a.cmd == "etat":
            _print(etat())
    except KeyError as e:
        sys.exit(e.args[0])


if __name__ == "__main__":
    main()
