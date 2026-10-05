"""Lecture des sources : flux RSS / Atom, ou page HTML listant des publications.

Chaque lecteur renvoie une liste d'éléments {url, title, summary, published} ;
`published` est une date ISO (AAAA-MM-JJ ou horodatage) ou None si la source n'en donne pas.
"""
import html as htmllib
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

TIMEOUT = 40
SUMMARY_CHARS = 400


# =================================================================== texte

def clean(text):
    """Texte brut sur une ligne : balises retirées, entités décodées, espaces réduits."""
    if not text:
        return ""
    if "<" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    text = htmllib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def shorten(text, n=SUMMARY_CHARS):
    text = clean(text)
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.-–") + "…"


def normalize(text):
    """Minuscules sans accents, apostrophes unifiées : base commune du filtrage par mots-clés."""
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.lower().replace("’", "'").replace(" ", " ")


# =================================================================== dates

MONTHS = {
    "janvier": 1, "janv": 1, "jan": 1, "fevrier": 2, "fevr": 2, "fev": 2, "mars": 3, "avril": 4, "avr": 4,
    "mai": 5, "juin": 6, "juillet": 7, "juil": 7, "aout": 8, "septembre": 9, "sept": 9, "sep": 9,
    "octobre": 10, "oct": 10, "novembre": 11, "nov": 11, "decembre": 12, "dec": 12,
    "january": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
    "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}
_M = "|".join(sorted(MONTHS, key=len, reverse=True))
TEXT_DATE = re.compile(r"\b(\d{1,2})(?:er)?\s+(" + _M + r")\.?\s+(\d{4})\b")
NUM_DATE = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")
ISO_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
URL_DATE = re.compile(r"/(20\d{2})/(\d{2})/(\d{2})/|/(20\d{2})(\d{2})(\d{2})[_/-]")


def _iso(y, m, d):
    try:
        return datetime(int(y), int(m), int(d)).date().isoformat()
    except ValueError:
        return None


def find_date(text):
    """Première date lisible dans un texte (« 24 septembre 2026 », « 21 sept. 2026 », 24/09/2026, 2026-09-24)."""
    t = normalize(text)
    for rx, order in ((TEXT_DATE, "dmy_text"), (NUM_DATE, "dmy"), (ISO_DATE, "ymd")):
        m = rx.search(t)
        if not m:
            continue
        if order == "dmy_text":
            d = _iso(m.group(3), MONTHS[m.group(2)], m.group(1))
        elif order == "dmy":
            d = _iso(m.group(3), m.group(2), m.group(1))
        else:
            d = _iso(m.group(1), m.group(2), m.group(3))
        if d:
            return d
    return None


def date_from_url(url):
    m = URL_DATE.search(url or "")
    if not m:
        return None
    g = [x for x in m.groups() if x]
    return _iso(*g[:3])


def parse_feed_date(s):
    """Date d'un flux (RFC 822 pour RSS, ISO 8601 pour Atom) → ISO UTC."""
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return find_date(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")


# =================================================================== lecteurs

def get(url, ua):
    r = requests.get(url, timeout=TIMEOUT, headers={
        "User-Agent": ua,
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, text/html;q=0.8, */*;q=0.5",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.6",
    })
    r.raise_for_status()
    return r


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child(el, *names):
    for c in el:
        if _local(c.tag) in names:
            return c
    return None


def _text(el, *names):
    c = _child(el, *names)
    return (c.text or "").strip() if c is not None and c.text else ""


def read_feed(src, ua):
    """RSS 2.0, RSS 1.0 (RDF) ou Atom, sans dépendance externe."""
    r = get(src["url"], ua)
    body = r.content.lstrip()
    if not body.startswith(b"<"):
        raise ValueError("réponse qui n'est pas du XML")
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        # quelques flux contiennent des entités HTML (&nbsp;…) invalides en XML
        fixed = re.sub(rb"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", b"&amp;", body)
        root = ET.fromstring(fixed)
    if _local(root.tag) in ("html", "HTML"):
        raise ValueError("la source renvoie une page HTML, pas un flux")
    out = []
    for el in root.iter():
        kind = _local(el.tag)
        if kind == "item":  # RSS 2.0 et RDF
            link = _text(el, "link") or (_text(el, "guid") if (_child(el, "guid") is not None and
                                                                (_child(el, "guid").get("isPermaLink") != "false")) else "")
            title = _text(el, "title")
            summary = _text(el, "description", "encoded", "summary")
            published = _text(el, "pubDate", "date", "published", "updated")
            via = _text(el, "source")  # Google Actualités : nom du média
        elif kind == "entry":  # Atom
            link = ""
            for c in el:
                if _local(c.tag) == "link" and c.get("href") and c.get("rel", "alternate") == "alternate":
                    link = c.get("href")
                    break
            title = clean("".join(_child(el, "title").itertext())) if _child(el, "title") is not None else ""
            sc = _child(el, "summary", "content")
            summary = "".join(sc.itertext()) if sc is not None else ""
            published = _text(el, "published", "updated")
            via = ""
        else:
            continue
        if not link or not title:
            continue
        out.append({
            "url": urljoin(src["url"], link.strip()),
            "title": clean(title),
            "summary": shorten(summary),
            "published": parse_feed_date(published) or date_from_url(link),
            "via": clean(via) or None,
        })
    if not out and not re.search(rb"<(rss|feed|rdf:RDF)[\s>]", body[:2000]):
        raise ValueError("aucun flux RSS/Atom reconnu")
    return out


def read_html(src, ua):
    """Page listant des publications. Réglages (config.json, clé "html") :

    link     : expression régulière que l'adresse (absolue) du lien doit vérifier ;
    item     : sélecteur CSS d'un bloc par publication (facultatif ; à défaut, chaque lien) ;
    title / summary / date : sélecteurs CSS dans le bloc (facultatifs).
    La date est cherchée dans `date`, puis dans l'adresse, puis dans le texte du bloc.
    """
    h = src["html"]
    r = get(src["url"], ua)
    soup = BeautifulSoup(r.content, "html.parser")  # à partir des octets : BeautifulSoup lit le charset de la page
    link_re = re.compile(h["link"])
    out, seen = [], set()

    def text_of(el, sel):
        if not sel or el is None:
            return ""
        x = el.select_one(sel)
        return x.get_text(" ", strip=True) if x else ""

    blocks = soup.select(h["item"]) if h.get("item") else None
    if blocks is None:
        pairs = [(a, a) for a in soup.find_all("a", href=True)]
    else:
        pairs = []
        for b in blocks:
            anchors = ([b] if b.name == "a" and b.get("href") else []) + b.find_all("a", href=True)
            a = next((a for a in anchors if link_re.search(urljoin(src["url"], a["href"].strip()))), None)
            if a is not None:
                pairs.append((b, a))
    for block, a in pairs:
        url = urljoin(src["url"], a["href"].strip())
        if not link_re.search(url) or url in seen:
            continue
        title = text_of(block, h.get("title")) or a.get_text(" ", strip=True)
        if not title:
            continue
        seen.add(url)
        summary = text_of(block, h.get("summary"))
        date_txt = text_of(block, h.get("date"))
        published = (find_date(date_txt) if date_txt else None) or date_from_url(url) or \
            (find_date(block.get_text(" ", strip=True)) if block is not a else None)
        out.append({"url": url, "title": clean(title), "summary": shorten(summary),
                    "published": published, "via": None})
    if not out:
        raise ValueError("aucun lien reconnu : la structure de la page a peut-être changé (voir config.json)")
    return out


GNEWS = "https://news.google.com/rss/search?q={q}&hl=fr&gl=FR&ceid=FR:fr"


def read_gnews(src, ua):
    """Recherche Google Actualités (flux RSS public) : utile pour les sites qui bloquent les robots
    ou n'ont pas de flux. `query` accepte la syntaxe de Google (guillemets, OR, site:…)."""
    days = src.get("days", 7)  # fenêtre de recherche ; 0 = pas de limite
    q = src["query"] + (f" when:{days}d" if days else "")
    items = read_feed({**src, "url": GNEWS.format(q=quote(q))}, ua)
    for it in items:
        # le titre se termine par « - Nom du média », déjà donné par <source>
        if it["via"] and it["title"].endswith(" - " + it["via"]):
            it["title"] = it["title"][: -len(it["via"]) - 3].rstrip()
        # la description ne fait que répéter titre et média
        it["summary"] = ""
    return items


READERS = {"rss": read_feed, "html": read_html, "gnews": read_gnews}


def read(src, ua):
    items = READERS[src["type"]](src, ua)
    limit = src.get("max_items")
    return items[:limit] if limit else items
