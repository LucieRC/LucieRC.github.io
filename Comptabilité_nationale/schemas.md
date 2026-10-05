# Schémas transcrits

Les arbres de décision des PDF sont des dessins : leur texte sort dans le désordre. Les plus utiles
pour l'analyse de cas sont transcrits ici à la main, d'après le PDF, et insérés par build.py dans le
corpus juste après le passage où figure le schéma. En cas de doute, le PDF fait foi.

Format : un titre `## DOC | page du PDF | légende`, puis le texte.

## SEC | 67 | Diagramme 2.1 – L’affectation des unités aux secteurs

1. L’unité est-elle résidente ? Non → Reste du monde. Oui → 2.
2. L’unité est-elle un ménage ? Oui → Ménages. Non → 3.
3. L’unité est-elle un producteur non marchand ?
   - Oui → L’unité est-elle contrôlée par une administration publique ? Non → ISBLSM. Oui → Administrations publiques.
   - Non → L’unité produit-elle des services financiers ?
     - Non → Sociétés non financières. L’unité est-elle contrôlée par les administrations publiques ? Oui → Sociétés non financières publiques. Non → Sociétés non financières privées.
     - Oui → Sociétés financières. L’unité est-elle contrôlée par les administrations publiques ? Oui → Sociétés financières publiques. Non → Sociétés financières privées.

## SEC | 500 | Diagramme 20.1 – Arbre de décision

1. L’entité est-elle une unité institutionnelle ? Non → Fait partie de l’unité exerçant le contrôle. Oui → 2.
2. L’unité est-elle contrôlée par les administrations publiques ? Non → Unité classée dans les secteurs privés. Oui → 3.
3. L’unité est-elle un non-producteur non marchand ? Non → Unité classée comme une société publique. Oui → L’unité fait partie du secteur des administrations publiques.

## MGDD | 26 | Decision tree (qualitative criteria and market/non-market test for public units)

1. Is the public unit a dedicated provider of ancillary services? Yes → Unit is part of general government. No → 2.
2. Is the output of the public unit sold only to government?
   - Yes → 3a. Is the public unit the only supplier of government?
     - Yes → 4. Does it compete with private producers through tendering for contracts? Yes → 6. No → Unit is part of general government.
     - No → 6.
   - No → 3b. Is the public unit the only supplier of government?
     - Yes → 5. Are the sales to non-government more than 50 % of total output? Yes → 6. No → 4.
     - No → 6.
6. Are prices economically significant (market/non-market test)? Yes → Unit is classified as public corporation. No → Unit is part of general government.

## MGDD | 179 | Decision tree for capital injections (other than investment grants D.92)

1. Are there private shareholders investing?
   - No → Does the company have accumulated net losses or made exceptional losses? (see 3.2.2.2.1)
     - Yes → General rule: non-financial transaction (if the amount injected exceeds the accumulated losses, see 3.2.2.2.1).
     - No → Is the market return likely? Yes → Financial transaction (see 3.2.2.2.2). No → Non-financial transaction (see 3.2.2.2.2).
   - Yes → Are there quoted shares?
     - Yes → General rule: financial transaction (see 3.2.2.3.2).
     - No → Are all three conditions under 3.2.2.3.1 met? Yes → Financial transaction (see 3.2.2.3.1). No → Think further (see 3.2.2.2.2) → non-financial transaction or financial transaction.
