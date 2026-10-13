"""Every thalamus and pupil test runs in CI, not only the ones a gate happened to name.

WHY. CI runs pytest, not cargo or vitest. The older lanes reach `--test serve`,
`--test binding`, `cargo test ledger` and three vitest files by name, so
tests/iris_genui.rs, tests/shell.rs, tree.test.ts and every new test file ran on the
operator's Mac and nowhere else (measured 2026-10-13). This runs each
crate's whole `cargo test --locked` and a plain `npx vitest run`.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
ANATOMY = REPO / "files/anatomy"
PUPIL = ANATOMY / "pupil"
# Tauri links webkit2gtk on Linux, which the CI image does not carry: the bridge lib builds without it.
CRATES = {
    "contract": (ANATOMY / "thalamus/contract", []),
    "thalamus": (ANATOMY / "thalamus/thalamus", []),
    "pupil bridge": (PUPIL / "src-tauri", ["--no-default-features"]),
}


@pytest.mark.skipif(not shutil.which("cargo"), reason="cargo runs the crates' tests")
@pytest.mark.parametrize("name", sorted(CRATES))
def test_every_cargo_target_runs(name):
    crate, extra = CRATES[name]
    r = subprocess.run(["cargo", "test", "--locked", *extra], cwd=crate,
                       capture_output=True, text=True, timeout=1800, check=False)
    out = r.stdout + r.stderr
    assert r.returncode == 0, f"{name}: cargo test failed\n" + out[-6000:]
    ran = sum(int(n) for n in re.findall(r"test result: ok\. (\d+) passed", out))
    assert ran > 0, f"{name}: cargo test ran no test\n" + out[-2000:]


@pytest.mark.skipif(not shutil.which("npx"), reason="npx runs the pupil's vitest")
def test_every_pupil_vitest_file_runs():
    assert (PUPIL / "node_modules").is_dir(), "run `npm ci --ignore-scripts` in files/anatomy/pupil first"
    r = subprocess.run(["npx", "vitest", "run"], cwd=PUPIL, capture_output=True, text=True, timeout=900, check=False)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-6000:]
    files = len(list((PUPIL / "src").rglob("*.test.ts")))
    got = re.search(r"Test Files\s+(\d+) passed \((\d+)\)", re.sub(r"\x1b\[[0-9;]*m", "", out))
    assert got and int(got[1]) == int(got[2]) == files, f"vitest ran {got and got[0]!r}, src has {files} test files\n" + out[-2000:]
