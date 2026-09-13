"""Device digest tables: defs load, synthetic fixture gates, teardown is leaf-first.

Wave 1 Lane B. The seed lists device then device-extraction; teardown_plan must
delete the extraction first. Reversing that pair in the assertion is the red
that pins the order (device-first teardown would leave restrict-on-delete stuck).
"""
import importlib.util
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
MOD = REPO / "files" / "anatomy" / "module_utils" / "nos_digest.py"
TABLES_DIR = REPO / "state" / "keap-tables"
SEED = REPO / "state" / "fixtures" / "device.seed.yml"


def _nd():
    spec = importlib.util.spec_from_file_location("nos_digest", MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ND = _nd()


def _seed() -> dict:
    return yaml.safe_load(SEED.read_text())


def test_defs_load():
    for slug in ("device", "device-extraction"):
        doc = yaml.safe_load((TABLES_DIR / f"{slug}.table.yml").read_text())
        assert doc["visibility"] == "tier-managers"
        assert "graph" not in doc
        keys = [c["key"] for c in doc["schema"]["columns"]]
        assert "slug" in keys


def test_synthetic_fixture_check_bundle_is_empty():
    seed = _seed()
    assert list(seed.keys()) == ["device", "device-extraction"]
    assert ND.check_fixture_seed(seed, TABLES_DIR) == []
    assert ND.check_bundle({"meta": {"trusted": True}, "deterministic": seed}, TABLES_DIR) == []


def test_teardown_plan_is_leaf_first():
    seed = _seed()
    plan = ND.teardown_plan(seed)
    assert plan[0][0] == "device-extraction"
    assert plan[-1][0] == "device"
    assert plan[0][0] != list(seed.keys())[0]
    assert plan == ND.teardown_plan({"meta": {}, "deterministic": seed})
