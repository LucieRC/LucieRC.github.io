"""data/corpus.json + page.html → dist/textes-fipu.html (un seul fichier, sans dépendance, sans les PDF).

Lancé par le portail et par la publication du site ; build.py n'est nécessaire que si les PDF changent.
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "dist" / "textes-fipu.html"


def main():
    corpus = json.loads((ROOT / "data" / "corpus.json").read_text())
    idx = {s["id"]: i for i, s in enumerate(corpus["sections"])}
    data = {
        "built": corpus["built"],
        "sources": corpus["sources"],
        # formes compactes : [doc, niveau, titre, page, parent] et [section, ¶, référence, page, page fin, texte]
        "sections": [[s["doc"], s["level"], s["title"], s["page"], idx.get(s["parent"])] for s in corpus["sections"]],
        "chunks": [[idx[c["sec"]], c["para"], c["ref"], c["page"], c["page_end"], c["text"]] for c in corpus["chunks"]],
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = (ROOT / "page.html").read_text()
    if "/*__DATA__*/null" not in html:
        raise SystemExit("marqueur /*__DATA__*/null absent de page.html")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html.replace("/*__DATA__*/null", payload))
    print(f"→ {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    main()
