"""The face Iris decides an approval under the terminal shell's invariants.

WHY. serve.rs refuses a decision for an id it is not waiting on, but it cannot know
whether the person saw the whole edit, and it does not refuse a turn while one waits;
those live in the shell (shell.rs:30-34, 157-161, 173-184, 219-231). This runs the
approval vitest (reducer + card, face/src/lib/iris). The pupil's bridge test of the
same rules retired with the pupil (2026-11-08): the face sends through the relay, and
serve's own refusals are cargo-tested in tests/serve.rs.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

FACE = pathlib.Path(__file__).resolve().parents[2] / "files/anatomy/face"


@pytest.mark.skipif(not shutil.which("npx"), reason="npx runs the face's vitest")
def test_iris_approval_queue_holds_the_shell_invariants():
    assert (FACE / "node_modules").is_dir(), "run `npm ci --ignore-scripts` in files/anatomy/face first"
    r = subprocess.run(["npx", "vitest", "run", "src/lib/iris/approvals.test.ts"], cwd=FACE,
                       capture_output=True, text=True, timeout=600, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
