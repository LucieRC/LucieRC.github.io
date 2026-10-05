"""Tests hors ligne des extracteurs : python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch  # noqa: E402
import jorf  # noqa: E402
import wiki  # noqa: E402


class Dates(unittest.TestCase):
    def test_full_dates(self):
        self.assertEqual(wiki.dates_in("du 15 mai 2012 au 18 juin 2012"), ["2012-05-15", "2012-06-18"])

    def test_range_without_first_year(self):
        self.assertEqual(wiki.dates_in("du 16 mai au 19 juin 2017"), ["2017-05-16", "2017-06-19"])
        self.assertEqual(wiki.dates_in("du 9 janvier au 5 septembre 2024"), ["2024-01-09", "2024-09-05"])
        self.assertEqual(wiki.dates_in("du 1 er juin au 3 juillet 2020"), ["2020-06-01", "2020-07-03"])

    def test_open_ended_and_numeric(self):
        self.assertEqual(wiki.dates_in("depuis le 10 octobre 2025"), ["2025-10-10"])
        self.assertEqual(wiki.dates_in("22/02/2026 en fonction"), ["2026-02-22"])

    def test_month_year(self):
        self.assertEqual(wiki.month_year("a succédé en janvier 2024 à"), "2024-01")
        self.assertIsNone(wiki.month_year("rien"))


class Wikitext(unittest.TestCase):
    def test_plain_and_links(self):
        s = "[[Roland Lescure]], ministre de l'[[Économie (France)|Économie]]<ref>x</ref> {{date|12|octobre|2025}}"
        self.assertEqual(wiki.plain(s), "Roland Lescure, ministre de l'Économie 12 octobre 2025")
        self.assertEqual(wiki.links(s)[1], ("Économie (France)", "Économie"))

    def test_infobox_field(self):
        wt = "{{Infobox\n | titulaire actuel = [[Sébastien Lecornu]]\n | autre = x\n}}"
        self.assertEqual(wiki.infobox_field(wt, "titulaire actuel"), "[[Sébastien Lecornu]]")

    def test_sections(self):
        wt = "== A ==\n=== x ===\nun\n=== y ===\ndeux\n== B ==\ntrois"
        self.assertEqual([(h, b.strip()) for h, b in wiki.sections(wt, 3)], [("x", "un"), ("y", "deux")])


class Grid(unittest.TestCase):
    def test_rowspan_colspan(self):
        html = """<table>
          <tr><th colspan="2">Ministre</th><th>Début</th></tr>
          <tr><td rowspan="2">img</td><td><a href="/wiki/A_B">A B</a></td><td>1 mai 2020</td></tr>
          <tr><td>C D</td><td>2 mai 2021</td></tr></table>"""
        g = wiki.grid(BeautifulSoup(html, "html.parser").table)
        self.assertEqual([[c["text"] for c in r] for r in g],
                         [["Ministre", "Ministre", "Début"], ["img", "A B", "1 mai 2020"], ["img", "C D", "2 mai 2021"]])
        self.assertEqual(g[1][1]["link"][1], "https://fr.wikipedia.org/wiki/A_B")


class Since(unittest.TestCase):
    def test_continuous_tenure(self):
        rows = [{"name": "X", "start": "2020-01-01"}, {"name": "Y", "start": "2021-01-01"},
                {"name": "Y", "start": "2022-01-01"}]
        self.assertEqual(fetch._since(rows, "Y"), "2021-01-01")
        self.assertEqual(fetch._since(rows, "X"), "2020-01-01")


SUMMARY = """<?xml version="1.0" encoding="UTF-8"?>
<JO><META><META_SPEC><META_CONTENEUR><TITRE>JORF n°0227 du 29 septembre 2026</TITRE>
<DATE_PUBLI>2026-09-29</DATE_PUBLI></META_CONTENEUR></META_SPEC></META>
<STRUCTURE_TXT><TM niv="1"><TITRE_TM>Journal officiel "Lois et Décrets"</TITRE_TM>
<TM niv="2"><TITRE_TM>Décrets, arrêtés, circulaires</TITRE_TM>
<TM niv="3"><TITRE_TM>Mesures nominatives</TITRE_TM>
<TM niv="4"><TITRE_TM>Ministère de l'action et des comptes publics</TITRE_TM>
<LIEN_TXT idtxt="JORFTEXT000000000001" titretxt="Arrêté du 9 septembre 2026 portant nomination au cabinet du ministre de l'action et des comptes publics"/>
</TM></TM>
<TM niv="3"><TITRE_TM>Textes généraux</TITRE_TM>
<TM niv="4"><TITRE_TM>Présidence de la République</TITRE_TM>
<LIEN_TXT idtxt="JORFTEXT000000000002" titretxt="Décret du 22 septembre 2026 relatif à la composition du Gouvernement"/>
</TM></TM></TM></TM></STRUCTURE_TXT></JO>""".encode()


class Jorf(unittest.TestCase):
    def setUp(self):
        self.entries = jorf.parse_summary(SUMMARY)

    def test_parse(self):
        e = self.entries[0]
        self.assertEqual(e["date"], "2026-09-29")
        self.assertEqual(e["path"], ["Décrets, arrêtés, circulaires", "Mesures nominatives",
                                     "Ministère de l'action et des comptes publics"])
        self.assertEqual(e["url"], "https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000000000001")

    def test_filters(self):
        cab = {"title": "cabinet", "ministry": "économie|comptes publics"}
        gouv = {"title": "composition du Gouvernement"}
        nom = {"section": "Mesures nominatives"}
        self.assertEqual([jorf.matches(e, cab) for e in self.entries], [True, False])
        self.assertEqual([jorf.matches(e, gouv) for e in self.entries], [False, True])
        self.assertEqual([jorf.matches(e, nom) for e in self.entries], [True, False])

    def test_empty_bundle(self):
        self.assertEqual(jorf.read_bundle(b"not a gzip"), [])


class Config(unittest.TestCase):
    """La configuration livrée doit rester cohérente avec le code."""

    def test_config(self):
        import json
        import re
        cfg = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text())
        kinds = {"infobox": {"page", "field"}, "government_role": {"pattern"},
                 "prose": {"page", "regex"}, "list_last_row": {"page", "name_header", "date_header"}}
        keys = [o["key"] for o in cfg["officials"]]
        self.assertEqual(len(keys), len(set(keys)), "clés de postes en double")
        for o in cfg["officials"]:
            self.assertIn(o["kind"], kinds)
            self.assertTrue(kinds[o["kind"]] <= set(o), o["key"])
        for f in cfg["jorf"]["filters"]:
            for k in ("title", "section", "ministry", "path"):
                if k in f:
                    re.compile(f[k])
        for s in cfg["eurostat"]:
            self.assertTrue({"key", "label", "dataset", "filters", "since"} <= set(s))


if __name__ == "__main__":
    unittest.main()
