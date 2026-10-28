"""nOS.app reads the medulla's state as the contract says (joint app <-> medulla, ssot/doctrine/gates.md §7).

WHY. The app's Swift decoder and the thalamus's EstateState are two representations of one
wire message. This decodes the fixture's to_shell `state` samples with the app's own decoder,
so a renamed or dropped field fails here instead of showing as off in the menu bar.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
APP = REPO / "files/anatomy/thalamus/app"
FIXTURE = REPO / "files/anatomy/contracts/thalamus-shell.fixture.json"


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("swift"), reason="SwiftUI builds on macOS only")
def test_the_app_decodes_every_contract_state_sample():
    r = subprocess.run(["swift", "run", "-q", "state-check", str(FIXTURE)], cwd=APP,
                       capture_output=True, text=True, timeout=900, check=False)
    assert r.returncode == 0 and r.stdout.startswith("ok "), (r.stdout + r.stderr)[-4000:]
