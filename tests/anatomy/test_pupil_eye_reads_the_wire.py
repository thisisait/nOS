"""The pupil's eye shows what the thalamus says it is doing, and nothing it guessed.

WHY. The eye is the person's only cue that Iris is working, waiting on them, or gone.
A state the wire did not name (a "thinking" assumed on send) or an approval hidden
behind a busy look misleads exactly when it matters. This runs the pupil's eye vitest:
the reducer over wire `activity` + link + local typing, and the drawn label.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

PUPIL = pathlib.Path(__file__).resolve().parents[2] / "files/anatomy/pupil"


@pytest.mark.skipif(not shutil.which("npx"), reason="npx runs the pupil's vitest")
def test_pupil_eye_follows_the_wire():
    assert (PUPIL / "node_modules").is_dir(), "run `npm ci` in files/anatomy/pupil first"
    r = subprocess.run(["npx", "vitest", "run", "src/eye.test.ts"], cwd=PUPIL,
                       capture_output=True, text=True, timeout=600, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
