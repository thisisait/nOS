"""Anatomy gate — the genome is one declaration, and it describes reality.

The estate restates the same law by hand in every runtime that needs it. Measured
before this schema existed:

  * the RBAC tier→group map in **7 places across 5 languages**, including a live
    shape mismatch in `superset_config.py.j2` (reads `.admin` as a dict against a
    list-of-dicts) that `| default()` had been hiding;
  * GDPR Article 30 in **4 declarations** with inverse spellings of one fact —
    `plugin.schema.json` requires `eu_residency`, `app.schema.json` requires
    `transfers_outside_eu`, and `nos_gdpr.py` exists to paper over the split;
  * tier visibility as an **unvalidated string** in `state/keap-tables/*.table.yml`
    — the existing test checks only that the key is present, never that the value
    is legal;
  * face↔KEAP contracts hand-mirrored with **no gate at all**, already drifted
    (11 ColumnKinds vs 12);
  * exposure/gating split **five ways**, which is what produced REM-144.

`state/genome/entity.schema.json` is the single declaration those collapse onto.
This file pins three things about it: the generated artifacts are current, the
schema is *composable* (an organelle inherits it rather than restating it), and —
the one that matters most — **the schema describes the estate that exists**, not
an idealised one. A base entity that no live manifest satisfies is fiction.

CI-safe: pure file + schema work. No Docker, no network, no live host.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
GENOME = REPO / "state" / "genome"
ENTITY = GENOME / "entity.schema.json"
ORGANELLE_DIR = GENOME / "organelle"
CODEGEN = REPO / "tools" / "genome-codegen.py"
PLUGINS = REPO / "files" / "anatomy" / "plugins"

jsonschema = pytest.importorskip("jsonschema")


def _entity() -> dict:
    return json.loads(ENTITY.read_text())


def _facet(name: str) -> dict:
    return _entity()["definitions"][name]


# ── the declaration itself ────────────────────────────────────────────────


def test_entity_schema_is_valid_draft7():
    jsonschema.Draft7Validator.check_schema(_entity())


def test_dialect_matches_the_rest_of_the_estate():
    """draft-07 + `definitions`, like 6 of the 7 schemas in state/schema/.

    Using `$defs` here would be correct JSON Schema and a second dialect in one
    repo. The genome exists to remove divergence, so it does not open with some.
    """
    s = _entity()
    assert s["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert "definitions" in s and "$defs" not in s


def test_every_facet_is_reachable_from_the_base():
    """A facet nothing references is a facet nobody will fill in."""
    s = _entity()
    base_props = s["definitions"]["entity"]["properties"]
    referenced = {v["$ref"].rsplit("/", 1)[-1] for v in base_props.values() if "$ref" in v}
    declared = set(s["definitions"]) - {"entity"}
    assert declared == referenced, (
        f"facets declared but not composed into the base: {sorted(declared - referenced)}; "
        f"composed but not declared: {sorted(referenced - declared)}"
    )


# ── composition: the thing the estate has never done across a file ────────


def _organelle_validator(path: pathlib.Path):
    org = json.loads(path.read_text())
    store = {"https://thisisait.eu/nos/schema/entity.schema.json": _entity()}
    resolver = jsonschema.RefResolver(base_uri=org["$id"], referrer=org, store=store)
    return jsonschema.Draft7Validator(org, resolver=resolver), org


def test_at_least_one_organelle_composes_the_base():
    files = sorted(ORGANELLE_DIR.glob("*.schema.json"))
    assert files, "no organelle schemas — the base composes with nothing and proves nothing"
    for f in files:
        org = json.loads(f.read_text())
        refs = json.dumps(org)
        assert "allOf" in org, f"{f.name} does not use allOf — it is not composing, it is restating"
        assert "entity.schema.json#/definitions/entity" in refs, (
            f"{f.name} does not reference the base entity"
        )


def test_organelle_rejects_an_illegal_visibility():
    """Today this value is a free string that nothing checks."""
    v, _ = _organelle_validator(ORGANELLE_DIR / "data-table.schema.json")
    inst = _valid_data_table()
    inst["table"]["visibility"] = "Manager"  # legal-looking, wrong case
    assert list(v.iter_errors(inst)), "an illegal visibility validated — the enum is not enforced"


def test_organelle_enforces_the_rem144_clause():
    """A routed entity with no gate must carry a justification FIELD.

    This is Part 0.4's rule expressed as schema instead of as a hand-written
    pytest. `traefik: none` was justified by a prose comment that had been false
    since batch-21, and nothing compared it to the router actually rendered.
    """
    v, _ = _organelle_validator(ORGANELLE_DIR / "data-table.schema.json")

    ungated = _valid_data_table()
    ungated["access"] = {"routed": True, "gate": "none"}
    errs = [e.message for e in v.iter_errors(ungated)]
    assert any("justification" in e for e in errs), (
        f"a routed, ungated entity validated with no justification: {errs}"
    )

    ungated["access"]["justification"] = (
        "Public tile server by design - read-only, no user data, no Authentik provider exists."
    )
    assert not list(v.iter_errors(ungated)), "a justified ungated route was rejected"


def _valid_data_table() -> dict:
    return {
        "identity": {
            "name": "business-partners",
            "version": "1",
            "description": "Operator-authored partner rows",
            "kind": "data-table",
        },
        "compliance": {
            "purpose": "Business contact rows authored by the operator.",
            "legal_basis": "legitimate_interests",
            "data_categories": ["business_contacts"],
            "data_subjects": ["tenant_users"],
            "retention_days": 0,
            "processors": [],
            "eu_residency": True,
        },
        "access": {"routed": False, "gate": "none"},
        "table": {"slug": "business-partners", "visibility": "manager"},
    }


def test_the_happy_instance_is_actually_valid():
    """Guards the negative tests above: if the baseline were invalid they would
    pass for the wrong reason."""
    v, _ = _organelle_validator(ORGANELLE_DIR / "data-table.schema.json")
    assert not list(v.iter_errors(_valid_data_table()))


# ── does it describe the estate that exists? ──────────────────────────────


def test_compliance_facet_accepts_every_live_manifest():
    """The load-bearing test.

    All 72 plugin manifests carry a `gdpr:` block. If the genome's compliance
    facet cannot validate them, the facet is a redesign wearing a schema's
    clothes, and every migration onto it would be a rewrite. It must fit what is
    already written — the two accepted residency spellings included.
    """
    facet = _facet("compliance")
    store = {"https://thisisait.eu/nos/schema/entity.schema.json": _entity()}
    resolver = jsonschema.RefResolver(base_uri=ENTITY.as_uri(), referrer=_entity(), store=store)
    v = jsonschema.Draft7Validator(facet, resolver=resolver)

    manifests = sorted(PLUGINS.rglob("plugin.yml"))
    assert len(manifests) >= 70, f"only {len(manifests)} manifests found — glob drift?"

    offenders = []
    for m in manifests:
        block = (yaml.safe_load(m.read_text()) or {}).get("gdpr")
        if not block:
            continue
        errs = [e.message for e in v.iter_errors(block)]
        if errs:
            offenders.append(f"{m.relative_to(REPO)}: {errs[0]}")

    assert not offenders, (
        "the genome's compliance facet rejects manifests that ship today — the "
        "facet must describe the estate before anything migrates onto it:\n  "
        + "\n  ".join(offenders[:10])
    )


def test_residency_gap_is_pinned_and_can_only_shrink():
    """`eu_residency` is canonical but not yet required — 3 manifests omit it.

    They are not missing residency: all three declare it as
    `transfers_outside_eu: false`, the deprecated inverse. So closing this gap is
    a rename, not new data — a distinction the two-spelling split was hiding, and
    a good miniature of why the genome exists.

    Pinning the exact list is the difference between a known gap and an invisible
    one. Adding a fourth fails; closing one fails too, and is fixed by editing
    this list down. That asymmetry is deliberate: the count is meant to reach 0.
    """
    known = {"hermes-base", "openclaw-base", "vaultwarden-base"}
    missing = set()
    for m in sorted(PLUGINS.rglob("plugin.yml")):
        block = (yaml.safe_load(m.read_text()) or {}).get("gdpr") or {}
        if "eu_residency" not in block:
            missing.add(m.parent.name)
    assert missing == known, (
        f"the eu_residency exemption set changed: now missing in {sorted(missing)}, "
        f"pinned as {sorted(known)}. If one was fixed, shrink this list; if one was "
        f"added, add the field instead."
    )


def test_residency_fields_never_contradict_each_other():
    """22 manifests carry both spellings. They are inverses; JSON Schema draft-07
    cannot express that, so it is asserted here (and in nos_entity.py)."""
    sys.path.insert(0, str(REPO / "files" / "anatomy"))
    from module_utils import nos_entity  # noqa: PLC0415

    offenders = []
    for m in sorted(PLUGINS.rglob("plugin.yml")):
        block = (yaml.safe_load(m.read_text()) or {}).get("gdpr") or {}
        if block and not nos_entity.residency_is_consistent(block):
            offenders.append(
                f"{m.relative_to(REPO)}: eu_residency={block.get('eu_residency')} "
                f"but transfers_outside_eu={block.get('transfers_outside_eu')}"
            )
    assert not offenders, "residency fields contradict each other:\n  " + "\n  ".join(offenders)


def test_identity_name_pattern_accepts_every_live_plugin_name():
    import re

    pat = re.compile(_facet("identity")["properties"]["name"]["pattern"])
    bad = []
    for m in sorted(PLUGINS.rglob("plugin.yml")):
        name = (yaml.safe_load(m.read_text()) or {}).get("name")
        if name and not pat.match(name):
            bad.append(f"{name} ({m.relative_to(REPO)})")
    assert not bad, f"the identity name pattern rejects live plugin names: {bad}"


# ── regenerate-and-diff ───────────────────────────────────────────────────


def test_generated_artifacts_are_current():
    r = subprocess.run(
        [sys.executable, str(CODEGEN), "--check"], capture_output=True, text=True, cwd=REPO
    )
    assert r.returncode == 0, (
        "generated genome artifacts are stale — run `python3 tools/genome-codegen.py` "
        f"and commit.\n{r.stdout}\n{r.stderr}"
    )


def test_a_hand_edit_of_a_generated_file_is_caught(tmp_path):
    """Proves the drift gate can go red. A gate nobody has seen fail is a hope."""
    target = REPO / "files" / "anatomy" / "module_utils" / "nos_entity.py"
    original = target.read_text()
    try:
        target.write_text(original + "\nHAND_EDITED = True\n")
        r = subprocess.run(
            [sys.executable, str(CODEGEN), "--check"], capture_output=True, text=True, cwd=REPO
        )
        assert r.returncode != 0, "a hand-edited generated artifact passed --check"
        assert "nos_entity.py" in (r.stdout + r.stderr)
    finally:
        target.write_text(original)
