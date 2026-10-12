"""The pupil (Iris's desktop window) draws every component the wire can carry.

WHY. The pupil is the second consumer of files/anatomy/contracts/thalamus-shell.yml.
A kind it cannot draw would vanish from the window while the terminal shell still
shows it, which the visibility invariant forbids (cross-repo-contracts.md §4). This
runs the pupil's vitest over the contract fixture and checks the spec names the pupil.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
SPEC = REPO / "files/anatomy/contracts/thalamus-shell.yml"
PUPIL = REPO / "files/anatomy/pupil"
needs_node = pytest.mark.skipif(not shutil.which("npx"), reason="npx runs the pupil's vitest")


def test_the_contract_names_the_pupil_as_a_consumer():
    code = yaml.safe_load(SPEC.read_text(encoding="utf-8"))["consumer"]["code"]
    assert any(p.startswith("files/anatomy/pupil/") for p in code), (
        f"{SPEC.name} consumer.code does not list the pupil: {code}")


@needs_node
def test_pupil_renders_the_fixture():
    assert (PUPIL / "package.json").is_file(), f"no pupil at {PUPIL}"
    assert (PUPIL / "node_modules").is_dir(), "run `npm ci` in files/anatomy/pupil first"
    r = subprocess.run(["npx", "vitest", "run", "src/fixture.test.ts"], cwd=PUPIL,
                       capture_output=True, text=True, timeout=600, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
