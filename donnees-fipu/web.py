"""Réponses JSON de la page Données (servie par portail-fipu).

Chaque fonction reçoit les paramètres de la requête (dict de listes, comme parse_qs)
et renvoie un objet sérialisable ; les erreurs de saisie lèvent KeyError / ValueError.
"""
import io
import json
import math
from datetime import date
from pathlib import Path

import donnees
import store

ROOT = Path(__file__).parent
PAGE = ROOT / "page.html"
MAX_RESULTS = 300


def _one(q, name, default=None):
    v = q.get(name) or [default]
    return v[0] or default


def _num(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


def _config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def catalogue(q):
    """Sources et alias, pour les menus de la page."""
    cfg = _config()
    with store.connect() as con:
        counts = dict(con.execute("SELECT source, COUNT(*) FROM series GROUP BY source"))
        labels = dict(con.execute("SELECT key, label FROM series"))
    return {
        "sources": [{"id": s["id"], "label": s["label"], "provider": s["provider"], "n": counts.get(s["id"], 0)}
                    for s in cfg["sources"]],
        "alias": [{"alias": a, "key": k, "label": labels.get(k, "")} for a, k in donnees._alias().items()],
    }


def cherche(q):
    mots = (_one(q, "q", "") or "").split()
    df = donnees.cherche(*mots, source=_one(q, "source"))
    total = len(df)
    df = df.head(MAX_RESULTS)
    return {"total": total, "results": df.to_dict("records")}


def series(q):
    names = q.get("k") or []
    if not names:
        raise ValueError("aucune série demandée")
    au, depuis = _one(q, "au"), _one(q, "depuis")
    out = []
    for n in names:
        s = donnees.serie(n, au, depuis)
        m = s.attrs
        out.append({"name": n, "key": m["key"], "label": m["label"], "unit": m["unit"], "freq": m["freq"],
                    "ref": m["ref"], "updated": m["updated"], "source": m["source"],
                    "obs": [[p, _num(v)] for p, v in s.items()]})
    return {"au": au, "series": out}


def revisions(q):
    n = _one(q, "k")
    if not n:
        raise ValueError("aucune série demandée")
    df = donnees.revisions(n, _one(q, "depuis"))
    return {"name": n, "vintages": list(df.columns),
            "rows": [{"period": p, "values": [_num(v) for v in row]} for p, row in df.iterrows()]}


def etat(q):
    df = donnees.etat()
    with store.connect() as con:
        n_series, n_obs = con.execute("SELECT (SELECT COUNT(*) FROM series), (SELECT COUNT(*) FROM obs)").fetchone()
    return {"n_series": n_series, "n_obs": n_obs,
            "runs": [{k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r.items()}
                     for r in df.to_dict("records")]}


def resume(q):
    """Derniers chiffres des alias principaux, pour l'accueil du portail."""
    out = []
    # dette : la trimestrielle, publiée chaque trimestre, plutôt que l'annuelle
    for a in ("deficit", "dette_trim", "po", "depense", "interets"):
        try:
            s = donnees.serie(a).dropna()
        except KeyError:
            continue
        if len(s):
            p = s.index[-1]
            year_before = str(int(p[:4]) - 1) + p[4:]  # même période un an plus tôt : 2025-Q2 pour 2026-Q2
            out.append({"alias": a, "label": s.attrs["label"], "unit": s.attrs["unit"],
                        "period": p, "value": s.iloc[-1], "previous": s.get(year_before)})
    return {"figures": out}


def export(q):
    """Classeur .xlsx (octets) pour les séries demandées."""
    names = q.get("k") or []
    if not names:
        raise ValueError("aucune série demandée")
    buf = io.BytesIO()
    donnees.export(names, buf, _one(q, "au"), _one(q, "depuis"))
    stamp = _one(q, "au") or date.today().isoformat()
    return buf.getvalue(), f"donnees-fipu-{stamp}.xlsx"


ROUTES = {"catalogue": catalogue, "cherche": cherche, "series": series, "revisions": revisions,
          "etat": etat, "resume": resume}
