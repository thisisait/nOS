"""nOS.app reads the medulla's state as the contract says (joint app <-> medulla, ssot/doctrine/gates.md §7).

WHY. The app's Swift decoder and the thalamus's EstateState are two representations of one
wire message. This decodes the fixture's to_shell `state` samples with the app's own decoder,
so a renamed or dropped field fails here instead of showing as off in the menu bar.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
APP = REPO / "files/anatomy/thalamus/app"
FIXTURE = REPO / "files/anatomy/contracts/thalamus-shell.fixture.json"


def _state_check() -> subprocess.CompletedProcess:
    return subprocess.run(["swift", "run", "-q", "state-check", str(FIXTURE)], cwd=APP,
                          capture_output=True, text=True, timeout=900, check=False)


darwin = pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("swift"), reason="SwiftUI builds on macOS only")


@darwin
def test_the_app_decodes_every_contract_state_sample():
    r = _state_check()
    assert r.returncode == 0 and r.stdout.startswith("ok "), (r.stdout + r.stderr)[-4000:]


@darwin
def test_nos_app_speaks_setting():
    """The app's `setting` line is the fixture's, null kept (an unpause is {job: null}); settings and act decode."""
    r = _state_check()
    m = re.match(r"ok \d+ states (\d+) settings", r.stdout)
    assert r.returncode == 0 and m and int(m[1]) >= 4, (r.stdout + r.stderr)[-4000:]
