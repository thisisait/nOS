"""The pupil (Iris's desktop window) draws every component the wire can carry.

WHY. The pupil is the second consumer of files/anatomy/contracts/thalamus-shell.yml.
A kind it cannot draw would vanish from the window while the terminal shell still
shows it, which the visibility invariant forbids (cross-repo-contracts.md §4). This
runs Iris's vitest (face/src/lib/iris, which the pupil borrows) over the contract fixture and checks the spec names the pupil.
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
PUPIL = REPO / "files/anatomy/pupil"
FACE = REPO / "files/anatomy/face"
needs_node = pytest.mark.skipif(not shutil.which("npx"), reason="npx runs the pupil's vitest")


def test_the_contract_names_the_pupil_as_a_consumer():
    code = yaml.safe_load(SPEC.read_text(encoding="utf-8"))["consumer"]["code"]
    assert any(p.startswith("files/anatomy/pupil/") for p in code), (
        f"{SPEC.name} consumer.code does not list the pupil: {code}")


@needs_node
def test_pupil_renders_the_fixture():
    assert (PUPIL / "package.json").is_file(), f"no pupil at {PUPIL}"
    assert (FACE / "node_modules").is_dir(), "run `npm ci --ignore-scripts` in files/anatomy/face first"
    r = subprocess.run(["npx", "vitest", "run", "src/lib/iris/fixture.test.ts"], cwd=FACE,
                       capture_output=True, text=True, timeout=600, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


@needs_node
@pytest.mark.parametrize("kind,old,new", [("markdown", "text", "body"), ("list", "items", "entries")])
def test_a_planted_prop_rename_is_named(tmp_path, kind, old, new):
    """Rename one prop in a copy of the fixture; the pupil's vitest must go red naming the kind."""
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    hit = [c["msg"]["component"]["props"] for c in fx["to_shell"]
           if c["msg"].get("component", {}).get("kind") == kind]
    assert hit, f"plant did not apply: no {kind} sample in the fixture"
    hit[0][new] = hit[0].pop(old)
    planted = tmp_path / "fixture.json"
    planted.write_text(json.dumps(fx), encoding="utf-8")
    r = subprocess.run(["npx", "vitest", "run", "src/lib/iris/fixture.test.ts"], cwd=FACE,
                       capture_output=True, text=True, timeout=600, check=False,
                       env={**os.environ, "PUPIL_FIXTURE": str(planted)})
    out = r.stdout + r.stderr
    assert r.returncode != 0, "vitest stayed green on a renamed prop:\n" + out[-2000:]
    assert f"{kind} props" in out, "vitest went red without naming the kind:\n" + out[-4000:]
