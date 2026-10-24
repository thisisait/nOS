"""estate-status reports the checkout the converge runs from: its ref and its drift.

Row estate-dev-split step 4: since 2026-10-23 the estate converges from
~/.nos/estate at the ref `nos update` recorded (git config nos.estate-ref), and
the only repo estate-status showed was the dev tree, which no longer answers
"what will the next converge run".
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "estate-status.py"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t",
                        "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _estate(tmp: Path) -> Path:
    origin, est = tmp / "origin", tmp / "estate"
    _git(tmp, "init", "-q", "-b", "dev", str(origin))
    _git(origin, "commit", "-q", "--allow-empty", "-m", "one")
    _git(tmp, "clone", "-q", str(origin), str(est))
    _git(est, "checkout", "-q", "-B", "estate", "origin/dev")
    _git(est, "config", "nos.estate-ref", "dev")
    _git(origin, "commit", "-q", "--allow-empty", "-m", "two")
    return est


def _run(est: Path) -> str:
    return subprocess.run([sys.executable, str(TOOL)], capture_output=True, text=True, timeout=180,
                          env={**os.environ, "NOS_ESTATE_DIR": str(est)}).stdout


def test_the_estate_line_names_its_ref_and_what_nos_update_would_move(tmp_path):
    out = _run(_estate(tmp_path))
    line = next((ln for ln in out.splitlines() if "estate @dev" in ln), None)
    assert line, f"no estate line:\n{out}"
    assert "1 behind origin/dev" in line and "nos update" in line, line


def test_no_estate_is_unknown_not_green(tmp_path):
    out = _run(tmp_path / "none")
    assert any("estate" in ln and "UNKNOWN" in ln for ln in out.splitlines()) or "estate-adopt" in out, out
