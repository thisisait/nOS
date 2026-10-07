"""A tissue gathers what exists; it never declares anything of its own.

state/tissues/<name>.tissue.yml lists ids of cells, skills, tables, services,
reflexes, importers and seeds (ssot/doctrine/tissue.md, PROPOSED). The
failure this guards is a pack that reads as transplantable while naming a part
that is gone, or that carries personal data no member declared under Article
30. Each rule is checked on the real manifests AND shown to refuse a broken one.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import pathlib

import pytest
import yaml

jsonschema = pytest.importorskip("jsonschema")

REPO = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = REPO / "state" / "genome" / "tissue.schema.json"
GRAPH = REPO / "state" / "anatomy-graph.json"


def _mod(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T = _mod("_tissue_status", REPO / "tools" / "tissue-status.py")
TISSUES = T.load_all()


def _refused(doc: dict) -> list[str]:
    errs = T._schema_errors(doc)
    bad, gdpr = T.resolve(doc) if not errs else ([], {})
    return errs + bad + T.art30_gaps(gdpr)


def test_there_is_a_tissue_and_the_schema_is_a_schema():
    jsonschema.Draft7Validator.check_schema(json.loads(SCHEMA.read_text(encoding="utf-8")))
    assert [t["name"] for t in TISSUES if t["name"] == "backoffice"], (
        "state/tissues/backoffice.tissue.yml is gone — the first instance the doctrine names")


@pytest.mark.parametrize("t", TISSUES, ids=lambda t: t["name"])
def test_every_tissue_holds(t):
    assert not t["refused"], f"{t['source']} refused:\n  " + "\n  ".join(t["refused"])


@pytest.mark.parametrize("key,bad", [
    ("cells", "no-such-cell"), ("skills", "no-such-skill"), ("tables", "no-such-table"),
    ("services", "no-such-service"), ("reflexes", "crm-hydrate:no-such-job"),
    ("importers", "no-such-importer"), ("seeds", "no-such-seed"),
    ("acceptance", "no-such-fixture"),
])
def test_a_dangling_reference_is_refused(key, bad):
    doc = copy.deepcopy(next(t["doc"] for t in TISSUES if t["name"] == "backoffice"))
    doc[key] = [*doc.get(key, []), bad]
    assert any(bad.split(":")[-1] in r for r in _refused(doc)), f"{key}: {bad} was accepted"


def test_a_tissue_cannot_declare_its_own_gdpr_or_an_unknown_key():
    doc = copy.deepcopy(next(t["doc"] for t in TISSUES if t["name"] == "backoffice"))
    doc["gdpr"] = {"purpose": "authored here instead of inherited"}
    assert _refused(doc), "a tissue-level gdpr block was accepted; Art 30 is inherited"


@pytest.mark.parametrize("t", TISSUES, ids=lambda t: t["name"])
def test_art30_is_inherited_from_every_processing_member(t):
    d = t["doc"]
    want = ({f"cell {c}" for c in d["cells"]} | {f"service {s}" for s in d["services"]}
            | {f"reflex {r}" for r in d["reflexes"]}
            | {f"importer {i}" for i in d.get("importers") or []})
    assert set(t["processors"]) == want
    broken = {"purpose": "x", "legal_basis": "because"}
    assert T.art30_gaps({"cell probe": broken}), "an incomplete member block was accepted"


@pytest.mark.parametrize("t", TISSUES, ids=lambda t: t["name"])
def test_the_acceptance_fixture_stays_inside_the_tissue(t):
    """Every table a fixture seeds is one the tissue holds — the fixture runs
    through this tissue, not through a table someone forgot to list."""
    held = set(t["doc"]["tables"])
    for f in t["doc"]["acceptance"]:
        seeded = set(yaml.safe_load((REPO / "state" / "fixtures" / f"{f}.seed.yml")
                                    .read_text(encoding="utf-8")))
        assert seeded <= held, f"{f} seeds tables {sorted(seeded - held)} the tissue does not hold"


@pytest.mark.parametrize("t", [t for t in TISSUES if t["doc"].get("profile")], ids=lambda t: t["name"])
def test_the_profile_installs_every_service(t):
    ident = _mod("_nos_identity", REPO / "tools" / "nos_identity.py")
    merged: dict = {}
    for layer in [*ident.default_layers(), REPO / "profiles" / f"{t['doc']['profile']}.yml"]:
        merged |= yaml.safe_load(layer.read_text(encoding="utf-8")) or {}
    rows = {s["id"]: s for s in yaml.safe_load(
        (REPO / "state" / "manifest.yml").read_text(encoding="utf-8"))["services"]}
    off = [s for s in t["doc"]["services"] if merged.get(rows[s]["install_flag"]) is not True]
    assert not off, f"profiles/{t['doc']['profile']}.yml leaves off {off}"


@pytest.mark.parametrize("t", TISSUES, ids=lambda t: t["name"])
def test_every_tissue_is_a_node_its_members_are_part_of(t):
    g = json.loads(GRAPH.read_text(encoding="utf-8"))
    nid = f"tissue:{t['name']}"
    assert g["nodes"].get(nid, {}).get("kind") == "tissue", f"{nid} missing from the anatomy graph"
    d = t["doc"]
    want = ({f"agent:{c}" for c in d["cells"]} | {f"skill:{s}" for s in d["skills"]}
            | {f"table:{x}" for x in d["tables"]} | {f"service:{s}" for s in d["services"]}
            | {f"pulse:{r}" for r in d["reflexes"]})
    got = {e["from"] for e in g["edges"] if e["to"] == nid and e["kind"] == "part_of"}
    assert got == want, f"part_of edges differ: missing {sorted(want - got)}, extra {sorted(got - want)}"
