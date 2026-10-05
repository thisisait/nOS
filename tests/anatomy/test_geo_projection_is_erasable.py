"""Anatomy gate — party sites reach PostGIS one-way, and a party erasure reaches PostGIS too.

nos_digest.erasure_plan walks KEAP's rowRef graph, so party-site rows (rowRef
party) are covered for free. geo.party_site is a copy OUTSIDE that graph: until
2026-10-03 nothing erased it, and a sole trader's (OSVČ) site — a natural
person's address — would survive an Art. 17 erasure until the next nightly
projection, or forever if that job was paused. This gate pins:

  1. party-site is a party facet (rowRef party, restrict) with the agreed kinds;
  2. erasure_plan reaches party-site rows;
  3. digest-teardown --erase-party --confirm also erases geo.party_site, by
     party slug passed as a psql variable (never interpolated into SQL);
  4. the erasure map names the projection (svc_geo) and how to erase it;
  5. projection: an operator hq outranks ARES's seat; ARES fills the gap.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
TABLES = REPO / "state/keap-tables"


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, REPO / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_party_site_is_a_party_facet():
    cols = {c["key"]: c for c in yaml.safe_load((TABLES / "party-site.table.yml").read_text())["schema"]["columns"]}
    assert cols["party"]["kind"] == "rowRef" and cols["party"]["refTable"] == "party"
    assert cols["party"]["onDelete"] == "restrict"
    assert cols["kind"]["options"] == ["hq", "branch", "factory", "warehouse", "parcel"]
    assert {"ruian_adm", "ku_kod", "parcel_no", "kod_so"} <= set(cols)


def test_erasure_plan_reaches_party_sites():
    nd = _load("nos_digest", "files/anatomy/module_utils/nos_digest.py")
    rows = {"party-site": [{"slug": "s1", "party": "p-a"}, {"slug": "s2", "party": "p-b"}]}
    plan = nd.erasure_plan("p-a", lambda t: rows.get(t, []), TABLES)
    assert [r["slug"] for r in plan.get("party-site", [])] == ["s1"]


def test_party_erasure_also_erases_the_postgis_projection():
    tree = ast.parse((REPO / "tools/digest-teardown.py").read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and any(isinstance(c, ast.Constant) and c.value == "--erase-party"
                     for a in n.args if isinstance(a, ast.List) for c in a.elts)]
    assert calls, "digest-teardown --erase-party must run tools/geo-project-sites.py --erase-party"
    src = (REPO / "tools/geo-project-sites.py").read_text()
    assert "WHERE party = :'party'" in src, "the slug reaches psql as a quoted variable, not SQL text"


def test_the_erasure_map_names_the_projection():
    rows = {e["id"]: e for e in yaml.safe_load((REPO / "state/gdpr-erasure-map.yml").read_text())["services"]}
    geo = rows.get("svc_geo")
    assert geo and geo["flag"] == "install_postgis"
    assert "geo.party_site" in geo["note"] and "--erase-party" in geo["note"]


def test_projection_prefers_the_operator_hq_over_ares():
    g = _load("geo_project_sites", "tools/geo-project-sites.py")
    sites = [{"slug": "s-hq", "party": "p-a", "kind": "hq", "ruian_adm": 1},
             {"slug": "s-x", "kind": "branch"}]                      # no party: dropped
    reg = [{"slug": "reg-a", "party": "p-a", "sidlo_ruian_adm": 9},
           {"slug": "reg-b", "party": "p-b", "sidlo_ruian_adm": 7},
           {"slug": "reg-c", "party": "p-c"}]                        # no seat: dropped
    rows = {r["slug"]: r for r in g.project(sites, reg)}
    assert set(rows) == {"s-hq", "reg-b"}
    assert rows["reg-b"]["kind"] == "hq" and rows["reg-b"]["source"] == "ares" and rows["reg-b"]["ruian_adm"] == 7
