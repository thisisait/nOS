"""Anatomy gate — the open-data geo loader loads the right units and fails loud.

Each assertion is a defect measured on 2026-10-03 against real ČÚZK data:
  * the RÚIAN download page is behind a bot captcha — scraping it found no link,
    so the month-end URL is computed;
  * INSPIRE buildings without a footprint are points — a MULTIPOLYGON staging
    column refused them mid-load;
  * ogr2ogr sizes text columns from the FIRST file (varchar(7) for a parcel
    label), so a later file with a longer value fails — PRECISION=NO;
  * a layer is "unchanged" only for the same unit set, or a new kraj never loads;
  * a swap by DROP TABLE fails once geo.party_site_geom depends on the layer.
"""
from __future__ import annotations

import datetime
import importlib.util
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("geo_load", REPO / "tools/geo-load.py")
geo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(geo)

CATALOG = """KRAJ_KOD;KRAJ_NAZEV;OKRES_KOD;NUTS4;OKRES_NAZEV;OBEC_KOD;OBEC_NAZEV;KU_KOD;KU_PRAC;KU_NAZEV;MAPA;CISELNA_RADA;PLATNOST_OD;PLATNOST_DO;PRARES_KOD;PRARES_NAZEV;POZNAMKA
35;Jihočeský kraj;3301;;;544256;Č. Budějovice;622214;;KU1;D;1;01.01.1990;;;;
35;Jihočeský kraj;3301;;;544256;Č. Budějovice;622222;;KU2;D;1;01.01.1990;31.12.2020;;;
19;Hlavní město Praha;;;;554782;Praha;601527;;Běchovice;D;1;01.03.1994;;;;
"""


def test_region_units_takes_valid_units_of_the_kraj_only():
    assert geo.region_units(CATALOG, {"35"}) == (["622214"], ["544256"])


def test_adm_header_drift_is_refused():
    header = ";".join(["c"] * len(geo.ADM_COLS))
    assert geo.adm_body_lines(header + "\n1;2\n") == ["1;2"]
    with pytest.raises(SystemExit):
        geo.adm_body_lines("a;b;c\n1;2;3\n")


def test_ruian_url_is_computed_not_scraped():
    assert not hasattr(geo, "ADM_PAGE"), "the RÚIAN HTML index answers a bot captcha"
    assert geo.adm_candidates(datetime.date(2026, 10, 3)) == ["20260930", "20260831"]
    assert geo.adm_candidates(datetime.date(2026, 1, 15)) == ["20251231", "20251130"]


def test_gml_staging_is_typed_for_real_data():
    src = (REPO / "tools/geo-load.py").read_text()
    assert "-lco PRECISION=NO" in src, "first-file varchar widths break the next file"
    assert '"bu": ("inspire_bu", BU_URL, obce, "GEOMETRY"' in src, "point-only buildings exist"
    assert "def current(self, table: str, sig: str)" in src, "a changed unit set must reload"


def test_each_layer_swaps_in_one_transaction_and_logs_the_count():
    src = (REPO / "tools/geo-load.py").read_text()
    for body in src.split('pg.sql(f"""BEGIN;')[1:]:
        block = body.split('COMMIT;""")')[0]
        assert "INSERT INTO geo.load_log" in block and "count(*)" in block
        assert "TRUNCATE" in block and "DROP TABLE IF EXISTS geo.{table}" not in block, (
            "swap by TRUNCATE + INSERT — a view depends on the layer tables")


def test_pulse_job_is_wired_through_both_token_lists():
    plugin = yaml.safe_load((REPO / "files/anatomy/plugins/geo-base/plugin.yml").read_text())
    assert plugin["requires"]["feature_flag"] == "install_postgis"
    job = plugin["pulse"]["jobs"][0]
    catalog = (REPO / "files/anatomy/scripts/discover-pulse-catalog.py").read_text()
    wing = (REPO / "roles/pazny.wing/tasks/post.yml").read_text()
    for token, env in (("{{ geo_region_codes }}", "NOS_GEO_REGION_CODES"), ("{{ geo_cache_dir }}", "NOS_GEO_CACHE_DIR")):
        assert token in job["args"]
        assert f'"{token}":' in catalog and f"{env}:" in wing, f"{token} must reach Pulse rendered"
