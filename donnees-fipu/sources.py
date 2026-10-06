"""Lecture des sources publiques. Chaque fonction renvoie une liste de séries :

    {"key", "label", "unit", "freq", "ref", "updated", "obs": {période: valeur}}

Les périodes suivent la notation des sources : « 2024 », « 2024-Q3 », « 2024-07 ».
"""
import csv
import html
import io
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime

import requests

UA = "DonneesFiPu/0.1 (collecte de statistiques publiques)"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
INSEE = "https://bdm.insee.fr/series/sdmx/data/"
MELODI = "https://api.insee.fr/melodi/"
SKIP_DIMS = ("time", "freq")
FREQ_INSEE = {"A": "A", "T": "Q", "M": "M", "S": "S", "B": "M2"}


def _get(url, params=None, timeout=180, tries=3):
    """GET avec nouvelles tentatives : l'Insee coupe parfois les connexions venant des serveurs de GitHub."""
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": UA})
            r.raise_for_status()
            return r
        except requests.RequestException:
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


def eurostat(src, cfg):
    """Toutes les séries d'une requête Eurostat (JSON-stat), une par combinaison de dimensions."""
    params = [("lang", "fr"), ("sinceTimePeriod", src["since"])]
    for k, vs in src["filters"].items():
        if vs == "$comparateurs":
            vs = cfg["comparateurs"]
        params += [(k, v) for v in (vs if isinstance(vs, list) else [vs])]
    d = _get(EUROSTAT + src["dataset"], params).json()
    if "error" in d:
        raise RuntimeError(str(d["error"]))
    ids, size = d["id"], d["size"]
    strides = [1] * len(size)
    for i in range(len(size) - 2, -1, -1):
        strides[i] = strides[i + 1] * size[i + 1]
    codes = {k: {pos: code for code, pos in d["dimension"][k]["category"]["index"].items()} for k in ids}
    labels = {k: d["dimension"][k]["category"].get("label", {}) for k in ids}
    freq = next(iter(labels.get("freq", {"A": ""})))
    series = {}
    for flat, val in d["value"].items():
        flat = int(flat)
        coord = {k: codes[k][(flat // s) % n] for k, s, n in zip(ids, strides, size)}
        dims = [k for k in ids if k not in SKIP_DIMS]
        key = ".".join([src["dataset"]] + [coord[k] for k in dims])
        if key not in series:
            series[key] = {
                "key": key,
                "label": " — ".join(labels[k].get(coord[k], coord[k]) for k in dims if k != "unit"),
                "unit": labels["unit"].get(coord["unit"], coord["unit"]) if "unit" in coord else "",
                "freq": freq,
                "ref": f"Eurostat {src['dataset']} : " + ", ".join(f"{k}={coord[k]}" for k in dims),
                "updated": d.get("updated"),
                "obs": {},
            }
        series[key]["obs"][coord["time"]] = val
    return list(series.values())


def insee(src, cfg):
    """Séries d'un jeu de données de la BDM Insee (SDMX), filtrées sur le titre si demandé."""
    params = {"startPeriod": src["since"]} if src.get("since") else None
    root = ET.fromstring(_get(INSEE + src["dataflow"], params).content)
    pattern = re.compile(src["title"], re.I) if src.get("title") else None
    out = []
    for s in root.iter():
        if not s.tag.endswith("Series"):
            continue
        a = s.attrib
        title = a.get("TITLE_FR", "")
        if pattern and not pattern.search(title):
            continue
        if a.get("SERIE_ARRETEE") == "TRUE":
            continue
        obs = {}
        for o in s:
            v = o.get("OBS_VALUE")
            if v not in (None, "", "NaN"):
                obs[o.get("TIME_PERIOD")] = float(v)
        mult = int(a.get("UNIT_MULT") or 0)
        unit = a.get("UNIT_MEASURE", "")
        out.append({
            "key": "insee." + a["IDBANK"],
            "label": title,
            "unit": unit + (f" (×10^{mult})" if mult else ""),
            "freq": FREQ_INSEE.get(a.get("FREQ"), a.get("FREQ", "")),
            "ref": f"Insee BDM {src['dataflow']} : idbank {a['IDBANK']}",
            "updated": a.get("LAST_UPDATE"),
            "obs": obs,
        })
    if not out:
        raise RuntimeError("aucune série retenue (filtre sur le titre trop strict ?)")
    return out


def insee_melodi(src, cfg):
    """Jeu de données du catalogue Insee (API Melodi, fichier CSV complet), filtré sur ses dimensions.

    Une série par combinaison des dimensions `key_dims` ; les autres dimensions doivent être fixées
    par `filters` (sinon plusieurs valeurs se mélangeraient dans une même série). `exclude` écarte des
    valeurs de dimension (ex. agrégats « Total des dépenses » non consolidés, qui ne sont pas ceux publiés)."""
    meta = _get(MELODI + "catalog/" + src["dataset"]).json()
    product = next(p for p in meta["product"] if p["id"].endswith("_CSV_FR"))
    url = product.get("url") or product.get("accessURL") or MELODI + f"file/{src['dataset']}/{product['id']}"
    z = zipfile.ZipFile(io.BytesIO(_get(url).content))
    names = {n.rsplit("_", 1)[-1]: n for n in z.namelist()}  # …_data.csv, …_metadata.csv
    labels = {}
    with z.open(names["metadata.csv"]) as f:
        for r in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"), delimiter=";"):
            labels[(r["COD_VAR"], r["COD_MOD"])] = r["LIB_MOD"]
    filters = {k: set(v if isinstance(v, list) else [v]) for k, v in src["filters"].items()}
    exclude = {k: set(v) for k, v in src.get("exclude", {}).items()}
    dims, since = src["key_dims"], src.get("since", "")
    updated = meta.get("modified", "")[:10] or None
    series = {}
    with z.open(names["data.csv"]) as f:
        for r in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"), delimiter=";"):
            if r["OBS_VALUE"] == "" or r["TIME_PERIOD"] < since or any(r[k] not in vs for k, vs in filters.items()) \
                    or any(r[k] in vs for k, vs in exclude.items()):
                continue
            key = ".".join([src["prefix"]] + [r[k] for k in dims])
            if key not in series:
                mult = int(r.get("UNIT_MULT") or 0)
                unit = labels.get(("UNIT_MEASURE", r["UNIT_MEASURE"]), r["UNIT_MEASURE"])
                series[key] = {
                    "key": key,
                    "label": " — ".join(labels.get((k, r[k]), r[k]) for k in dims),
                    "unit": "Millions d'euros" if (r["UNIT_MEASURE"], mult) == ("XDC", 6) else unit + (f" (×10^{mult})" if mult else ""),
                    "freq": r["FREQ"],
                    "ref": f"Insee, catalogue de données {src['dataset']} : " + ", ".join(f"{k}={r[k]}" for k in dims),
                    "updated": updated,
                    "obs": {},
                }
            series[key]["obs"][r["TIME_PERIOD"]] = float(r["OBS_VALUE"])
    if not series:
        raise RuntimeError("aucune série retenue (filtres trop stricts ?)")
    return list(series.values())


def _slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _cell(c):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()


def insee_tableau(src, cfg):
    """Tableau publié dans une page insee.fr (ex. « Principaux agrégats de finances publiques »), repris tel quel.

    Une série par ligne ; les renvois « (1) » sont retirés des libellés. L'adresse de la page change à chaque
    édition annuelle : la mettre à jour dans config.json (un contrôle signale quand l'édition semble dépassée)."""
    page = _get(src["url"]).text
    tables = [t for t in re.findall(r"<table.*?</table>", page, re.S) if re.search(src["table"], _cell(t), re.I)]
    if not tables:
        raise RuntimeError(f"tableau « {src['table']} » introuvable dans la page")
    rows = [[_cell(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)] for tr in re.findall(r"<tr.*?</tr>", tables[0], re.S)]
    years = rows[0][1:]
    if not all(re.fullmatch(r"\d{4}", y) for y in years):
        raise RuntimeError(f"en-tête inattendu : {rows[0]}")
    m = re.search(r"Paru le(?:&nbsp;|\s)*:(?:\s|<[^>]+>)*(\d{2})/(\d{2})/(\d{4})", page)
    updated = f"{m[3]}-{m[2]}-{m[1]}" if m else None
    title = _cell(re.search(r"<title>(.*?)</title>", page, re.S)[1]) if "<title>" in page else src["url"]
    out = []
    for row in rows[1:]:
        label = re.sub(r"\s*\(\d+\)\s*", " ", row[0]).strip()
        vals = {y: float(v.replace(",", ".").replace("−", "-")) for y, v in zip(years, row[1:]) if re.fullmatch(r"[-−]?\d+(,\d+)?", v)}
        if not vals:
            continue
        slug = _slug(label)
        variants = [(slug, src.get("label_prefix", "") + label, 1)]
        if slug in src.get("negate", {}):  # ex. solde = − déficit publié, pour garder le signe des séries Eurostat
            variants.append((src["negate"][slug]["key"], src["negate"][slug]["label"], -1))
        for k, lab, sign in variants:
            out.append({"key": f"{src['prefix']}.{k}", "label": lab, "unit": src["unit"], "freq": "A",
                        "ref": f"{title} — {src['url']}", "updated": updated,
                        "obs": {y: round(sign * v, 6) for y, v in vals.items()}})
    if datetime.now() >= datetime(datetime.now().year, 6, 15) and max(years) < str(datetime.now().year - 1):
        raise RuntimeError(f"édition dépassée (dernière année {max(years)}) : mettre à jour l'adresse de la page dans config.json")
    return out


PROVIDERS = {"eurostat": eurostat, "insee": insee, "insee_melodi": insee_melodi, "insee_tableau": insee_tableau}


def fetch(src, cfg):
    return PROVIDERS[src["provider"]](src, cfg)
