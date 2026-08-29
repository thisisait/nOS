"""The scheduler's run, the agent's session and the ledger's rows are one key.

MEASURED 2026-08-29 on the live wing.db:

    events          4 712 / 380 902  carry actor_action_id
    agent_sessions     54 /      55  join to events by it
    pulse_runs          0 /  56 051  carry actor_action_id

`pulse_runs.actor_action_id` is declared in the schema — *"A10: UUID grouping
start/finish events with this run"* — and `PulseRepository::recordStart` has
accepted it since 2026-05-08. The daemon's `post_run_start` never sent one, so
it was NULL on every row that has ever existed.

The consequence is the whole point of the lineage: **a nightly job could not be
traced to the session it started, or to the rows that session wrote.** The agent
half worked; the scheduler half was severed, and a severed join looks exactly
like a run with nothing to show.

THE KEY IS THE RUN'S OWN UUID, not a new one. `run_id` is already a uuid4 and is
already handed to the child as `PULSE_RUN_ID` (that handoff was itself a fix, on
2026-08-13, for the same class of gap). So:

    pulse_runs.run_id == pulse_runs.actor_action_id
                      == agent_sessions.uuid == events.actor_action_id

and one `SELECT ... WHERE actor_action_id = ?` reconstructs scheduler → agent →
ledger. Minting a second id would have given the join a key nothing else could
produce, which is how the column got here in the first place.

Retro-verified 2026-08-29 against each of the three edits removed in turn.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
DAEMON = REPO / "files/anatomy/pulse/pulse/daemon.py"
CLIENT = REPO / "files/anatomy/pulse/pulse/wing_client.py"
RUNNER = REPO / "tools/run-agent.sh"
REPOSITORY = REPO / "files/anatomy/wing/app/Model/PulseRepository.php"


def _call(src: str) -> str:
    """The daemon's run-start call, argument list only.

    Sliced rather than regexed: a non-greedy a non-greedy paren match stops at the first
    close paren, which here belongs to `_now_iso()` — the first draft of this
    gate failed against a correct daemon for that reason.
    """
    i = src.index("self.wing.post_run_start(")
    depth, j = 0, i + len("self.wing.post_run_start")
    for j in range(j, len(src)):
        if src[j] == "(":
            depth += 1
        elif src[j] == ")":
            depth -= 1
            if depth == 0:
                break
    return src[i:j + 1]


def test_the_daemon_sends_an_action_id_with_every_run_start() -> None:
    src = DAEMON.read_text(encoding="utf-8")
    call = _call(src)
    assert "actor_action_id" in call, (
        "the daemon opens a run without an action id — pulse_runs.actor_action_id "
        "goes back to NULL and nothing can join a scheduled run to what it did")


def test_the_action_id_is_the_run_id_and_not_a_fresh_one() -> None:
    """A second uuid would populate the column and join to nothing, which is
    worse than NULL: it reads as lineage."""
    src = DAEMON.read_text(encoding="utf-8")
    assert re.search(r"actor_action_id\s*=\s*run_id", _call(src)), (
        "the action id is not `run_id` — the child receives PULSE_RUN_ID=run_id, "
        "so any other value breaks the join it was meant to make")


def test_the_client_puts_it_in_the_body_only_when_it_has_one() -> None:
    """An empty string in the body would overwrite a real id with nothing on a
    caller that does not supply one."""
    src = CLIENT.read_text(encoding="utf-8")
    fn = src[src.index("def post_run_start"):src.index("def post_run_finish")]
    assert "actor_action_id" in fn
    assert re.search(r"if\s+actor_action_id\s*:", fn), (
        "the client sends actor_action_id unconditionally; a caller without one "
        "would write an empty value over the column")


def test_the_agent_runner_adopts_the_scheduler_s_uuid() -> None:
    src = RUNNER.read_text(encoding="utf-8")
    assert "PULSE_RUN_ID" in src and "--session-uuid=$PULSE_RUN_ID" in src, (
        "tools/run-agent.sh does not adopt PULSE_RUN_ID as the session uuid, so "
        "a scheduled agent run and its session remain two unrelated rows")


def test_it_refuses_a_malformed_or_already_chosen_uuid() -> None:
    """`bin/run-agent.php` validates the 8-4-4-4-12 shape and exits 2 on
    anything else — passing a non-UUID would turn a lineage improvement into a
    nightly job that cannot start. And an explicit --session-uuid from the
    caller must win."""
    src = RUNNER.read_text(encoding="utf-8")
    block = src[src.index("PULSE_RUN_ID"):]
    assert "[0-9a-fA-F]{8}-" in block, "the UUID shape guard is gone"
    assert '--session-uuid=' in block and 'PASSTHRU[*]' in block, (
        "nothing checks whether the caller already chose a session uuid")


def test_the_wing_side_has_always_been_ready() -> None:
    """Named so the fix is not later 'improved' by adding a column that exists.
    The repository accepted this field for sixteen months; only the sender was
    missing."""
    src = REPOSITORY.read_text(encoding="utf-8")
    assert "'actor_action_id' => $payload['actor_action_id'] ?? null" in src
