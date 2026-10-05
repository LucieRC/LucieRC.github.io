"""Journal officiel (JORF) : sommaires quotidiens publiés en open data par la DILA.

Chaque archive JORF_AAAAMMJJ-HHMMSS.tar.gz contient le sommaire (JORFCONT*.xml) des
numéros publiés : rubriques (« Mesures nominatives », « Textes généraux »…), ministère
émetteur, intitulé exact de chaque texte et son identifiant Légifrance.

Collecte incrémentale : les archives déjà lues sont mémorisées dans data/jorf.json.
"""
import io
import json
import re
import tarfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

UA = "ReperesFiPu/0.1 (outil interne de veille; contact: luc.elie@hotmail.fr)"
BUNDLE_RE = re.compile(r'href="(JORF_(\d{8})-(\d{6})\.tar\.gz)"')
LEGIFRANCE = "https://www.legifrance.gouv.fr/jorf/id/"


def list_bundles(index_url):
    """[(filename, date)] of the daily archives listed on the DILA index."""
    r = requests.get(index_url, timeout=60, headers={"User-Agent": UA})
    r.raise_for_status()
    out = {}
    for name, d, _ in BUNDLE_RE.findall(r.text):
        out[name] = date(int(d[:4]), int(d[4:6]), int(d[6:]))
    return sorted(out.items(), key=lambda x: x[0])


def parse_summary(xml_bytes):
    """Entries of one JORFCONT (sommaire) file."""
    root = ET.fromstring(xml_bytes)
    jo = root.findtext(".//META_CONTENEUR/TITRE") or ""
    published = root.findtext(".//META_CONTENEUR/DATE_PUBLI")
    entries = []

    def walk(el, path):
        for c in el:
            if c.tag == "TM":
                walk(c, path + [(c.findtext("TITRE_TM") or "").strip()])
            elif c.tag == "LIEN_TXT":
                tid = c.get("idtxt")
                if not tid:
                    continue
                entries.append({
                    "id": tid,
                    "title": (c.get("titretxt") or "").strip(),
                    "date": published,
                    "jo": jo,
                    # path[0] = « Journal officiel "Lois et Décrets" » : sans intérêt
                    "path": [p for p in path[1:] if p],
                    "url": LEGIFRANCE + tid,
                })

    struct = root.find("STRUCTURE_TXT")
    if struct is not None:
        walk(struct, [])
    return entries


def read_bundle(content):
    """All summary entries in one .tar.gz archive (empty archives are fine)."""
    try:
        tf = tarfile.open(fileobj=io.BytesIO(content), mode="r:gz")
    except (tarfile.TarError, OSError, EOFError):
        return []  # certaines archives publiées sont vides
    entries = []
    for m in tf.getmembers():
        if m.isfile() and "/JORFCONT" in m.name and m.name.endswith(".xml"):
            entries += parse_summary(tf.extractfile(m).read())
    return entries


def _download(url):
    r = requests.get(url, timeout=120, headers={"User-Agent": UA})
    r.raise_for_status()
    return r.content


def update(store_path, cfg, progress=print):
    """Read new archives, merge into the store, prune old entries. Returns the store."""
    store_path = Path(store_path)
    try:
        store = json.loads(store_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        store = {"seen": [], "entries": {}}
    seen = set(store["seen"])
    today = date.today()
    horizon = today - timedelta(days=cfg["days_initial"])
    bundles = list_bundles(cfg["index"])
    if not bundles:
        raise RuntimeError("aucune archive JORF listée sur l'index DILA")
    todo = [(n, d) for n, d in bundles if d >= horizon and n not in seen]
    progress(f"Journal officiel : {len(todo)} archive(s) à lire")
    with ThreadPoolExecutor(max_workers=6) as ex:
        contents = ex.map(lambda nd: (nd[0], _download(cfg["index"] + nd[0])), todo)
        for i, (name, content) in enumerate(contents, 1):
            for e in read_bundle(content):
                store["entries"][e["id"]] = e
            seen.add(name)
            if i % 20 == 0:
                progress(f"Journal officiel : {i}/{len(todo)} archives lues")
    # Les archives renvoient aussi d'anciens numéros : la couverture n'est complète qu'à partir
    # du premier jour dont l'archive a été lue. On ne garde que cette période.
    read_days = [d for n, d in bundles if n in seen]
    if read_days:
        first = min(read_days).isoformat()
        store["coverage_from"] = min(store.get("coverage_from") or first, first)
    keep_from = max(store.get("coverage_from") or "", (today - timedelta(days=cfg["retention_days"])).isoformat())
    store["coverage_from"] = keep_from
    store["entries"] = {k: v for k, v in store["entries"].items() if (v.get("date") or "") >= keep_from}
    listed = {n for n, _ in bundles}
    store["seen"] = sorted(n for n in seen if n in listed)
    store["latest_bundle"] = bundles[-1][0]
    store["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    store_path.write_text(json.dumps(store, ensure_ascii=False))
    return store


def matches(entry, flt):
    """Same semantics as the page's JS filter: every given field must match (regex, case-insensitive)."""
    path = entry.get("path") or []
    fields = {
        "title": entry.get("title", ""),
        "section": path[1] if len(path) > 1 else "",
        "ministry": path[2] if len(path) > 2 else (path[-1] if path else ""),
        "path": " > ".join(path),
    }
    return all(re.search(flt[k], fields[k], re.I) for k in fields if k in flt)


def for_page(store, cfg):
    """Entries worth embedding: those matching a filter, plus every text of the last few days."""
    recent = (date.today() - timedelta(days=cfg["all_texts_days"])).isoformat()
    out = []
    for e in store["entries"].values():
        tags = [f["id"] for f in cfg["filters"] if matches(e, f)]
        if tags or (e.get("date") or "") >= recent:
            out.append({**e, "tags": tags})
    out.sort(key=lambda e: (e.get("date") or "", e["id"]), reverse=True)
    return out
