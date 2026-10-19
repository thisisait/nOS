"""A loop run leaves the source checkout clean (roadmap pipeline-exercise-writes-checkout).

The repo is not the running system: a nightly run that rewrote committed
fixtures dirtied every host's checkout and turned a fixture into that host's
run record. This runs the real main() — only the VLM cycle and the readiness
hold are stubbed — from a throwaway git worktree under a temp HOME.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
pytest.importorskip("PIL.Image", reason="Pillow not installed")
LOOP_REL = "tools/loops/pipeline-exercise.py"


def _git(*args, cwd=REPO) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout


@pytest.fixture
def checkout(tmp_path):
    wt = tmp_path / "wt"
    _git("worktree", "add", "-q", "--detach", str(wt), "HEAD")
    for rel in (LOOP_REL, "tools/loops/vision-bench.py"):  # the code under test, not HEAD's
        shutil.copy2(REPO / rel, wt / rel)
    try:
        yield wt
    finally:
        _git("worktree", "remove", "--force", str(wt))


def test_a_run_writes_under_the_runtime_dir_not_the_checkout(checkout, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("NOS_LOOP_STATE_DIR", raising=False)
    monkeypatch.delenv("STATE_DIR", raising=False)
    before = _git("status", "--porcelain", cwd=checkout)

    spec = importlib.util.spec_from_file_location("pe_clean", checkout / LOOP_REL)
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    monkeypatch.setattr(loop.job_readiness, "hold", lambda *a, **k: 0)
    monkeypatch.setattr(loop, "cycle", lambda n, plan: {"n": n, **plan, "ok": True})

    assert loop.main(["--cycles", "2"]) == 0
    assert _git("status", "--porcelain", cwd=checkout) == before, "the run dirtied the checkout"
    runtime = home / ".nos" / "loops" / "pipeline-exercise"
    cov = (runtime / "coverage.json").read_text(encoding="utf-8")
    assert '"cycles"' in (runtime / "last-run.json").read_text(encoding="utf-8")
    # the committed matrix is the seed, so a fresh host does not restart at zero
    seed = (checkout / "state/fixtures/pipeline-exercise/coverage.json").read_text(encoding="utf-8")
    assert sum(json.loads(cov).values()) == sum(json.loads(seed).values()) + 2
    assert str(loop.BENCH.REPORT_DIR).startswith(str(home / ".nos")), "vision-bench writes the checkout"
