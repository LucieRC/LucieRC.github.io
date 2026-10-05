"""PDF du corpus (config.json) → data/corpus.json : sections (signets) et paragraphes numérotés.

Déterministe : même PDF, même sortie. Les pages citées sont celles du PDF (pas la pagination imprimée).
"""
import hashlib
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF

import page

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "corpus.json"
MAX_WORDS = 700          # au-delà, un passage non numéroté est coupé en morceaux « (suite) »
LIST_ITEM = re.compile(r"^(\(?[a-z]{1,4}\)|\d{1,2}\)|[•▪●–—-])\s")
CAPTION = re.compile(r"^(Diagramme|Graphique|Schéma|Figure|Diagram|Chart|Decision tree)\b")
NOTE = re.compile(r"^\((\d{1,3})\)\s*(.*)")


def clean(s):
    s = unicodedata.normalize("NFC", s).replace("\r", " ").replace("\xa0", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", s).strip()


def norm(s):
    """Clé de comparaison titre de signet ↔ ligne de la page : minuscules, sans accents ni ponctuation."""
    s = unicodedata.normalize("NFKD", s.replace("\xad", "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def leading_number(title):
    m = re.match(r"^(\d+(?:\.\d+)*)\.?\s", title)
    return m.group(1) if m else None


def dedupe(path):
    """« 20. Les comptes des APU > Les comptes des APU » : le SEC répète le titre du chapitre en sous-niveau."""
    strip = lambda t: norm(re.sub(r"^\d+(\.\d+)*\.?\s", "", t))
    return [t for i, t in enumerate(path) if i == 0 or strip(t) != strip(path[i - 1])]


def join_lines(lines):
    out = ""
    for t in lines:
        if not out:
            out = t
        elif out.endswith("\xad"):
            out = out[:-1] + t
        elif LIST_ITEM.match(t):
            out += "\n" + t
        else:
            out += " " + t
    return re.sub(r"[ ]+", " ", out.replace("\xad", "")).strip()


def page_lines(page, margins):
    top, bottom = margins
    lines = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            spans = [s for s in l["spans"] if s["text"].strip()]
            if not spans:
                continue
            x0, y0 = l["bbox"][0], l["bbox"][1]
            if y0 < top or y0 > bottom:
                continue
            text = unicodedata.normalize("NFC", "".join(s["text"] for s in l["spans"]))
            text = re.sub(r"[ \t\xa0]+", " ", text).strip()
            lines.append({"x": x0, "text": text, "font": spans[0]["font"], "size": spans[0]["size"],
                          "max": max(s["size"] for s in spans)})
    return lines


def ensure_pdf(src):
    """Le PDF est téléchargé depuis son adresse officielle s'il manque ; son empreinte garantit les mêmes pages."""
    path = ROOT / src["file"]
    if not path.exists():
        print(f"téléchargement de {src['file']}…", file=sys.stderr)
        req = urllib.request.Request(src["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            path.write_bytes(r.read())
    sha1 = hashlib.sha1(path.read_bytes()).hexdigest()
    if sha1 != src["sha1"]:
        sys.exit(f"{src['file']} : empreinte {sha1} ≠ {src['sha1']} (autre version du document ? "
                 "vérifier, puis mettre à jour sha1 dans config.json)")
    return path


def attach_notes(lines, chunks, state, page):
    """Notes de bas de page « (NN) texte » → ajoutées au passage de la page qui contient l'appel (NN)."""
    notes = []
    for l in lines:
        m = NOTE.match(l["text"])
        if m:
            notes.append([m.group(1), [m.group(2)]])
        elif notes:
            notes[-1][1].append(l["text"])
    for num, body in notes:
        note = f"[Note {num}] {join_lines(body)}"
        call = f"({num})"
        if call in "".join(state["lines"]) or not chunks or chunks[-1]["page_end"] < page:
            state["notes"].append(note)
            continue
        for c in reversed(chunks):
            if c["page_end"] < page - 1 or call in c["text"]:
                break
        target = c if call in c["text"] else None
        if target:
            target["text"] += "\n" + note
        else:
            state["notes"].append(note)


def insert_schemas(src, chunks):
    """Transcriptions de schemas.md → insérées après le passage qui contient le schéma (même section)."""
    text = (ROOT / "schemas.md").read_text()
    for m in re.finditer(r"^## (\w+) \| (\d+) \| (.+?)\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        doc, page, caption, body = m.group(1), int(m.group(2)), m.group(3).strip(), m.group(4).strip()
        if doc != src["id"]:
            continue
        # de préférence le passage qui porte la légende du schéma, sinon le premier de la page
        on_page = [n for n, c in enumerate(chunks) if c["page"] <= page <= c["page_end"]]
        k = next((n for n in on_page if "[Schéma : " in chunks[n]["text"]), on_page[0] if on_page else None)
        if k is None:
            sys.exit(f"schemas.md : page {page} introuvable dans {doc}")
        host = chunks[k]
        chunks.insert(k + 1, {"id": None, "doc": doc, "sec": host["sec"], "para": None,
                              "ref": f"{src['cite']} {caption} (transcription)", "page": page, "page_end": page,
                              "text": f"[Transcription manuelle du schéma de la p. {page}, voir schemas.md]\n{body}"})
    for n, c in enumerate(chunks):
        c["id"] = f"{src['id']}-c{n}"


def extract(src):
    pdf = fitz.open(ensure_pdf(src))
    # Les signets peuvent contenir des doublons qui reviennent en arrière : on ne garde que l'ordre des pages.
    toc, last = [], 0
    for lvl, t, p in pdf.get_toc():
        if p > 0 and p >= last:
            toc.append({"level": lvl, "title": clean(t), "page": p})
            last = p
    doc = src["id"]
    para_re = re.compile(src["para_regex"])

    sections, chunks, misses = [], [], []
    stack = []  # sections ouvertes, par niveau
    for i, e in enumerate(toc):
        while stack and stack[-1]["level"] >= e["level"]:
            stack.pop()
        num = leading_number(e["title"])
        sec = {"id": f"{doc}-s{i}", "doc": doc, "level": e["level"], "num": num, "title": e["title"],
               "page": e["page"], "parent": stack[-1]["id"] if stack else None,
               "path": dedupe([s["title"] for s in stack] + [e["title"]])}
        # numéro de section « effectif » : celui de la section ou de l'ancêtre numéroté le plus proche
        sec["ref_num"] = num or next((s["ref_num"] for s in reversed(stack) if s["ref_num"]), None)
        sec["skip"] = e["title"] in src["skip_sections"] or any(s["skip"] for s in stack)
        sections.append(sec)
        stack.append(sec)

    state = {"sec": None, "para": None, "lines": [], "p0": None, "p1": None, "part": 0, "notes": []}

    def flush():
        sec = state["sec"]
        if state["lines"] and sec and not sec["skip"]:
            text = join_lines(state["lines"])
            words = text.split(" ")
            pieces = [" ".join(words[k:k + MAX_WORDS]) for k in range(0, len(words), MAX_WORDS)] \
                if state["para"] is None else [text]
            pieces[-1] += "".join("\n" + n for n in state["notes"])
            for piece in pieces:
                para = state["para"]
                if src["para_scope"] == "doc" and para:
                    ref = f"{src['cite']} §{para}"
                else:
                    where = sec["ref_num"] or sec["title"]
                    ref = f"{src['cite']} {where}" + (f" ¶{para}" if para else "")
                if state["part"]:
                    ref += " (suite)"
                chunks.append({"id": f"{doc}-c{len(chunks)}", "doc": doc, "sec": sec["id"], "para": para,
                               "ref": ref, "page": state["p0"], "page_end": state["p1"], "text": piece})
                state["part"] += 1
        state.update(lines=[], p0=None, p1=None, part=0, notes=[])

    def open_section(k):
        flush()
        state.update(sec=sections[k], para=None)

    j = 0  # prochain signet à placer
    for pno in range(len(pdf)):
        page = pno + 1
        while j < len(sections) and sections[j]["page"] < page:   # signet non retrouvé sur sa page
            misses.append(sections[j]["title"])
            open_section(j)
            j += 1
        lines = page_lines(pdf[pno], src["margins"])
        if "note_max_size" in src:
            notes = [l for l in lines if l["max"] <= src["note_max_size"]]
            lines = [l for l in lines if l["max"] > src["note_max_size"]]
        else:
            notes = []
        i = 0
        while i < len(lines):
            ln = lines[i]
            is_heading = any(f in ln["font"] for f in src["heading_fonts"]) or ln["size"] >= 11.5
            # 1. début d'une section (signet) ?
            matched = False
            if is_heading:
                for k in range(j, min(j + 4, len(sections))):
                    if sections[k]["page"] != page:
                        break
                    title, num = sections[k]["title"], sections[k]["num"]
                    keys = [norm(title)[:25], norm(re.sub(r"^\d+(\.\d+)*\.?\s", "", title))[:25]]  # 25 car. : tolère les coquilles des signets
                    acc = "".join(norm(l["text"]) for l in lines[i:i + 6])
                    # titre identique (avec ou sans numéro), ou même numéro (le titre imprimé diffère parfois du signet)
                    if any(key and acc.startswith(key) for key in keys) \
                            or num and re.match(re.escape(num) + r"\.?(\s|$)", ln["text"]):
                        for skipped in range(j, k):
                            misses.append(sections[skipped]["title"])
                        open_section(k)
                        j = k + 1
                        # le titre peut tenir sur plusieurs lignes de même style
                        i += 1
                        while i < len(lines) and (lines[i]["font"], lines[i]["size"]) == (ln["font"], ln["size"]) \
                                and norm(lines[i]["text"]) in norm(title):
                            i += 1
                        matched = True
                        break
            if matched:
                continue
            # 2. début d'un paragraphe numéroté ?
            m = para_re.match(ln["text"])
            if m and (("para_font" in src and src["para_font"] in ln["font"])
                      or ("para_max_x" in src and ln["x"] <= src["para_max_x"] and not is_heading)):
                flush()
                state["para"] = m.group(1)
                ln = dict(ln, text=ln["text"][m.end():])
            if CAPTION.match(ln["text"]) and is_heading:
                ln = dict(ln, text=f"[Schéma : {ln['text']} — le texte du schéma suit, dans le désordre ; "
                                   f"voir le PDF p. {page}]")
            if ln["text"]:
                state["lines"].append(ln["text"])
                state["p0"] = state["p0"] or page
                state["p1"] = page
            i += 1
        attach_notes(notes, chunks, state, page)
    flush()
    insert_schemas(src, chunks)

    for s in sections:
        del s["skip"]
    return sections, chunks, misses


def main():
    cfg = json.loads((ROOT / "config.json").read_text())
    out = {"built": date.today().isoformat(), "sources": [], "sections": [], "chunks": []}
    for src in cfg["sources"]:
        sections, chunks, misses = extract(src)
        out["sources"].append({k: src[k] for k in ("id", "title", "cite", "lang", "url", "info")} |
                              {"file": src["file"], "pages": fitz.open(ROOT / src["file"]).page_count})
        out["sections"] += sections
        out["chunks"] += chunks
        numbered = sum(1 for c in chunks if c["para"])
        print(f"{src['id']}: {len(sections)} sections, {len(chunks)} passages dont {numbered} paragraphes numérotés, "
              f"{len(misses)} signets non retrouvés dans le texte", file=sys.stderr)
        for t in misses[:15]:
            print(f"   ? {t}", file=sys.stderr)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=0))
    print(f"→ {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} Ko)", file=sys.stderr)
    page.main()


if __name__ == "__main__":
    main()
