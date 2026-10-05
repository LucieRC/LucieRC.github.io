"""Assemble data/*.json + template.html → dist/reperes-fipu.html (un seul fichier, sans dépendance)."""
import json
from pathlib import Path

import jorf

ROOT = Path(__file__).parent
OUT = ROOT / "dist" / "reperes-fipu.html"


def main():
    cfg = json.loads((ROOT / "config.json").read_text())
    data = json.loads((ROOT / "data" / "data.json").read_text())
    try:
        store = json.loads((ROOT / "data" / "jorf.json").read_text())
    except FileNotFoundError:
        store = None
    # Les filtres sont appliqués ici : modifier config.json puis relancer build.py suffit.
    data["jorf_entries"] = jorf.for_page(store, cfg["jorf"]) if store else []
    data["jorf_filters"] = [{"id": f["id"], "label": f["label"]} for f in cfg["jorf"]["filters"]]
    data["jorf_all_days"] = cfg["jorf"]["all_texts_days"]
    data["stale_page_days"] = cfg["stale_page_days"]
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = (ROOT / "template.html").read_text()
    if "/*__DATA__*/null" not in html:
        raise SystemExit("marqueur /*__DATA__*/null absent du template")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html.replace("/*__DATA__*/null", payload))
    print(f"→ {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    main()
