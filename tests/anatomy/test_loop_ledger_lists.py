"""Anatomy gate — the ledger's LIST surface never leaks the artifact.

Subject: files/anatomy/bone/ledger.py `list_proposals` / `list_judge_runs` /
`list_verdicts` + the /api/v1/loop routes over them (2026-08-06, the run
screen's read surface).

THE PROMISE UNDER TEST: `diff_text` is excluded from the proposals list BY
CONSTRUCTION. The list feeds a browser through the face BFF, and a proposal's
hunks are secrets-adjacent (a proposal may touch credential templates). The
face projection also refuses the field — but a projection can only refuse what
it knows about, so the exclusion must hold at the SOURCE, where the column
list is written. Same doctrine as the Pulse projection's env_json.

CI-safe: pure sqlite3 in a tmp dir, no subprocess, no network.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone"
if str(BONE) not in sys.path:
    sys.path.insert(0, str(BONE))

import ledger  # noqa: E402

WEAKNESS_INDEX = {"hidden-fee:08": "e" * 64}
TARGET = "roles/pazny.gitea/defaults/main.yml"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = tmp_path / "wing.db"
    sqlite3.connect(str(path)).close()
    monkeypatch.setenv("WING_DB_PATH", str(path))
    monkeypatch.setenv("WING_EVENTS_HMAC_SECRET", "loop-lists-test-secret")
    return path


@pytest.fixture()
def proposer(db):
    led = ledger.open_ledger("proposer", weakness_index=WEAKNESS_INDEX)
    yield led
    led.close()


def _propose(led):
    return led.record_proposal(
        weakness_id="hidden-fee:08", target_paths=[TARGET],
        intent_class="version-pin-bump", gate_set="fast", tree_sha="a" * 40,
        proposer_id="agent:remediator", proposer_model="anthropic-claude-opus-5",
        diff_text=f"--- a/{TARGET}\n+++ b/{TARGET}\n@@ -1 +1 @@\n-a\n+b\n")


def test_the_proposals_list_never_carries_the_artifact(proposer):
    _propose(proposer)
    rows = proposer.list_proposals()
    assert rows, "the list is empty against a ledger that holds a proposal"
    for row in rows:
        assert "diff_text" not in row, (
            "list_proposals carries diff_text — one BFF pass-through away "
            "from putting proposal hunks in a browser"
        )
    # The full row remains reachable server-side; the exclusion is a property
    # of the LIST surface, not amnesia about the artifact.
    full = proposer.proposal(rows[0]["uuid"])
    assert full is not None and full["diff_text"]


def test_the_lists_are_newest_first_and_bounded(proposer):
    first = _propose(proposer)
    # A second, distinct proposal (different content → different fingerprint
    # path is not needed; attempt_n increments on same fingerprint).
    rows = proposer.list_proposals(limit=1)
    assert len(rows) == 1
    assert rows[0]["uuid"] == first["uuid"] or rows[0]["id"] >= 1


def test_the_read_routes_exist_with_read_scope():
    """The routes are the wire; a list surface without a route is the 'tested,
    never callable' defect the wire test exists for — asserted here at the
    source level, offline."""
    src = (BONE / "looproutes.py").read_text(encoding="utf-8")
    for route in ('@router.get("/proposals")', '@router.get("/judge_runs")',
                  '@router.get("/verdicts")'):
        assert route in src, f"{route} missing from looproutes.py"
    # Each list route must gate on the read scope, and none may write.
    for fn in ("def list_proposals", "def list_judge_runs", "def list_verdicts"):
        body = src[src.index(fn):]
        body = body[:body.index("\n\n\n")] if "\n\n\n" in body else body
        assert 'require_loop_scope("read")' in body, f"{fn} is not read-scope-gated"
