# Veille FiPu

Brief quotidien des publications utiles aux finances publiques : institutions françaises,
UE et international, recherche et think tanks, presse. Les éléments sont classés par mots-clés
pondérés, sans résumé automatique : titre, source, date, premières lignes, lien.

Le Journal officiel, les titulaires des postes et les chiffres clés sont dans **Repères FiPu**
(`../reperes-fipu`), vers lequel la page renvoie.

## Utilisation

```bash
pip install -r requirements.txt   # requests, beautifulsoup4
python3 update.py                 # collecte + génération  →  dist/veille-fipu.html
python3 fetch.py --only hcfp igf  # ne relire que certaines sources
python3 build.py                  # régénérer la page sans recollecter (après un changement de mots-clés)
python3 serve.py                  # page sur http://127.0.0.1:8766 avec un bouton « Actualiser »
```

Double-cliquer sur `Veille FiPu.command` (macOS) ou `Veille FiPu.bat` (Windows) lance `serve.py`.
`dist/veille-fipu.html` est un fichier unique, lisible sans serveur ni connexion.

**La page** : *Nouveautés* (depuis le dernier brief, 7 ou 30 jours, par catégorie et par source,
avec un seuil de pertinence), *Archive* (recherche plein texte sur 90 jours), *Sources* (état de
chaque source à la dernière collecte), *Mots-clés* (ce qui fait le score).

**Le dernier brief** = ce que l'outil a vu pour la première fois depuis la collecte précédente
datant d'au moins 12 h (`brief_min_hours`). Plusieurs collectes dans la même matinée forment donc
un seul brief. À la toute première collecte d'une source, ce qu'elle liste déjà n'est pas compté
comme nouveau, sauf ce qui a été publié dans les 2 derniers jours.

**Articles similaires** : quand plusieurs médias reprennent le même sujet (titres qui partagent
60 % de leurs mots sur 3 jours), un seul élément est affiché, les autres sont repliés dessous.

## Lancer la veille chaque matin

**Windows (Planificateur de tâches)** :

```bat
schtasks /Create /TN "Veille FiPu" /SC WEEKDAY /ST 07:30 /TR "py -3 C:\chemin\vers\veille-fipu\update.py"
```

Dans les propriétés de la tâche, cocher « Exécuter la tâche dès que possible si un démarrage
planifié est manqué » : le brief se fait alors à l'ouverture de session si le poste était éteint.

**macOS (cron)** : `crontab -e`, puis

```
30 7 * * 1-5 cd "/Users/…/veille-fipu" && /usr/bin/env python3 update.py >> data/cron.log 2>&1
```

(cron ne rattrape pas une exécution manquée ; `launchd` le fait, avec un fichier `.plist` dans
`~/Library/LaunchAgents` et `StartCalendarInterval`.)

## En ligne

La Veille est publiée avec les autres outils sur https://lucierc.github.io/bercy/veille/ :
voir `../README.md` et `../.github/workflows/site.yml`. En ligne, le bouton « Actualiser » est
masqué ; la collecte a lieu chaque matin de semaine sur GitHub.

## Ajouter une source

Dans `config.json`, ajouter une entrée à `sources` :

| Type | Réglages | Quand l'utiliser |
|---|---|---|
| `rss` | `url` du flux RSS ou Atom | le site publie un flux (chercher « RSS » en bas de page, ou `<link rel="alternate">` dans le code source) |
| `html` | `url` de la page de liste ; `html.item` (sélecteur CSS d'un bloc par publication), `html.link` (expression régulière sur l'adresse des liens), et en option `html.title`, `html.summary`, `html.date` | pas de flux, mais une page qui liste les publications |
| `gnews` | `query` (syntaxe Google : guillemets, `OR`, `site:`), `days` (7 par défaut) | le site bloque les robots, ou pour une recherche thématique dans la presse |

Communs : `key` (unique), `label`, `category` (`institutions`, `international`, `recherche`,
`presse`), `boost` (points ajoutés à chaque élément de la source), `max_items`, `enabled`
(`false` pour garder une source en réserve), `note` (affichée dans le tableau des sources).

Tester une source seule : `python3 fetch.py --only <key>` puis `python3 build.py`.

## Modifier les mots-clés

`keywords` dans `config.json` : chaque ligne a un thème, un poids et des termes. Une ligne compte
une fois : son poids si un terme est dans le résumé, ×2 (`title_weight`) s'il est dans le titre.
S'ajoutent le bonus de la catégorie et celui de la source. Poids négatif = pénalité (hors champ).
Les termes s'écrivent en minuscules sans accents ; `impot*` accepte toute terminaison.
`min_score` fixe le seuil d'affichage des nouveautés. Relancer `python3 build.py` pour appliquer.

## Fichiers

| Fichier | Rôle |
|---|---|
| `config.json` | Sources, catégories, mots-clés, seuils |
| `sources.py` | Lecture des flux RSS/Atom, des pages HTML et de Google Actualités ; dates en français |
| `fetch.py` | Collecte (une source en échec n'arrête pas les autres) → `data/veille.sqlite` |
| `store.py` | Base SQLite : éléments (clé = adresse, date de première vue), collectes, état des sources |
| `score.py` | Score de pertinence |
| `build.py` | Score, regroupement des articles similaires, page → `dist/veille-fipu.html` |
| `template.html` | Mise en page et rendu (JavaScript) |
| `serve.py` | Serveur local (127.0.0.1 uniquement) pour le bouton « Actualiser » |

## Limites connues

- Pas de flux direct pour le FMI, l'OCDE, l'Institut Montaigne, l'AFT, budget.gouv.fr, le CAE et
  Les Echos (sites qui refusent les robots ou pages JavaScript) : ils passent par Google
  Actualités, qui ne voit pas tout et renvoie des liens `news.google.com` (redirection vers l'article).
- Les lecteurs `html` dépendent de la structure des pages. Si un site change, la source passe en
  échec (bandeau en haut de la page) : corriger ses sélecteurs dans `config.json`.
- Certaines listes n'ont pas de date (avis du HCFP, iFRAP) : la date affichée est alors celle
  où l'outil a vu l'élément pour la première fois.
- Les flux de presse ne donnent que titre et chapeau ; les articles payants restent payants.
- Le score est un simple comptage de mots-clés : il faut l'ajuster à l'usage.
- Au-delà de 90 jours (`retention_days`), les éléments sortent de la page ; la base garde leur
  adresse et leur titre pour ne pas les signaler de nouveau.
