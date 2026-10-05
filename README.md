# lucierc.github.io

| Adresse | Contenu | Source |
|---|---|---|
| `/` | CV | `site/index.html`, `site/photo.jpg` |
| `/bercy/` | Portail FiPu : Accueil, Repères, Veille, Données | `portail-fipu/`, `reperes-fipu/`, `veille-fipu/`, `donnees-fipu/` |
| `/rss-flux/` | Ancienne adresse de la Veille, redirigée vers `/bercy/veille/` | `site/build.py` |

`.github/workflows/site.yml` collecte les trois outils chaque matin de semaine (5 h 30 UTC),
enregistre leurs bases dans le dépôt (`*/data/`) et publie le site ; un push sur `main`
republie sans collecter. Lancement manuel : *Actions* → *Site* → *Run workflow*.

En local, rien ne change : `FiPu.command` / `FiPu.bat` ouvrent le portail sur
http://127.0.0.1:8760. Pour voir la version publiée : `python3 site/build.py`, puis
`python3 -m http.server -d _site 8790`.

**Les bases de référence sont celles du dépôt.** Avant une collecte locale, `git pull` ;
après, `git push` (sinon la collecte du lendemain matin sur GitHub et la vôtre divergent).

Le dossier `coloc/` n'est pas publié (`.gitignore`).
