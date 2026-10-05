"""Assemble le site publié sur GitHub Pages dans _site/ :

    /             CV (site/index.html, site/photo.jpg)
    /bercy/       portail FiPu : Accueil, Repères, Veille, Données, Textes
    /rss-flux/    ancienne adresse de la Veille, redirigée vers /bercy/veille/

Les pages de Repères, Veille et Textes doivent avoir été générées (update.py, build.py ou page.py de chaque outil).
La page Données n'a pas de serveur en ligne : la base est exportée dans bercy/donnees/donnees.json
et la page calcule ses réponses dans le navigateur.

    python3 site/build.py
"""
import json
import math
import shutil
import sys
from pathlib import Path

SITE = Path(__file__).parent
BERCY = SITE.parent
OUT = BERCY / "_site"

sys.path.insert(0, str(BERCY / "portail-fipu"))
import serve as portail  # noqa: E402  — importe aussi donnees-fipu/web.py

BAR = {"base": "/bercy/", "title": "Bercy", "home": ("/", "Lucie Ricq")}
NOTE = "Version publiée : mise à jour automatiquement chaque matin de semaine, à partir de sources publiques uniquement."
# Les boutons « Actualiser » supposent le serveur local, absent en ligne.
HIDE = "<style>#refresh,#refresh-log,#refresh-panel{display:none!important}</style>"


def _js(obj):
    return json.dumps(obj, ensure_ascii=False, allow_nan=False, default=str).replace("</", "<\\/")


def inject(html, head):
    if "</head>" not in html:
        raise SystemExit("balise </head> absente")
    return html.replace("</head>", head + "</head>", 1)


def _num(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


def donnees_json():
    """Base Données en un fichier : versions, métadonnées, observations [période, valeur, n° de version]."""
    web = portail.donnees_web
    if web is None:
        raise SystemExit("module Données non chargé (voir l'erreur ci-dessus)")
    con = web.store.connect()
    vintages = [r[0] for r in con.execute("SELECT DISTINCT vintage FROM obs ORDER BY vintage")]
    vi = {v: i for i, v in enumerate(vintages)}
    meta = {k: [src, label, unit, freq, ref, updated] for k, src, label, unit, freq, ref, updated in
            con.execute("SELECT key, source, label, unit, freq, ref, updated FROM series")}
    obs = {}
    for key, period, value, vintage in con.execute("SELECT key, period, value, vintage FROM obs ORDER BY key, period, vintage"):
        obs.setdefault(key, []).append([period, _num(value), vi[vintage]])
    con.close()
    return {"vintages": vintages, "meta": meta, "obs": obs, "alias": web.donnees._alias(),
            "catalogue": web.catalogue({}), "etat": web.etat({})}


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    (OUT / ".nojekyll").touch()
    for f in ("index.html", "photo.jpg"):
        shutil.copy(SITE / f, OUT / f)

    for tool, t in portail.TOOLS.items():
        if not (t["dir"] / t["page"]).exists():
            raise SystemExit(f"{t['dir'].name}/{t['page']} absent : lancer d'abord la collecte de l'outil")
        head = HIDE
        if tool == "donnees":
            data = _js(donnees_json())
            write(OUT / "bercy" / "donnees" / "donnees.json", data)
            head += f"<script>window.FIPU_STATIC = {_js({'data': 'donnees.json', 'note': NOTE})};</script>"
            print(f"→ bercy/donnees/donnees.json ({len(data.encode()) // 1024} Ko)")
        write(OUT / "bercy" / tool / "index.html", inject(portail.page_html(tool, **BAR), head))

    overview = portail.overview() | {"note": NOTE}
    write(OUT / "bercy" / "index.html", inject(portail.page_html(None, **BAR), f"{HIDE}<script>window.FIPU_OVERVIEW = {_js(overview)};</script>"))

    write(OUT / "rss-flux" / "index.html",
          '<!doctype html><meta charset="utf-8"><title>Veille FiPu</title>'
          '<meta http-equiv="refresh" content="0; url=/bercy/veille/"><link rel="canonical" href="/bercy/veille/">'
          '<p>Page déplacée : <a href="/bercy/veille/">/bercy/veille/</a></p>')

    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"→ {OUT.relative_to(BERCY)}/ ({size // 1024} Ko)")


if __name__ == "__main__":
    main()
