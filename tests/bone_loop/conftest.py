"""Fixtures for the Bone weakness reader (files/anatomy/bone/weaknesses.py).

Loads the module directly (same importlib trick as tests/bone_vfs) and builds a
SYNTHETIC repo per test: a real `git init` with real commits, plus the four
file-backed sources. Nothing here reads the operator's own repo — a reader test
that asserted against the live `remediation-queue.json` would go red every time
the nightly scan ran, which is the opposite of a gate.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from .fakes import FEE_FILE, FEE_FILES, FEES_README, JUDGE_TOKEN, PROPOSE_TOKEN, make_queue, make_scan_state

ROOT = Path(__file__).resolve().parents[2]
BONE_DIR = ROOT / "files" / "anatomy" / "bone"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def loopauth():
    return _load("loopauth", BONE_DIR / "loopauth.py")


@pytest.fixture(scope="session")
def judges():
    """Preloaded because `weaknesses` imports it flat, the way Bone runs.

    Until 2026-08-13 nothing here loaded it, and this directory still passed —
    `tests/anatomy/test_loop_repo_root_is_asked.py` imports `judges` into
    `sys.modules` and sorts earlier, so the whole suite worked and
    `pytest tests/bone_loop` alone raised 42 ModuleNotFoundErrors. A fixture
    that depends on another directory having run first is not a fixture.
    """
    return _load("judges", BONE_DIR / "judges.py")


@pytest.fixture(scope="session")
def weaknesses(loopauth, judges):  # noqa: ARG001 — load order: weaknesses imports both
    return _load("weaknesses", BONE_DIR / "weaknesses.py")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


@pytest.fixture
def state(tmp_path):
    """The runtime side-car (~/.nos stand-in), in its HEALTHY shape.

    Every source present and reporting `ok`, so the base fixture's
    `complete: true` is a real baseline. A test that wants a degraded source
    removes or corrupts it explicitly — the reverse (a fixture that is already
    half-broken) makes `complete: false` meaningless.
    """
    d = tmp_path / "state"
    (d / "events").mkdir(parents=True, exist_ok=True)
    (d / "cortex-corpus-diff.json").write_text(
        json.dumps({
            "version": 2,
            "agreeStreak": 6,
            "disagreements": 0,
            "halted": False,
            "nights": [{
                "at": "2026-08-02T05:33:24+00:00",
                "result": "agree",
                "clauses": {"fs ids": True, "taxonomy": True},
            }],
        })
    )
    return d


@pytest.fixture(autouse=True)
def prometheus(tmp_path, monkeypatch):
    """Serve the alerts endpoint from disk, so no test reads the live estate.

    MEASURED 2026-08-13: `test_severity_is_gated_on_pending_status` asserted
    `counts['critical'] == 0` for a fixture holding one pending HIGH, and got 1
    — from `NosCriticalCveFoundCritical`, firing on the operator's own
    Prometheus since 06:12 that morning. The synthetic repo above is careful to
    read nothing of the operator's; the alert source reached straight past it to
    127.0.0.1:9090. A gate that goes red because the estate it guards has a
    problem cannot be told apart from one that found a bug in itself.

    `urllib` opens `file://`, and the reader appends `/api/v1/alerts` to
    whatever base it is given — so a directory IS the stub. Empty and firing
    nothing, which is the neutral baseline the `state` fixture aims for; a test
    wanting alerts overwrites the file.
    """
    endpoint = tmp_path / "prom" / "api" / "v1"
    endpoint.mkdir(parents=True, exist_ok=True)
    (endpoint / "alerts").write_text(
        json.dumps({"status": "success", "data": {"alerts": []}})
    )
    monkeypatch.setenv("PROMETHEUS_URL", (tmp_path / "prom").as_uri())
    return endpoint / "alerts"


@pytest.fixture
def repo(tmp_path, monkeypatch, state, weaknesses):  # noqa: ARG001
    """A committed synthetic repo with every file-backed source present."""
    repo = tmp_path / "repo"
    (repo / "docs" / "llm" / "security").mkdir(parents=True)
    (repo / "docs" / "hidden_fees").mkdir(parents=True)

    (repo / "docs" / "llm" / "security" / "remediation-queue.json").write_text(
        json.dumps(make_queue(pending=[("HIGH", "gitea"), ("MEDIUM", "miniflux")], resolved=3))
    )
    (repo / "docs" / "llm" / "security" / "scan-state.json").write_text(
        json.dumps(make_scan_state())
    )
    (repo / "docs" / "hidden_fees" / "README.md").write_text(FEES_README)
    for slug, body in FEE_FILES:
        (repo / "docs" / "hidden_fees" / slug).write_text(
            FEE_FILE.format(slug=slug, body=body)
        )

    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")

    monkeypatch.setenv("NOS_LOOP_REPO_ROOT", str(repo))
    monkeypatch.setenv("NOS_LOOP_STATE_DIR", str(state))
    monkeypatch.setenv("BONE_LOOP_PROPOSE_TOKEN", PROPOSE_TOKEN)
    monkeypatch.setenv("BONE_LOOP_JUDGE_TOKEN", JUDGE_TOKEN)
    return repo


@pytest.fixture
def client(repo, weaknesses):  # noqa: ARG001
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    app = FastAPI()
    app.include_router(weaknesses.router)
    return TestClient(app)
