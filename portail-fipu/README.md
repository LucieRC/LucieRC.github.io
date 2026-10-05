# Portail FiPu

Une seule adresse locale pour les trois outils :

| Onglet | Outil | Contenu |
|---|---|---|
| Accueil | — | Derniers chiffres publiés, état de chaque outil, « Tout actualiser » |
| Repères | `../reperes-fipu` | Qui est en poste, gouvernement, Journal officiel, chiffres clés, cadre et calendrier |
| Veille | `../veille-fipu` | Publications et presse classées par mots-clés |
| Données | `../donnees-fipu` | Séries Eurostat et Insee : recherche, graphiques, tableaux, révisions, export Excel |

## Lancer

Double-cliquer `FiPu.command` (macOS) ou `FiPu.bat` (Windows) dans le dossier parent, ou :

```bash
python3 serve.py            # http://127.0.0.1:8760, ouvert dans le navigateur
```

Le serveur n'écoute que sur ce poste (127.0.0.1). Une vue de la page Données se retrouve
par son adresse (séries, période et version sont dans l'URL) : on peut la mettre en favori.

## Fonctionnement

- Les pages de Repères et Veille sont servies telles quelles ; le portail ajoute la barre de
  navigation et redirige leurs appels `/api/…` vers `/reperes/api/…` et `/veille/api/…`.
- « Actualiser » lance `update.py` de l'outil dans un processus séparé ; la progression
  s'affiche dans la page (et dans la console du portail).
- La page Données est servie par le portail lui-même (`donnees-fipu/web.py`).
- Les outils restent autonomes : leurs propres lanceurs (`Repères FiPu.command`,
  `Veille FiPu.command`…) fonctionnent toujours, sur leurs ports habituels.

## Limites connues

- Les réécritures d'adresse supposent que Repères et Veille appellent `fetch("/api/…")` ;
  si l'un d'eux change sa façon d'appeler son serveur, son bouton « Actualiser » cessera de
  fonctionner dans le portail (la page reste lisible).
- Un seul portail à la fois (port 8760) ; `--port` pour en changer.
