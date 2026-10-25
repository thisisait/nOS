"""The committed Wing contract artifacts are what Wing's exporters print, checked where the edit is made.

MEASURED 2026-10-25: two branches hand-edited files/anatomy/contracts/wing.openapi.yml (403s on the
Pulse routes, a GET /pulse_runs entry) instead of teaching the exporter; every local lane was green
and dev's CI went red on "Contracts drift check" twice. This is that check's twin for Wing, as
test_the_bone_contract_is_current is for Bone: same scripts, same files, so it can only disagree
with CI about WHEN. The fix for a red here is the exporter or a presenter docblock, never the YAML.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
CONTRACTS = REPO / "files/anatomy/contracts"
EXPORTS = [("export-openapi.php", "wing.openapi.yml"), ("export-schema.php", "wing.db-schema.sql")]


@pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing's exporters")
@pytest.mark.parametrize("script,artifact", EXPORTS)
def test_the_committed_artifact_is_what_the_exporter_prints(tmp_path, script, artifact):
    out = tmp_path / artifact
    r = subprocess.run(["php", str(WING / "bin" / script), f"--output={out}"],
                       capture_output=True, text=True, timeout=120, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.read_text(encoding="utf-8") == (CONTRACTS / artifact).read_text(encoding="utf-8"), (
        f"{artifact} drifted from bin/{script}: regenerate with "
        f"`php files/anatomy/wing/bin/{script} --output=files/anatomy/contracts/{artifact}` "
        "and teach the exporter or the presenter docblock what the hand edit wanted")
