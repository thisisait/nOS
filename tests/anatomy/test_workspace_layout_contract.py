"""The pupil's workspace layout: one spec, one fixture, decoded by the pupil's Rust.

WHY. The layout is the one file the pupil writes on the person's Mac, and the face
is to read the same format later. A layout the decoder accepts past its caps (a
13th workspace, a widget narrower than 80 px, a spec with two keys, a parent cycle)
would be saved and restored as if valid; one it refuses must be refused on load,
never half-drawn. A v2 file a person already has must load as v3, the same in Rust
and in TypeScript, or one shell would draw it elsewhere. This runs `cargo test
--no-default-features workspace` in the pupil crate, whose test decodes every
fixture sample, re-encodes it to itself, refuses every `refused` sample and
migrates every `migrated` v2 sample to its v3 (genui I5h; canvas v3 2026-10-18).
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
SPEC = REPO / "files/anatomy/contracts/workspace-layout.yml"
FIXTURE = REPO / "files/anatomy/contracts/workspace-layout.fixture.json"
CRATE = REPO / "files/anatomy/pupil/src-tauri"
# The cases the definition names; the fixture may hold more, never fewer.
MUST_REFUSE = {"a 13th workspace", "a widget w: 79", "an unknown key", "a spec with two keys", "5 lens conditions",
               "a heading with a spec", "a parent that names no workspace", "a parent cycle", "nesting 7 deep"}


def _spec() -> dict:
    return yaml.safe_load(SPEC.read_text(encoding="utf-8"))


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_spec_names_this_fixture_and_these_files():
    spec = _spec()
    assert spec["version"] == _fixture()["version"] == 3
    assert REPO / spec["fixture"] == FIXTURE
    for side in ("producer", "consumer"):
        for path in spec[side]["code"]:
            assert (REPO / path).is_file(), f"{side} names a missing file: {path}"
    names = {pathlib.PurePath(p).name for p in spec["consumer"]["code"]}
    assert {"workspace.rs", "workspace.test.ts"} <= names, names


def test_the_fixture_holds_the_named_refusals():
    fx = _fixture()
    assert fx["samples"], "no sample layout"
    missing = MUST_REFUSE - {c["case"] for c in fx["refused"]}
    assert not missing, f"fixture lacks refused cases: {sorted(missing)}"


def test_the_fixture_migrates_v2_files_and_draws_every_kind():
    fx = _fixture()
    assert fx["migrated"] and all(c["v2"]["version"] == 2 and c["v3"]["version"] == 3 for c in fx["migrated"])
    kinds = {i["kind"] for c in fx["samples"] for s in c["layout"]["workspaces"] for i in s["items"]}
    assert kinds == {"widget", "heading", "frame"}, kinds
    spaces = [s for c in fx["samples"] for s in c["layout"]["workspaces"]]
    assert any("view" in s for s in spaces) and any("parent" in s for s in spaces), "no sample keeps a view or a parent"


@pytest.mark.skipif(not shutil.which("cargo"), reason="cargo runs the pupil's decoder")
def test_the_pupil_decodes_and_refuses_the_fixture():
    r = subprocess.run(["cargo", "test", "--locked", "-p", "nos-pupil", "--no-default-features", "workspace"],
                       cwd=CRATE, capture_output=True, text=True, timeout=1800, check=False)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-6000:]
    assert re.search(r"workspace::\S*fixture\S* \.\.\. ok", out), "the fixture test did not run:\n" + out[-2000:]
