"""The pupil decides an approval under the terminal shell's invariants.

WHY. serve.rs refuses a decision for an id it is not waiting on, but it cannot know
whether the person saw the whole edit, and it does not refuse a turn while one waits;
those live in the shell (shell.rs:30-34, 157-161, 173-184, 219-231). This runs the
approval vitest (reducer + card, face/src/lib/iris since the pupil borrows them) and the bridge's cargo test of the same rules.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

PUPIL = pathlib.Path(__file__).resolve().parents[2] / "files/anatomy/pupil"
FACE = PUPIL.parent / "face"  # Iris's components and their tests live in face/src/lib/iris


@pytest.mark.skipif(not shutil.which("npx"), reason="npx runs the pupil's vitest")
def test_pupil_approval_queue_holds_the_shell_invariants():
    assert (FACE / "node_modules").is_dir(), "run `npm ci --ignore-scripts` in files/anatomy/face first"
    r = subprocess.run(["npx", "vitest", "run", "src/lib/iris/approvals.test.ts"], cwd=FACE,
                       capture_output=True, text=True, timeout=600, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


# Tauri links webkit2gtk on Linux, which the CI image does not carry: the bridge builds without it.
@pytest.mark.skipif(not shutil.which("cargo"), reason="cargo builds the bridge")
def test_pupil_bridge_refuses_what_the_shell_would_not_send():
    r = subprocess.run(["cargo", "test", "--locked", "--no-default-features", "--lib", "pending"], cwd=PUPIL / "src-tauri",
                       capture_output=True, text=True, timeout=1200, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    assert " 0 passed" not in r.stdout, "no bridge test matched `pending`"
