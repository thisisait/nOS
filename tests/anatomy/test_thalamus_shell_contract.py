"""The thalamus<->shell wire: one Rust crate, one fixture, decoded both ways.

WHY. The shell renders only what the wire names, and the thalamus acts only
on what the wire names. A component the shell cannot decode must surface
as `refused`, never vanish (ssot/doctrine/cross-repo-contracts.md §4
visibility). This runs nos-contract's `wire_fixture` example on
files/anatomy/contracts/thalamus-shell.fixture.json and checks every sample
re-encodes to itself and every refused line is refused. The refused samples
also pin ssot/doctrine/generative-ui.md §2 for Iris: a source carries no URL and
no name of the model's, a model's step is never done or failed, and a callout
carries no marker field (the shell draws "Iris says").
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
SPEC = REPO / "files/anatomy/contracts/thalamus-shell.yml"
FIXTURE = REPO / "files/anatomy/contracts/thalamus-shell.fixture.json"
CRATE = REPO / "files/anatomy/thalamus/contract"
needs_cargo = pytest.mark.skipif(not shutil.which("cargo"), reason="cargo runs the contract crate")


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _spec() -> dict:
    return yaml.safe_load(SPEC.read_text(encoding="utf-8"))


def _rust(crate: pathlib.Path, target: pathlib.Path) -> dict:
    r = subprocess.run(["cargo", "run", "--quiet", "--manifest-path", str(crate / "Cargo.toml"),
                        "--example", "wire_fixture", "--", str(FIXTURE)],
                       capture_output=True, text=True, timeout=600, check=False,
                       env={**os.environ, "CARGO_TARGET_DIR": str(target)})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _drift(out: dict) -> list[str]:
    fx, bad = _fixture(), []
    for side in ("to_thalamus", "to_shell"):
        for case, got in zip(fx[side], out[side]):
            if got != case["msg"]:
                bad.append(f"{side} {case['case']}: want {case['msg']!r}, got {got!r}")
    for case, got in zip(fx["refused"], out["refused"]):
        if got.get("t") != "refused" or not got.get("reason"):
            bad.append(f"refused {case['case']}: decoded to {got!r}")
    for case, got in zip(fx["refused_to_thalamus"], out["refused_to_thalamus"]):
        if "error" not in got:
            bad.append(f"refused_to_thalamus {case['case']}: accepted as {got!r}")
    return bad


def test_the_spec_names_this_fixture_and_these_files():
    spec = _spec()
    assert spec["contract_version"] == _fixture()["contract_version"]
    assert REPO / spec["fixture"] == FIXTURE
    for side in ("producer", "consumer"):
        for path in spec[side]["code"]:
            assert (REPO / path).is_file(), f"{side} names a missing file: {path}"


def test_the_fixture_holds_every_variant_and_component():
    """Removal: a variant with no sample could leave the enum unseen."""
    spec, fx = _spec(), _fixture()
    for side in ("to_thalamus", "to_shell"):
        seen = {c["msg"]["t"] for c in fx[side]}
        assert seen == set(spec["wire"][side]), f"{side}: fixture {sorted(seen)} vs spec {spec['wire'][side]}"
    kinds = {c["msg"]["component"]["kind"] for c in fx["to_shell"] if "component" in c["msg"]}
    assert kinds == set(spec["components"]["vocabulary"]), f"components: fixture {sorted(kinds)}"


@needs_cargo
def test_the_crate_round_trips_and_refuses_the_fixture(tmp_path_factory):
    bad = _drift(_rust(CRATE, tmp_path_factory.getbasetemp() / "cargo-target"))
    assert not bad, "nos-contract wire drifted from the contract:\n  " + "\n  ".join(bad)


@needs_cargo
def test_a_planted_divergence_in_the_wire_goes_red(tmp_path, tmp_path_factory):
    """Rename one component field in a copy of the crate; the gate must name the case."""
    crate = tmp_path / "contract"
    shutil.copytree(CRATE, crate, ignore=shutil.ignore_patterns("target"))
    src = crate / "src" / "renderers.rs"
    planted = src.read_text(encoding="utf-8").replace(
        "pub projected: bool", '#[serde(rename = "projection")] pub projected: bool')
    assert planted != src.read_text(encoding="utf-8"), "plant did not apply"
    src.write_text(planted, encoding="utf-8")
    bad = _drift(_rust(crate, tmp_path_factory.getbasetemp() / "cargo-target"))
    assert any("search results" in b for b in bad), f"Rust plant went unseen: {bad}"
