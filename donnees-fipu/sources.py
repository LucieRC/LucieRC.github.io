"""Lecture des sources publiques. Chaque fonction renvoie une liste de séries :

    {"key", "label", "unit", "freq", "ref", "updated", "obs": {période: valeur}}

Les périodes suivent la notation des sources : « 2024 », « 2024-Q3 », « 2024-07 ».
"""
import re
import xml.etree.ElementTree as ET

import requests

UA = "DonneesFiPu/0.1 (collecte de statistiques publiques)"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
INSEE = "https://bdm.insee.fr/series/sdmx/data/"
SKIP_DIMS = ("time", "freq")
FREQ_INSEE = {"A": "A", "T": "Q", "M": "M", "S": "S", "B": "M2"}


def _get(url, params=None, timeout=180):
    r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": UA})
    r.raise_for_status()
    return r


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


PROVIDERS = {"eurostat": eurostat, "insee": insee}


def fetch(src, cfg):
    return PROVIDERS[src["provider"]](src, cfg)
