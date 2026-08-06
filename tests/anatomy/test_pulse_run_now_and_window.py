"""Anatomy gate — the §4b run-now endpoint and the runs time window.

Subject: files/anatomy/wing/app/{Core/RouterFactory.php,
Presenters/Api/PulsePresenter.php, Model/PulseRepository.php} (2026-08-06,
the run screen's Wing half — anatomy-graph-screens.md §4b + §3).

THE INVARIANT THAT MATTERS: **run-now must not be a spawn path.** The whole
§4b design is that the endpoint edits one row (next_fire_at = now) and the
daemon remains the only executor, so every existing guard — re-entrancy, the
4-slot cap, max_concurrent, the agent-run-lock — applies to a browser-
triggered run exactly as to a scheduled one. An endpoint that execs is
remote code execution with a friendlier name; this gate greps the runNow
body for every PHP spawn primitive and refuses all of them.

Source-level and offline (no PHP runtime in CI): the assertions read the
files the converge deploys. That cannot prove runtime behaviour — the smoke
catalog owns end-to-end truth — but it pins the shapes a refactor would
silently lose: the refusals, the recorded request, the canonicalised window.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing/app"

PRESENTER = (WING / "Presenters/Api/PulsePresenter.php").read_text(encoding="utf-8")
REPOSITORY = (WING / "Model/PulseRepository.php").read_text(encoding="utf-8")
ROUTER = (WING / "Core/RouterFactory.php").read_text(encoding="utf-8")


def _fn(src: str, name: str) -> str:
    """Body of one PHP function, delimited by the next function declaration."""
    m = re.search(rf"function {name}\b.*?(?=\n\t(?:public|private|protected) function |\Z)",
                  src, re.S)
    assert m, f"function {name} not found — the surface this gate pins is gone"
    return m.group(0)


def _code(body: str) -> str:
    """The body with comments and docblocks stripped — a gate that greps raw
    text cannot tell an exec from a sentence ABOUT an exec (the same reason
    test_loop_ledger.py::code_of parses instead of grepping), and this file's
    own first run proved it: the phrase 'pulse_runs is the daemon's statement'
    in a comment tripped the pulse_runs ban."""
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    return re.sub(r"//[^\n]*", "", body)


def test_the_run_now_route_exists_before_its_general_sibling():
    assert "pulse_jobs/<id>/run-now" in ROUTER, "the §4b route is not registered"
    assert ROUTER.index("pulse_jobs/<id>/run-now") < ROUTER.index("pulse_jobs[/<id>]"), (
        "run-now is registered AFTER the [/<id>] sibling — Nette is "
        "first-match-wins and the general route would swallow it"
    )


def test_run_now_is_not_a_spawn_path():
    body = _code(_fn(PRESENTER, "actionRunNow"))
    for primitive in ("proc_open", "exec(", "shell_exec", "popen", "system(",
                      "passthru", "pcntl_"):
        assert primitive not in body, (
            f"actionRunNow contains {primitive!r} — §4b's whole design is that "
            f"the daemon remains the ONLY executor; an endpoint that spawns "
            f"bypasses the re-entrancy guard, the slot cap and the agent lock"
        )
    # The one write it performs is the row edit, delegated to the repository.
    assert "requestRunNow" in body


def test_run_now_refuses_paused_and_body_and_unknown():
    body = _fn(PRESENTER, "actionRunNow")
    assert "409" in body and "paused_reason" in body, (
        "the paused refusal lost its 409 or stopped carrying paused_reason — "
        "unpausing must stay a separate deliberate act"
    )
    assert "404" in body, "unknown-job refusal gone"
    assert "php://input" in body and "400" in body, (
        "the empty-body refusal is gone — a run-now that can carry env is "
        "remote code execution with extra steps"
    )


def test_run_now_records_the_request_not_the_outcome():
    body = _fn(PRESENTER, "actionRunNow")
    assert "pulse_run_requested" in body and "actor_action_id" in body, (
        "the request event vanished — WHO asked is the audit half of §4b"
    )
    # The reader records the run: this endpoint must not write pulse_runs.
    assert "pulse_runs" not in _code(body), (
        "actionRunNow touches pulse_runs — the run row is the DAEMON's "
        "statement (success markers are written by a reader)"
    )
    repo_fn = _fn(REPOSITORY, "requestRunNow")
    assert "pulse_runs" not in _code(repo_fn) and "next_fire_at" in repo_fn


def test_the_runs_window_is_canonicalised_not_trusted():
    assert "since" in _fn(PRESENTER, "listRuns"), "since param gone from listRuns"
    tp = _fn(PRESENTER, "timeParam")
    assert "strtotime" in tp and "400" in tp, (
        "garbage time params must be a 400, not a silently dropped filter"
    )
    assert "date('c'" in tp, (
        "the window value is passed through unnormalised — the 2026-07-28 "
        "two-ISO-spellings bug is exactly one offset spelling away"
    )
    repo_fn = _fn(REPOSITORY, "listRuns")
    assert "fired_at >= ?" in repo_fn and "fired_at <= ?" in repo_fn
