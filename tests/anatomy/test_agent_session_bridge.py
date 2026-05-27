"""Anatomy gate — claude-CLI agent runs surface in /agents sessions (W5-A1, 2026-05-26).

The pulse / claude-CLI runtime (pulse-run-agent.sh) emits agent_run_start/end
events grouped by actor_action_id but never created an agent_sessions row, so
those runs were invisible in Wing /agents (only /timeline). Operator hit this:
"I don't see the run in sessions, only timeline without detail."

Fix: AgentSessionRepository::syncFromAgentEvent upserts a session keyed on
uuid == actor_action_id (so the run's events attach to the transcript) and
repairs orphaned same-run_id events (the inner agent's conductor_report left
actor_action_id null on scout). Api\EventsPresenter calls it live on ingest;
bin/backfill-agent-sessions.php replays historical events; the wing role runs
the backfill on deploy.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
REPOSITORY = WING / "app/Model/AgentSessionRepository.php"
EVENTS_PRESENTER = WING / "app/Presenters/Api/EventsPresenter.php"
BACKFILL = WING / "bin/backfill-agent-sessions.php"
WING_POST = REPO / "roles/pazny.wing/tasks/post.yml"


def test_repository_has_sync_from_agent_event():
    src = REPOSITORY.read_text()
    assert "function syncFromAgentEvent" in src, "session-bridge method missing"
    # Keys on the pulse-runner event types.
    assert "agent_run_start" in src and "agent_run_end" in src
    # Session uuid == the event's actor_action_id (so events attach).
    assert "actor_action_id" in src


def test_repository_repairs_orphaned_run_events():
    """The inner agent's conductor_report can land with a null actor_action_id
    (scout did). The sync must stamp the session uuid onto null-attribution
    events sharing the run_id, so the report shows in the transcript."""
    src = REPOSITORY.read_text()
    assert "run_id" in src
    assert "UPDATE events SET actor_action_id" in src, "orphaned-event repair missing"


def test_events_ingest_syncs_sessions():
    """The HMAC event-ingest must call syncFromAgentEvent so live runs surface
    without a separate write endpoint."""
    src = EVENTS_PRESENTER.read_text()
    assert "AgentSessionRepository" in src, "EventsPresenter must inject the session repo"
    assert "syncFromAgentEvent" in src, "EventsPresenter must sync sessions on ingest"


def test_backfill_script_present_and_wired():
    assert BACKFILL.is_file(), "backfill-agent-sessions.php missing"
    post = WING_POST.read_text()
    assert "backfill-agent-sessions.php" in post, "wing role must run the backfill on deploy"


def test_agent_reports_linked_by_bounded_window():
    """2026-05-27: the inner agent posts its conductor_report with its own
    run_id/actor_action_id, so it didn't attach to the session transcript. On
    run-end, link reports from this agent within the run's FULL window
    [started_at, ended_at] (both bounds — a lower-bound-only window let the
    first run greedily grab every later run's report). Renders the full report
    in the session deep-dive."""
    src = REPOSITORY.read_text()
    assert "function linkAgentReports" in src, "report-linkage helper missing"
    assert "ts >= ? AND ts <= ?" in src, "linkage must bound BOTH ends of the run window"
    sess = (WING / "app/Templates/Agents/session.latte").read_text()
    assert "report_markdown" in sess, "session transcript must render the conductor_report body"
