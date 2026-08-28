"""A declared-but-disabled intent class is refused, and the refusal says WHERE
the switch is.

WHY THIS SHAPE (Q6 seam, 2026-08-29). The surface needs a word for a proposal
that changes the apparatus a run is judged BY — `harness` — before the engine
is taught to accept one. Two wrong ways to get there: leave it out of the enum,
and the first harness proposal arrives as `unknown-intent` alongside every
typo, indistinguishable from a misspelling; or special-case it with a branch,
and the loop grows a second refusal mechanism to keep in step with the first.
It joins the SAME closed enum and one more frozenset beside
`OPERATOR_REQUIRED_INTENTS`, and the refusal names the toggle that will one day
lift it — because a refusal an operator cannot act on produces a retry, and a
retry is what the docs/idea/11-agentic-loop-contract.md §4 ceiling spends.

WHAT THIS GATE READS. The real router, the real ledger, a real POST over the
wire, against a temp wing.db. Not the enum's membership — a test that asserted
`"harness" in DISABLED_INTENTS` would pass while the guard consulting the set
was deleted. The claim under test is the 409, its reason, and the toggle path
in its detail.

THE OTHER HALF, deliberately: the ledger must NOT read the live toggle this
cycle. A ledger wired to a config row nothing writes is a half-armed switch,
and the estate's rule is that arming is a separate, deliberate act. So the
refusal is unconditional here, and that unconditionality is asserted.

CI-safe: FastAPI TestClient + tmp sqlite. No live estate, no network.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone"
if str(BONE) not in sys.path:
    sys.path.insert(0, str(BONE))

import ledger  # noqa: E402
import looproutes  # noqa: E402

PROPOSE_TOKEN = "p" * 64
WEAKNESS_INDEX = {"hidden-fee:08": "sha-08"}
ALLOWED = "roles/pazny.gitea/defaults/main.yml"

BODY = dict(
    weakness_id="hidden-fee:08",
    target_paths=[ALLOWED],
    gate_set="repo",
    tree_sha="a" * 40,
    proposer_id="agent:proposer",
    diff_text=(f"diff --git a/{ALLOWED} b/{ALLOWED}\n"
               f"--- a/{ALLOWED}\n+++ b/{ALLOWED}\n"
               "@@ -1 +1 @@\n-a\n+b\n"),
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    path = tmp_path / "wing.db"
    sqlite3.connect(str(path)).close()
    monkeypatch.setenv("WING_DB_PATH", str(path))
    monkeypatch.setenv("WING_EVENTS_HMAC_SECRET", "disabled-intent-test-secret")
    monkeypatch.setenv("BONE_LOOP_PROPOSE_TOKEN", PROPOSE_TOKEN)
    monkeypatch.setattr(ledger, "default_weakness_index",
                        lambda: dict(WEAKNESS_INDEX))
    app = FastAPI()
    app.include_router(looproutes.router)
    return TestClient(app), path


def post(client, **over):
    tc, _ = client
    return tc.post("/api/v1/loop/proposals", json={**BODY, **over},
                   headers={"Authorization": f"Bearer {PROPOSE_TOKEN}"})


def test_the_enum_still_admits_the_word(client):
    """ANTI-VACUITY, in the direction that matters: `harness` must not be
    refused as a typo. If it left the enum, the test below would still pass —
    on the wrong 409 — and the surface would have no way to say the word."""
    r = post(client, intent_class="harness")
    detail = r.json()["detail"]
    assert detail["reason"] != "unknown-intent", (
        "`harness` fell out of INTENT_CLASSES — a disabled kind and a "
        "misspelling now refuse identically, which is the state this seam "
        "exists to avoid"
    )


def test_a_harness_proposal_is_refused_by_the_real_route(client):
    r = post(client, intent_class="harness")
    assert r.status_code == 409, (
        f"got {r.status_code}: a disabled intent must be refused, not "
        f"recorded — {r.text[:300]}"
    )
    assert r.json()["detail"]["reason"] == "intent-disabled"


def test_the_refusal_names_the_toggle_and_its_table(client):
    detail = post(client, intent_class="harness").json()["detail"]["detail"]
    assert "harness_proposals_enabled" in detail, (
        f"the refusal must name the toggle by its exact key; got {detail!r}"
    )
    assert "KEAP config table" in detail, (
        f"the refusal must name WHERE the toggle lives — a key with no table "
        f"is a name an operator has to grep for; got {detail!r}"
    )


def test_nothing_was_recorded(client):
    """A refusal that still wrote the row would pass every assertion above."""
    post(client, intent_class="harness")
    _, path = client
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM loop_proposals WHERE intent_class = 'harness'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 0, "a refused proposal was persisted anyway"


def test_an_enabled_intent_on_the_same_body_is_accepted(client):
    """The control. Without it, every assertion above is satisfied by a route
    that refuses everything — including for the budget, the weakness index or
    a missing token."""
    r = post(client, intent_class="config-fix")
    assert r.status_code == 201, (
        f"the same body under an ENABLED intent must be recorded; got "
        f"{r.status_code} {r.text[:300]} — the refusals above prove nothing "
        "if this path is broken too"
    )


def test_the_refusal_does_not_depend_on_a_toggle_being_readable(client, monkeypatch):
    """This cycle's contract, stated as a test: the ledger holds NO reader for
    the switch. Wiring one is the later cycle's single change; until then a
    harness proposal is refused on every host, configured or not."""
    monkeypatch.setenv("HARNESS_PROPOSALS_ENABLED", "true")
    monkeypatch.setenv("KEAP_HARNESS_PROPOSALS_ENABLED", "1")
    r = post(client, intent_class="harness")
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "intent-disabled"
