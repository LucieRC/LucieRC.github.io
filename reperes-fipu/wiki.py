"""Helpers to read French Wikipedia through the MediaWiki API."""
import re
from datetime import date

import requests
from bs4 import BeautifulSoup

API = "https://fr.wikipedia.org/w/api.php"
WIKI = "https://fr.wikipedia.org/wiki/"
UA = "ReperesFiPu/0.1 (outil interne de veille; contact: luc.elie@hotmail.fr)"

session = requests.Session()
session.headers["User-Agent"] = UA


def page_url(title):
    return WIKI + title.replace(" ", "_")


def _api(**params):
    params.update(format="json", formatversion=2)
    r = session.get(API, params=params, timeout=40)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"{data['error'].get('code')}: {data['error'].get('info')}")
    return data


def last_edits(titles):
    """{requested title: {'title', 'updated'}} — last revision timestamp; missing pages omitted."""
    out = {}
    titles = list(dict.fromkeys(titles))
    for i in range(0, len(titles), 40):
        chunk = titles[i:i + 40]
        q = _api(action="query", titles="|".join(chunk), prop="revisions",
                 rvprop="timestamp", redirects=1)["query"]
        alias = {t: t for t in chunk}
        for n in q.get("normalized", []):
            alias[n["from"]] = n["to"]
        redir = {r["from"]: r["to"] for r in q.get("redirects", [])}
        pages = {p["title"]: p for p in q["pages"] if not p.get("missing")}
        for t in chunk:
            final = alias[t]
            final = redir.get(final, final)
            if final in pages:
                out[t] = {"title": final, "updated": pages[final]["revisions"][0]["timestamp"]}
    return out


def wikitext(title, section=None):
    params = dict(action="parse", page=title, prop="wikitext", redirects=1)
    if section is not None:
        params["section"] = section
    p = _api(**params)["parse"]
    return p["title"], p["wikitext"]


def html(title):
    p = _api(action="parse", page=title, prop="text", redirects=1)["parse"]
    return p["title"], BeautifulSoup(p["text"], "html.parser")


def extract(title, sentences=None):
    params = dict(action="query", prop="extracts", explaintext=1, exintro=1,
                  titles=title, redirects=1)
    if sentences:
        params["exsentences"] = sentences
    pages = _api(**params)["query"]["pages"]
    p = pages[0]
    if p.get("missing"):
        return None, None
    return p["title"], p.get("extract", "").strip()


# ---------------------------------------------------------------- wikitext

LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")


def links(text):
    """[(target, label)] for every [[wikilink]] in text."""
    return [(t.strip(), (l or t).strip()) for t, l in LINK.findall(text or "")]


def plain(text):
    """Very small wikitext → plain text converter (enough for one-liners)."""
    s = text or ""
    s = re.sub(r"<ref[^>]*/>", "", s)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"\{\{[Dd]ate\|([^}]*)\}\}",
               lambda m: " ".join(x for x in m.group(1).split("|")
                                  if x and "=" not in x and x.strip() != "en France"), s)
    s = re.sub(r"\{\{(?:Citation|citation|Incise|nombre|Nombre)\|([^}|]*)(?:\|[^}]*)?\}\}", r"« \1 »", s)
    s = re.sub(r"\{\{[Nn]ombre\|([^}|]*)\|([^}|]*)\}\}", r"\1 \2", s)
    s = re.sub(r"\{\{(?:er|1er)\}\}", "er", s)
    s = re.sub(r"\{\{,\}\}", "", s)
    for _ in range(3):
        s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = LINK.sub(lambda m: (m.group(2) or m.group(1)), s)
    s = re.sub(r"'''?", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("« « ", "« ").replace(" » »", " »")
    return re.sub(r"[ \t]+", " ", s).strip()


def infobox_field(wt, field):
    m = re.search(r"^\s*\|\s*" + re.escape(field) + r"\s*=\s*(.*)$", wt, flags=re.M)
    return m.group(1).strip() if m else None


def sections(wt, level=3):
    """[(heading, body)] for headings of exactly `level` '=' signs."""
    eq = "=" * level
    pat = re.compile(r"^" + eq + r"\s*([^=].*?)\s*" + eq + r"\s*$", re.M)
    ms = list(pat.finditer(wt))
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(wt)
        body = wt[m.end():end]
        # stop at the next higher-level heading
        hm = re.search(r"^={1," + str(level - 1) + r"}[^=].*?={1," + str(level - 1) + r"}\s*$", body, re.M)
        if hm:
            body = body[:hm.start()]
        out.append((m.group(1), body))
    return out


# ---------------------------------------------------------------- tables

def grid(table):
    """Expand a HTML table (rowspan/colspan) into a rectangular list of cells.

    Each cell is {'text', 'link', 'th'}; link = (title, url) of the first article link.
    """
    rows, pending = [], {}
    for tr in table.find_all("tr"):
        row, col = [], 0
        cells = tr.find_all(["td", "th"], recursive=False)
        ci = 0
        while ci < len(cells) or col in pending:
            if col in pending:
                cell, left = pending[col]
                row.append(cell)
                if left > 1:
                    pending[col] = (cell, left - 1)
                else:
                    del pending[col]
                col += 1
                continue
            c = cells[ci]
            ci += 1
            for sup in c.find_all("sup", class_="reference"):
                sup.decompose()
            a = next((a for a in c.find_all("a", href=True)
                      if a["href"].startswith("/wiki/") and ":" not in a["href"][6:]), None)
            cell = {
                "text": re.sub(r"\s+", " ", c.get_text(" ", strip=True)).strip(),
                "link": (a.get("title") or a.get_text(strip=True),
                         "https://fr.wikipedia.org" + a["href"]) if a else None,
                "th": c.name == "th",
            }
            span = int(re.sub(r"\D", "", c.get("colspan", "1")) or 1)
            rspan = int(re.sub(r"\D", "", c.get("rowspan", "1")) or 1)
            for _ in range(span):
                row.append(cell)
                if rspan > 1:
                    pending[col] = (cell, rspan - 1)
                col += 1
        rows.append(row)
    return rows


# ---------------------------------------------------------------- dates

MONTHS = {m: i for i, m in enumerate(
    "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split(), 1)}
DATE_RE = re.compile(r"(\d{1,2})\s*(?:er)?\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", re.I)
NUM_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


_M = "(" + "|".join(MONTHS) + ")"
RANGE_RE = re.compile(r"\b(du\s+\d{1,2}(?:\s*er)?)(?:\s+" + _M + r")?\s+au\s+(\d{1,2}(?:\s*er)?\s+" + _M + r"\s+(\d{4}))", re.I)
MONTH_YEAR_RE = re.compile(_M + r"\s+(\d{4})", re.I)


def _complete_ranges(text):
    """« du 16 mai au 19 juin 2017 » → « du 16 mai 2017 au 19 juin 2017 »."""
    return RANGE_RE.sub(lambda m: f"{m.group(1)} {m.group(2) or m.group(4)} {m.group(5)} au {m.group(3)}", text)


def month_year(text):
    """First « janvier 2024 » in text → '2024-01' (month precision), or None."""
    m = MONTH_YEAR_RE.search(text or "")
    return f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}" if m else None


def dates_in(text):
    """All dates found in a French string, as ISO strings, in order of appearance."""
    text = _complete_ranges(text or "")
    found = []
    for m in DATE_RE.finditer(text or ""):
        found.append((m.start(), date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()))
    for m in NUM_DATE_RE.finditer(text or ""):
        found.append((m.start(), date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()))
    return [d for _, d in sorted(found)]


# ---------------------------------------------------------------- page content

def section_blocks(title, heading):
    """Text of the section named `heading` (with its sub-sections) as [{'type': 'h'|'p'|'li', 'text'}]."""
    p = _api(action="parse", page=title, prop="sections", redirects=1)["parse"]
    want = heading.strip().lower()
    sec = next((s for s in p["sections"] if BeautifulSoup(s["line"], "html.parser").get_text().strip().lower() == want), None)
    if not sec:
        raise RuntimeError(f"section « {heading} » absente de {p['title']}")
    h = _api(action="parse", page=title, prop="text", section=sec["index"], redirects=1,
             disableeditsection=1)["parse"]["text"]
    soup = BeautifulSoup(h, "html.parser")
    for bad in soup.select("sup.reference, .mw-editsection, figure, .thumb, style, .bandeau-container, "
                           ".navbox, .reference-cadre, ol.references, .references, .mw-references-wrap, .noprint"):
        bad.decompose()

    def clean(el):
        text = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
        return re.sub(r"\s+([,.;:)])", r"\1", text).replace("( ", "(")

    blocks = []
    for el in soup.find_all(["h2", "h3", "h4", "p", "li", "table"]):
        if el.find_parent("table") or (el.name == "li" and el.find_parent("li")):
            continue
        if el.name == "table":
            rows = [[clean(c) for c in tr.find_all(["th", "td"])] for tr in el.find_all("tr")]
            rows = [r for r in rows if any(r)]
            if rows:
                blocks.append({"type": "table", "rows": rows})
            continue
        text = clean(el)
        if text:
            blocks.append({"type": "h" if el.name.startswith("h") else el.name, "text": text})
    if blocks and blocks[0]["type"] == "h":
        blocks = blocks[1:]  # the section's own heading
    return p["title"], blocks


def pages_info(titles, sentences=2, thumb=96):
    """{requested title: {'title', 'extract', 'thumb_url', 'updated'}} for a batch of pages."""
    out = {}
    titles = [t for t in dict.fromkeys(titles) if t]
    for i in range(0, len(titles), 20):
        chunk = titles[i:i + 20]
        params = dict(action="query", titles="|".join(chunk), redirects=1,
                      prop="extracts|pageimages|revisions", rvprop="timestamp",
                      exintro=1, explaintext=1, piprop="thumbnail", pithumbsize=thumb)
        if sentences:
            params["exsentences"] = sentences
        q = _api(**params)["query"]
        alias = {t: t for t in chunk}
        for n in q.get("normalized", []):
            alias[n["from"]] = n["to"]
        redir = {r["from"]: r["to"] for r in q.get("redirects", [])}
        pages = {p["title"]: p for p in q["pages"] if not p.get("missing")}
        for t in chunk:
            final = redir.get(alias[t], alias[t])
            p = pages.get(final)
            if p:
                out[t] = {"title": final, "extract": (p.get("extract") or "").strip(),
                          "thumb_url": (p.get("thumbnail") or {}).get("source"),
                          "updated": (p.get("revisions") or [{}])[0].get("timestamp")}
    return out


def data_uri(url):
    """Download a (small) image and return it as a data: URI, so the page works offline."""
    import base64
    r = session.get(url, timeout=30)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "image/jpeg").split(";")[0]
    return f"data:{ctype};base64,{base64.b64encode(r.content).decode()}"


def title_from_url(url):
    from urllib.parse import unquote
    return unquote(url.split("/wiki/", 1)[1]).replace("_", " ") if url and "/wiki/" in url else None
