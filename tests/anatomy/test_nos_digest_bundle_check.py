"""The load-bearing digest judge: nos_digest.check_bundle().

Validated against the REAL fixture seeds (which are trusted deterministic
bundles — their {slug:[rows]} IS the deterministic section) plus deliberate
corruptions, so the gate that stands between an importer and the live doors is
itself gated.
"""
import copy
import importlib.util
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
MOD = REPO / "files" / "anatomy" / "module_utils" / "nos_digest.py"
TABLES = REPO / "state" / "keap-tables"


def _nd():
    spec = importlib.util.spec_from_file_location("nos_digest", MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ND = _nd()


def _seed(name: str) -> dict:
    return yaml.safe_load((REPO / "state" / "fixtures" / f"{name}.seed.yml").read_text())


def test_real_fixtures_pass_as_trusted_bundles():
    for name in ("label-printer", "kolben-it"):
        errs = ND.check_fixture_seed(_seed(name), TABLES)
        assert errs == [], f"{name} should be a valid trusted bundle: {errs}"


def test_untrusted_bundle_requires_per_row_provenance():
    # the same good fixture, declared UNTRUSTED → every row lacks _prov
    errs = ND.check_bundle({"meta": {}, "deterministic": _seed("kolben-it")}, TABLES)
    assert errs, "an untrusted bundle without _prov must fail"
    assert all("_prov" in e for e in errs), errs


def test_forward_reference_is_caught():
    # reverse the key order so domain tables precede the party spine they rowRef
    seed = _seed("kolben-it")
    reordered = {k: seed[k] for k in reversed(list(seed.keys()))}
    errs = ND.check_bundle({"meta": {"trusted": True}, "deterministic": reordered}, TABLES)
    assert any("FORWARD" in e for e in errs), errs


def test_unresolved_rowref_is_caught():
    seed = copy.deepcopy(_seed("kolben-it"))
    seed["kolben-ticket"][0] = {**seed["kolben-ticket"][0], "project": "no-such-project"}
    errs = ND.check_bundle({"meta": {"trusted": True}, "deterministic": seed}, TABLES)
    assert any("no-such-project" in e for e in errs), errs


def test_untrusted_bundle_with_provenance_passes():
    seed = copy.deepcopy(_seed("label-printer"))
    stamp = {"source_id": "src:test", "importer_version": "0.0.0", "content_hash": "abc"}
    for rows in seed.values():
        for r in rows:
            r["_prov"] = dict(stamp)
    errs = ND.check_bundle(
        {"meta": {"source_id": "src:test", "trusted": False}, "deterministic": seed}, TABLES)
    assert errs == [], f"a stamped untrusted bundle should pass: {errs}"


def test_unknown_top_level_key_is_flagged():
    errs = ND.check_bundle({"meta": {"trusted": True}, "deterministic": {}, "bogus": 1}, TABLES)
    assert any("bogus" in e for e in errs), errs
