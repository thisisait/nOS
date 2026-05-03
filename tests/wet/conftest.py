"""Wet-test pytest fixtures.

These tests assert post-blank state on the operator's box. They're
NOT unit tests — they read live artifacts (~/wing/wing.db, ~/.nos/
events/playbook.jsonl, state/smoke-catalog.runtime.yml) and only run
when those exist. On CI / fresh worktrees the artifacts are absent
and every test in this dir skips cleanly.

Toggle: set NOS_WET=1 to make missing-artifact a hard FAIL instead
of a SKIP. Useful for the operator's own verification run after a
blank — `NOS_WET=1 pytest tests/wet -v` will redline if the blank
didn't produce the expected state, instead of silently passing.
"""

from __future__ import annotations

import os
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
HOME = pathlib.Path.home()

# Wing's SQLite lives at ~/wing/app/data/wing.db on the host (the wing
# container bind-mounts ~/wing/app at the same path inside, so host and
# container see identical paths). Set NOS_WING_DB to override for
# operators with non-default wing_app_dir.
WING_DB = pathlib.Path(
    os.environ.get("NOS_WING_DB", HOME / "wing" / "app" / "data" / "wing.db")
)
EVENTS_JSONL = HOME / ".nos" / "events" / "playbook.jsonl"
SMOKE_CATALOG = REPO_ROOT / "state" / "smoke-catalog.runtime.yml"

PILOTS = ("twofauth", "roundcube", "documenso")
APP_IDS = tuple(f"app_{p}" for p in PILOTS)

STRICT = os.environ.get("NOS_WET") == "1"


def _require(path: pathlib.Path, label: str) -> pathlib.Path:
    """Skip (or fail under NOS_WET=1) if a wet artifact is missing."""
    if not path.exists():
        msg = f"{label} not found at {path} — blank not run yet?"
        if STRICT:
            pytest.fail(msg)
        pytest.skip(msg)
    return path


@pytest.fixture
def wing_db() -> pathlib.Path:
    return _require(WING_DB, "Wing SQLite DB")


@pytest.fixture
def events_jsonl() -> pathlib.Path:
    return _require(EVENTS_JSONL, "Bone events JSONL")


@pytest.fixture
def smoke_catalog() -> pathlib.Path:
    return _require(SMOKE_CATALOG, "smoke-catalog.runtime.yml")


@pytest.fixture(params=PILOTS, ids=list(PILOTS))
def pilot(request) -> str:
    return request.param
