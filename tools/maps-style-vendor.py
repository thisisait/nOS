#!/usr/bin/env python3
"""Vendor an OpenFreeMap style for the local tileserver (pazny.offline_maps).

Fetches https://tiles.openfreemap.org/styles/<name>, then rewrites it so every
reference is local: the OpenMapTiles source becomes `pmtiles://{basemap}`, the
hosted Natural Earth hillshade source and its layer are dropped, sprites and
glyphs become tileserver-gl placeholders, and labels prefer `name:cs`.
Writes roles/pazny.offline_maps/files/styles/<name>.json. Re-run to refresh.
"""
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "roles/pazny.offline_maps/files/styles"
SRC = "https://tiles.openfreemap.org/styles/{name}"
LABEL_LANG = "name:cs"


def localize(style: dict, name: str) -> dict:
    style["name"] = f"nos-{name}"
    style["sprite"] = "ofm"                       # joined with paths.sprites
    style["glyphs"] = "{fontstack}/{range}.pbf"   # resolved under paths.fonts
    style["sources"] = {"openmaptiles": {"type": "vector", "url": "pmtiles://{basemap}"}}
    style["layers"] = [l for l in style["layers"] if l.get("source", "openmaptiles") == "openmaptiles"]
    text = json.dumps(style)
    text = text.replace('["get", "name_en"]', f'["get", "{LABEL_LANG}"]')
    style = json.loads(text)
    style["metadata"] = {
        "nos:source": SRC.format(name=name),
        "nos:tool": "tools/maps-style-vendor.py",
        "nos:labels": f"{LABEL_LANG} before name",
    }
    return style


def main() -> int:
    names = sys.argv[1:] or ["liberty"]
    OUT.mkdir(parents=True, exist_ok=True)
    for name in names:
        req = urllib.request.Request(SRC.format(name=name), headers={"User-Agent": "nos-maps-style-vendor"})
        with urllib.request.urlopen(req, timeout=60) as r:
            style = json.load(r)
        out = OUT / f"{name}.json"
        out.write_text(json.dumps(localize(style, name), indent=1, ensure_ascii=False) + "\n")
        print(f"{out}: {len(style['layers'])} layers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
