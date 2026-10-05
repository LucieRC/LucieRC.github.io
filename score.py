"""Pertinence d'un élément selon les mots-clés de config.json.

Chaque ligne de "keywords" compte au plus une fois : son poids si l'un de ses termes figure
dans le résumé, multiplié par "title_weight" s'il figure dans le titre. S'y ajoute le "boost"
de la source. Les termes s'écrivent sans accents ni majuscules ; « * » en fin de terme
accepte toute terminaison (impot* → impôt, impôts, imposition non).
"""
import re

from sources import normalize


def compile_keywords(cfg):
    lines = []
    for k in cfg["keywords"]:
        rx = []
        for term in k["terms"]:
            t = normalize(term)
            body = re.escape(t.rstrip("*")) + (r"[a-z0-9]*" if t.endswith("*") else "")
            rx.append((t, re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])")))
        lines.append({"group": k["group"], "weight": k["weight"], "terms": rx})
    return lines


def score(title, summary, boost, lines, title_weight):
    """→ (score, termes trouvés, groupes trouvés)"""
    t, s = normalize(title), normalize(summary)
    total, terms, groups = boost, [], []
    for line in lines:
        best = 0
        for term, rx in line["terms"]:
            if rx.search(t):
                best = max(best, title_weight)
                terms.append(term)
            elif rx.search(s):
                best = max(best, 1)
                terms.append(term)
        if best:
            total += line["weight"] * best
            if line["weight"] > 0 and line["group"] not in groups:
                groups.append(line["group"])
    return total, terms, groups
