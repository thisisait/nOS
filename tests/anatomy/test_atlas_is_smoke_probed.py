"""rel-016 MUST (2): the atlas works end to end, smoke-probed.

GeoLibre serves the map, martin the tiles (behind Authentik, on the GeoLibre
domain at /tiles), and the ČÚZK cadastral layers are martin sources inspire_cp
(parcels) and inspire_bu (buildings). Before 2026-10-09 nothing in
`nos-smoke --strict` asked for a tile source: a green smoke said nothing about
the MUST.
"""
from __future__ import annotations

import importlib.util
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CUZK_SOURCES = ("inspire_cp", "inspire_bu")


def _rows():
    spec = importlib.util.spec_from_file_location("_smoke", REPO / "tools" / "nos-smoke.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    catalog = yaml.safe_load((REPO / "state" / "smoke-catalog.yml").read_text(encoding="utf-8"))
    vars_dict = {"tenant_domain": "test.local", "geolibre_domain": "geolibre.test.local",
                 "install_geolibre": True, "install_martin": True}
    return smoke.merge_catalog([], catalog.get("smoke_endpoints") or [],
                               catalog.get("smoke_defaults") or {}, vars_dict)


def test_each_cuzk_source_is_asked_for_by_a_signed_in_tester():
    tiles = [r for r in _rows() if "geolibre.test.local/tiles/" in r["url"]]
    for src in CUZK_SOURCES:
        hit = [r for r in tiles if src in (r.get("require_json") or "")]
        assert hit, f"no smoke row asks martin's catalog for the ČÚZK source {src}"
        for r in hit:
            assert r.get("auth") == "tester", f"{r['id']}: tiles are behind Authentik; the row needs auth: tester"
            assert (r.get("expect_strict") or []) == [200], f"{r['id']}: strict must want the signed-in 200"
