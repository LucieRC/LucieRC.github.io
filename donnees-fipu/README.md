# Données FiPu

Base locale des séries publiques de finances publiques (Eurostat, Insee). **Chaque version
publiée est conservée** : on peut retrouver un chiffre tel qu'il était connu à une date
donnée et suivre ses révisions.

Complète [Repères FiPu](../reperes-fipu/) (qui est en poste, chiffres clés, Journal officiel) :
ici, les séries détaillées à interroger, comparer et exporter.

## Utilisation

Page de consultation (recherche, graphiques, tableaux, révisions, export) : lancer le
portail (`FiPu.command` / `FiPu.bat` dans le dossier parent), onglet **Données**.

En ligne de commande :

```bash
pip install -r requirements.txt
python3 update.py                               # collecte (≈ 30 s) ; relancer régulièrement
python3 update.py --only budget_etat            # une seule source

python3 donnees.py cherche tva recettes         # trouver une série
python3 donnees.py voir deficit dette --depuis 2015
python3 donnees.py voir deficit --au 2026-04-22 # tel que connu à cette date
python3 donnees.py revisions deficit            # versions successives
python3 donnees.py export deficit dette po -o chiffres.xlsx
python3 donnees.py etat                         # dernière collecte de chaque source
```

Depuis Python ou un notebook (lancé dans ce dossier) :

```python
import donnees as d
d.tableau(["deficit", "dette", "interets"], depuis="2010")
d.serie("gov_10a_exp.PC_GDP.S13.GF09.TE.FR")     # enseignement, % du PIB
d.cherche("gov_10a_exp", "sante", "PC_GDP", ".DE")   # tous les mots doivent figurer (sous-chaînes)
d.revisions("dette_trim")
```

L'export Excel contient une feuille « sources » (libellé exact, unité, jeu de données,
date de mise à jour par la source, date de version) : de quoi citer le chiffre sans ambiguïté.

## Contenu (config.json)

| Source | Contenu | Pays |
|---|---|---|
| `notif_pde` | Solde, dette, intérêts, PIB de la notification PDE (APU et sous-secteurs) | comparateurs |
| `apu_annuel` | Comptes des APU : dépenses et recettes par opération, sous-secteurs | comparateurs |
| `cofog` | Dépenses par fonction (niveau 1), en % du PIB, Md€ et % du total | comparateurs |
| `cofog_fr_detail` | Dépenses par fonction, tous niveaux, par opération | France |
| `prelevements` | Impôts et cotisations par catégorie (93 postes), par sous-secteur | France |
| `prelevements_ue` | Taux de PO et grandes catégories | comparateurs |
| `fp_insee` | Principaux agrégats de finances publiques en % du PIB : dépenses, recettes, déficit, dette brute et nette, prélèvements obligatoires (Insee, Comptes de la Nation, depuis 2018) | France |
| `apu_annuel_insee` | Comptes annuels des APU par sous-secteur et opération, en M€ : impôts par catégorie, cotisations, intérêts, rémunérations, investissement, solde (Insee, catalogue de données `DD_CNA_APU`) | France |
| `apu_trim`, `dette_trim_ue` | Comptes trimestriels et dette trimestrielle (Eurostat) | France / comparateurs |
| `pib` | PIB en valeur, volume et prix | comparateurs |
| `budget_etat` | Situation mensuelle du budget de l'État (cumul depuis janvier) | Insee |
| `dette_trim_insee`, `dette_etat` | Dette de Maastricht trimestrielle par instrument et sous-secteur ; dette négociable de l'État | Insee |
| `apu_trim_insee`, `pib_trim_insee` | Comptes trimestriels des APU et PIB (base 2020) | Insee |

Comparateurs : FR, DE, IT, ES, NL, BE, zone euro, UE (liste `comparateurs`).
Les **alias** (`deficit`, `dette`, `po`, `pib`, `budget_etat_solde`…) sont définis dans
`config.json`, section `alias`. Un alias peut lister plusieurs séries équivalentes : on retient
celle dont la dernière année est la plus récente, la première de la liste en cas d'égalité. Pour la
France, l'Insee est cité en premier, puisqu'il publie avant Eurostat (comptes des APU fin mars et
fin mai ; Eurostat les reprend en avril et en octobre) : Eurostat ne prend le relais que s'il a une
année de plus (en avril-mai, avant l'édition Insee de fin mai). `po` est le taux de prélèvements
obligatoires au sens national (Insee) ; l'agrégat d'Eurostat, de définition différente
(45,2 % en 2024 contre 42,7 %), reste disponible sous `po_eurostat`.

**Chaque année, fin mai** : mettre à jour l'adresse de la page Insee de `fp_insee` (« Finances
publiques en <année> », édition des Comptes de la Nation). Passé le 15 juin, la source passe en
échec tant que l'adresse désigne l'édition précédente.

Ajouter des séries : ajouter une valeur à un filtre ou une entrée à `sources`, puis
relancer `update.py`. Les codes se trouvent dans le navigateur de données d'Eurostat
(nom du jeu de données, codes des dimensions) ou dans la BDM de l'Insee (nom du jeu de
données ; le filtre `title` retient les séries dont le titre correspond à l'expression).

## Clés des séries

- Eurostat : `jeu.dimension1.dimension2…` dans l'ordre des dimensions du jeu, sans la
  fréquence ni le temps. Ex. `gov_10dd_edpt1.PC_GDP.S13.B9.FR`.
- Insee : `insee.<idbank>`. Ex. `insee.001717255`.

## Fichiers

| Fichier | Rôle |
|---|---|
| `sources.py` | Lecture d'Eurostat (JSON-stat) et de la BDM Insee (SDMX) |
| `store.py` | Base SQLite `data/donnees.sqlite` : séries, observations versionnées, journal des collectes |
| `update.py` | Collecte ; une source en échec n'empêche pas les autres et garde ses dernières valeurs |
| `donnees.py` | Consultation, révisions, recherche, export (Python et ligne de commande) |
| `web.py`, `page.html` | Page Données : réponses JSON et interface, servies par `portail-fipu` |

## Collecte automatique

L'historique des versions ne se constitue qu'à partir de la première collecte, et
seulement là où elle tourne. La collecte de référence tourne désormais sur GitHub chaque
matin de semaine (`../.github/workflows/site.yml`), et `data/donnees.sqlite` est enregistrée
dans le dépôt : avant une collecte locale, `git pull` ; après, `git push`. La page est publiée
sur https://lucierc.github.io/bercy/donnees/ (sans serveur : la base y est exportée en JSON
par `../site/build.py`, l'export Excel se fait dans le navigateur).

Les instructions ci-dessous ne servent que pour une collecte locale planifiée.

- Windows : Planificateur de tâches → Créer une tâche de base → quotidienne →
  « Démarrer un programme » : `Mettre à jour.bat` (ou `py -3 update.py`, dossier de départ
  = ce dossier).
- macOS : `crontab -e`, puis
  `30 8 * * 1-5 cd "/chemin/vers/donnees-fipu" && /usr/bin/env python3 update.py >> data/cron.log 2>&1`

## Limites connues

- Les versions antérieures à la première collecte ne sont pas disponibles : la base ne
  « voit » que les publications postérieures à son installation. Les versions passées
  (prévisions et premières estimations publiées) relèvent de l'outil de suivi des
  millésimes, à construire.
- `vintage` est la date de la collecte, pas la date de publication par la source ;
  `series.updated` garde la date de mise à jour déclarée par la source.
- Changement de base Insee : les nouvelles séries ont de nouveaux idbanks ; les séries
  arrêtées sont ignorées. Mettre à jour les jeux de données (`…-2020`) et les alias en
  conséquence.
- Montants Insee : unité indiquée par la source (ex. `EUROS (×10^6)` = millions d'euros).
