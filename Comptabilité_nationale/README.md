# Textes — SEC 2010 et MGDD 2022

Interroger les deux textes de référence de la comptabilité nationale des administrations publiques :
le **SEC 2010** (règlement UE n° 549/2013, version française, 762 p.) et le **MGDD 2022** (Manual on
Government Deficit and Debt d'Eurostat, en anglais, 482 p.).

## Trois usages

| Usage | Comment |
|---|---|
| **Analyser un cas** (« comment classer / enregistrer… ? ») | Ouvrir Claude Code dans ce dossier (ou dans `Bercy/`) et poser la question. Le skill `compta-nat` (`.claude/skills/compta-nat/SKILL.md`) cherche dans les textes, cite paragraphes et pages, et, si le cas n'est pas univoque, présente un arbre de décision et les options **sans trancher**. |
| **Retrouver une règle** en ligne de commande | `python3 cn.py search "test marchand"`, `get SEC 20.29`, `get MGDD 1.2.4.3 57`, `section MGDD 3.2.2`, `toc MGDD 7.4`, `refs MGDD 3.2.2`, `cite SEC 20.309`, `cas` (voir `python3 cn.py -h`). |
| **Consulter** dans le navigateur | Onglet « Textes » du portail FiPu (local) et https://lucierc.github.io/bercy/textes/ : recherche, plan, lecture, renvois cliquables vers le SEC, liens vers la page du PDF officiel. Taper `20.29` ou `MGDD 1.2.3 ¶29` va directement au paragraphe. |

## Journal des cas — privé

Chaque cas analysé peut être enregistré dans `cas/AAAA-MM-JJ-sujet.md` (modèle : `modele_cas.md`) ;
il est alors retrouvé par `cn.py search -d CAS` et rappelé par Claude sur les cas suivants.

**`cas/` n'est jamais versionné** (`.gitignore`) : le dépôt est public. En contrepartie, il n'est
sauvegardé nulle part ailleurs que sur ce poste : le copier régulièrement (OneDrive, clé…).

## Fichiers

| Fichier | Rôle | Versionné |
|---|---|---|
| `config.json` | Documents du corpus : PDF, adresse officielle, empreinte, règles de numérotation | oui |
| `build.py` | PDF → `data/corpus.json` (sections d'après les signets, paragraphes numérotés, notes de bas de page rattachées), puis `page.py` | oui |
| `schemas.md` | Transcription manuelle des arbres de décision (dessins illisibles en texte) | oui |
| `data/corpus.json` | Texte extrait (≈ 4,7 Mo) : la référence pour `cn.py` et la page | oui |
| `cn.py` | Recherche en ligne de commande ; index SQLite FTS5 `data/corpus.sqlite` reconstruit seul | oui (index : non) |
| `page.html`, `page.py` | Page web autonome → `dist/textes-fipu.html` | oui (dist : non) |
| `.claude/skills/compta-nat/` | Instructions d'analyse de cas pour Claude | oui |
| `*.pdf` | Les PDF officiels (téléchargés par `build.py` s'ils manquent) | non |
| `cas/` | Journal des cas | **non** |

## Mettre à jour

- Rien à faire au quotidien : les textes ne changent pas. La publication (GitHub Actions) régénère la
  page depuis `data/corpus.json`.
- Nouvelle édition du MGDD, ou nouveau document : ajouter ou modifier l'entrée dans `config.json`
  (adresse, empreinte `sha1`, numérotation des paragraphes), puis `python3 build.py`. Vérifier le
  résumé affiché (paragraphes numérotés, signets non retrouvés) et la carte du corpus dans le skill.

## Limites

- Extraction automatique : les tableaux et schémas sortent dans le désordre (signalés `[Schéma : …]`,
  les arbres de décision clés sont transcrits). Le PDF fait foi.
- Pages citées = pages du PDF (affichées par le lecteur), pas la pagination imprimée.
- Le corpus ne contient ni les décisions et lettres d'Eurostat, ni les méthodologies de l'INSEE.
