"""W6.3 gates (2026-06-10) — /agents run-lifecycle surface.

Operator-requested (parked 2026-05-30): failed/killed agent runs never emit
agent_run_end, so their `running` row hung forever (5 orphans hand-cleaned
that day). Pins:
  - server-side stale reaper (lazy, on catalog view) + its cap default
  - operator kill is POST + CSRF + only flips `running` rows
  - the kill route precedes the catch-all /agents/<name> (first-match-wins)
  - the template states the honest kill semantics (row ≠ OS process)
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]

PRESENTER = REPO / "files/anatomy/wing/app/Presenters/AgentsPresenter.php"
SESSIONS = REPO / "files/anatomy/wing/app/Model/AgentSessionRepository.php"
TEMPLATE = REPO / "files/anatomy/wing/app/Templates/Agents/default.latte"
ROUTER = REPO / "files/anatomy/wing/app/Core/RouterFactory.php"


def test_reaper_runs_on_catalog_view():
    src = PRESENTER.read_text()
    body = src[src.index("function renderDefault"):]
    assert "terminateStale" in body.split("function ", 1)[0] or "terminateStale" in body[:1500], (
        "renderDefault no longer sweeps stale running sessions — orphaned "
        "rows would hang `running` forever again"
    )
    # The cap and its env override MOVED to AgentSessionRepository on
    # 2026-08-23, when the reaper gained callers that are not a page (session
    # open, on both runtimes). A policy defined by one of several callers
    # drifts, so it now lives with the reaper — and this assertion follows it
    # rather than pinning the old location. See
    # tests/anatomy/test_a_dead_session_is_closed_by_a_successor.py.
    sessions = SESSIONS.read_text()
    assert "SESSION_CAP_MINUTES_DEFAULT" in sessions
    assert "AGENT_SESSION_CAP_MINUTES" in sessions, "env override lost"
    assert "staleCapMinutes" in src, (
        "the presenter must still ASK for the cap — it shows the operator a "
        "per-session countdown against it, and a hard-coded second copy is how "
        "the countdown stops matching the reap")


def test_terminate_stale_only_touches_running_past_cutoff():
    src = SESSIONS.read_text()
    body = src[src.index("function terminateStale"):]
    body = body[:body.index("\n\t}")]
    assert "'status', 'running'" in body
    assert "started_at < ?" in body
    assert "'interrupted'" in body
    assert "wing-stale-reaper" in body, "reaper attribution lost from error_json"


def test_mark_interrupted_is_guarded_to_running():
    src = SESSIONS.read_text()
    body = src[src.index("function markInterrupted"):]
    body = body[:body.index("\n\t}")]
    assert "'status', 'running'" in body, (
        "markInterrupted must only flip running rows — an idle/terminated "
        "session must not be rewritable via the kill verb"
    )
    assert "operator kill" in body


def test_kill_action_is_post_csrf_gated():
    src = PRESENTER.read_text()
    body = src[src.index("function actionKill"):]
    assert "requirePostMethod()" in body[:400], (
        "actionKill lost requirePostMethod (POST + CSRF validation)"
    )
    # Presenter-wide super-admin gate must still stand.
    assert "requireSuperAdmin()" in src


def test_kill_route_precedes_catch_all():
    src = ROUTER.read_text()
    kill = src.index("'agents/kill'")
    catch_all = src.index("'agents/<name>'")
    assert kill < catch_all, (
        "agents/kill must be added BEFORE agents/<name> — Nette router is "
        "first-match-wins, the catch-all would swallow the verb as a name"
    )


def test_template_kill_form_has_csrf_and_honest_confirm():
    src = TEMPLATE.read_text()
    form = src[src.index('action="/agents/kill'):]
    form = form[:form.index("</form>")]
    assert 'name="_csrf"' in form, "kill form lost the SEC-14 CSRF field"
    assert "Pulse max_runtime" in form, (
        "the confirm must state the honest semantics: the row is marked "
        "dead, the OS process is governed by Pulse separately"
    )


def test_template_shows_elapsed_and_cap_countdown():
    src = TEMPLATE.read_text()
    assert "elapsed_min" in src and "remaining_min" in src
    assert "sessionCapMinutes" in src
    assert "tokens_pct" in src, "token mini-bar denominator lost"
