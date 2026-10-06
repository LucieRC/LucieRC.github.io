# Repères FiPu

Page de repères pour le suivi des finances publiques : qui est en poste, mouvements
publiés au Journal officiel, composition du Gouvernement, chiffres clés, budget en
cours, historique depuis 2002, textes de référence.

**Principe : aucune information n'est écrite à la main.** Tout est collecté depuis des
sources publiques décrites dans `config.json`, repris tel quel (pas de résumé), avec sa
source et sa date. L'outil contrôle lui-même la cohérence de ses sources à chaque collecte.

## Utilisation

| Besoin | Commande |
|---|---|
| Ouvrir la page avec le bouton « Actualiser » | double-cliquer `Repères FiPu.command` (Mac) ou `Repères FiPu.bat` (Windows), ou `python3 serve.py` |
| Actualiser sans ouvrir la page | `python3 update.py` |
| Ne rafraîchir qu'une partie | `python3 fetch.py --only figures jorf` puis `python3 build.py` |
| Vérifier les extracteurs (hors ligne) | `python3 -m unittest discover tests` |

La page générée, `dist/reperes-fipu.html`, est un fichier unique qui fonctionne hors
ligne : on peut l'envoyer tel quel. Une copie envoyée est figée à la date de ses données
(affichée en haut) ; seul l'outil lancé via `serve.py` peut l'actualiser.

Installation : Python 3.10+, puis `pip install -r requirements.txt`. Première collecte ≈ 1 à 2 min
(90 jours de Journal officiel), ensuite ≈ 15 s.

## Sources

| Bloc | Source | Ce qui est repris |
|---|---|---|
| Mouvements | Journal officiel — sommaires open data de la DILA (`echanges.dila.gouv.fr/OPENDATA/JORF`) | Intitulé exact, rubrique, ministère, lien Légifrance ; filtres définis dans `config.json` |
| Titulaires | Wikipédia (infobox, listes, page du gouvernement) | Nom, date de prise de fonction ; début de la page de la personne et sa photo, **uniquement si la source renvoie vers sa page** (pas de recherche par nom : homonymes) |
| Gouvernement | Page Wikipédia du gouvernement en fonction, trouvée via « Liste des gouvernements de la France » | Organisation fonctionnelle, évolutions de composition, numéros NOR |
| Historiques | Listes Wikipédia des gouvernements, ministres de l'Économie, ministres du Budget | |
| Chiffres | Eurostat (API publique, libellés officiels en français) ; Insee (BDM) pour la dette trimestrielle, publiée plus tôt qu'à Eurostat | Séries listées dans `config.json` |
| Budget, références, calendrier | Wikipédia : introductions et sections nommées dans `config.json` | Texte intégral de l'introduction / de la section |

Non retenus : info.gouv.fr (protection anti-robot), Wikidata (titulaires récents
incomplets), texte intégral des « Informations parlementaires » du JO (absent de l'open data).

## Faire évoluer l'outil sans le recoder

Tout se fait dans `config.json`, puis `python3 update.py` (ou `build.py` si seuls les filtres changent) :

- **ajouter un poste** : une entrée dans `officials` ; `kind` = `infobox` (page + champ),
  `government_role` (motif sur l'intitulé dans le gouvernement en fonction), `prose`
  (expression régulière dans le texte d'une page) ou `list_last_row` (dernière ligne d'un tableau) ;
- **ajouter un filtre du JO** : une entrée dans `jorf.filters` ; critères `title`, `section`,
  `ministry`, `path` (expressions régulières, insensibles à la casse, toutes requises) ;
- **ajouter une série** : une entrée dans `eurostat` (code du jeu de données et filtres tels
  qu'affichés dans le navigateur de données Eurostat), ou, pour une série Insee,
  `"provider": "insee"` et son `idbank` (numéro affiché sur la page de la série) ;
- **ajouter une page de référence ou une section de calendrier** : `reference`, `calendar`.

## Tenue dans le temps

- Rien n'est figé dans le code : gouvernement en fonction, pages de budget (année courante
  et suivante), archives du JO sont découverts à chaque collecte.
- Chaque bloc est collecté séparément : une source en échec garde sa dernière version valide
  et un bandeau le signale.
- **Contrôles de cohérence** (en haut de la page) : un seul gouvernement en fonction, Premier
  ministre identique entre deux pages, ministres identiques entre gouvernement et historiques,
  JO récent, Wikipédia à jour du dernier décret « relatif à la composition du Gouvernement »,
  pages de titulaires modifiées récemment, séries Eurostat et Insee récentes, pages de référence trouvées.
  Un contrôle en échec indique quel extracteur ou quelle source regarder.
- `data/changelog.json` garde la trace des changements de titulaires détectés d'une collecte à l'autre.
- Le JO n'est complet qu'à partir du premier jour lu (date affichée) ; conservation 400 jours.

## Limites

- Wikipédia est à jour rapidement mais n'est pas une source officielle ; le JO fait foi.
- Si une page change de structure (nom de section, colonnes), le contrôle correspondant échoue ;
  corriger alors l'extracteur concerné dans `fetch.py` et relancer les tests.
- Les textes de référence sont ceux de Wikipédia à la date de collecte : certains peuvent être
  anciens (ex. calendrier du Semestre européen antérieur à la réforme de 2024) ; leur date de
  dernière modification est affichée.
