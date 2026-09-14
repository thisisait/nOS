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


# Pairing-registry columns belong on device-client (dtt devices-table), not
# on the digest physical-unit table. The 2026-09-14 handoff proposed a
# `devices` registry; `device` is already this family.
_REGISTRY_KEYS = frozenset({
    "paired_at", "last_seen", "fingerprint", "pubkey", "device_id",
})


def test_device_client_is_the_pairing_registry():
    pairing = yaml.safe_load((TABLES_DIR / "device-client.table.yml").read_text())
    assert pairing["visibility"] == "tier-managers"
    assert "graph" not in pairing
    keys = {c["key"] for c in pairing["schema"]["columns"]}
    for col in ("slug", "type", "owner", "fingerprint", "scopes", "paired_at", "last_seen", "status"):
        assert col in keys, f"device-client missing pairing column {col}"
    digest = yaml.safe_load((TABLES_DIR / "device.table.yml").read_text())
    digest_keys = {c["key"] for c in digest["schema"]["columns"]}
    assert not (digest_keys & {"paired_at", "last_seen", "fingerprint"})


def test_digest_device_is_not_the_pairing_registry():
    doc = yaml.safe_load((TABLES_DIR / "device.table.yml").read_text())
    keys = {c["key"] for c in doc["schema"]["columns"]}
    overlap = sorted(keys & _REGISTRY_KEYS)
    assert not overlap, (
        "digest device table grew pairing-registry columns "
        f"{overlap}; the gateway registry is slug device-client, not device"
    )
    assert "identifier_hash" in keys
    text = (TABLES_DIR / "device.table.yml").read_text()
    assert "device-client" in text, (
        "the digest table header lost the pointer at the gateway registry slug"
    )


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
