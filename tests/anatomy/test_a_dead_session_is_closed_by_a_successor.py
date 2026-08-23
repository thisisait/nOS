"""An abandoned agent session is closed by something demonstrably alive.

WHAT HAPPENED. `AgentSessionRepository::terminateStale()` was written on
2026-06-10, after five orphaned `running` rows were hand-cleaned in a single
day. It works. Its only caller was `AgentsPresenter::renderDefault()` — Wing's
/agents page — on stated reasoning that reads well and turned out to be
load-bearing in the wrong direction:

    "the page where orphans annoy is the page that clears them"

That was true while /agents was the only surface showing orphans. It stopped
being true on 2026-08-18, when `tools/red-status.py` shipped. Orphans now annoy
on a **reader**, and a reader may not write — deliberately, because half this
estate's expensive defects were a marker written by the code that attempted the
work. So the complaint moved to a surface that must not act, and the repair
stayed on one nobody opened.

Measured: a surveyor session sat `running` for **110 hours** and was reported
red for four days. A LATER surveyor run started beside it, finished, and went
idle — without touching it. The reaper existed, was correct, and never ran.

THE FIX, AND WHY IT IS THIS SHAPE. `terminateStale()` is now also called at
session OPEN, on both runtimes: the PHP runner's `startSession()` and the
claude-CLI bridge's `agent_run_start` branch. A successor closes what its
predecessor could not — the row saying "this run died" is written by something
that is provably alive, never by the run itself.

BOTH runtimes matter and it is not symmetry for its own sake: the 110-hour
orphan arrived on the claude-CLI path, so reaping only in the PHP runner would
have left exactly the observed case uncovered.

WHAT THIS GATE PINS.
  1. Both session-creating paths reap before they insert. Reaping AFTER would
     let a run close itself the moment it opened.
  2. The cap lives with the reaper, not with one of its callers.
  3. The lazy page-view caller survives — it is the only path that TELLS the
     operator a reap happened.

WHAT IT CANNOT SEE. Whether the cap is wise, or whether a legitimately long run
gets killed by it. That is a judgement, and `AGENT_SESSION_CAP_MINUTES` is the
knob for it.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing/app"
REPOSITORY = WING / "Model/AgentSessionRepository.php"
PRESENTER = WING / "Presenters/AgentsPresenter.php"


def repo_src() -> str:
    return REPOSITORY.read_text(encoding="utf-8")


def _method(src: str, signature: str) -> str:
    """Body of a PHP method, by brace matching from its signature."""
    start = src.index(signature)
    brace = src.index("{", start)
    depth, i = 0, brace
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[brace:i + 1]
        i += 1
    raise AssertionError(f"unbalanced braces after {signature!r}")


def test_the_reaper_still_exists():
    assert "public function terminateStale(" in repo_src(), (
        "terminateStale() is gone; five orphans were hand-cleaned the day it "
        "was written, and one sat for 110 hours the day it gained callers")


def test_both_session_creating_paths_reap_before_inserting():
    src = repo_src()
    for signature in ("public function startSession(", "public function syncFromAgentEvent("):
        body = _method(src, signature)
        assert "terminateStale(" in body, (
            f"{signature}…) creates a `running` row without reconciling the "
            "abandoned ones. The 110-hour orphan arrived on the claude-CLI "
            "path (syncFromAgentEvent); covering only the other runtime would "
            "have missed exactly the case this exists for")
        reap = body.index("terminateStale(")
        insert = body.index("->insert(")
        assert reap < insert, (
            f"{signature}…) reaps AFTER inserting, so the session it just "
            "opened is a candidate for its own reaper the moment the cap is "
            "misconfigured — a run must never close itself")


def test_the_cap_belongs_to_the_reaper_not_to_a_caller():
    src = repo_src()
    assert "SESSION_CAP_MINUTES_DEFAULT" in src and "function staleCapMinutes(" in src, (
        "the cap must live with terminateStale(). It used to be a private "
        "constant on AgentsPresenter, which meant one of several callers "
        "defined the policy for all of them")
    presenter = PRESENTER.read_text(encoding="utf-8")
    assert not re.search(r"private const SESSION_CAP_MINUTES_DEFAULT", presenter), (
        "AgentsPresenter re-declares the cap; two defaults will drift and the "
        "countdown shown to the operator will stop matching the reap")


def test_the_page_view_reaper_survives_and_still_reports():
    presenter = PRESENTER.read_text(encoding="utf-8")
    body = _method(presenter, "public function renderDefault(")
    assert "terminateStale(" in body, (
        "the lazy page-view reap was removed. Keep it: it is a free extra "
        "chance, and it is the ONLY path that tells the operator a reap "
        "happened rather than doing it silently")
    assert "flashMessage" in body, (
        "a reap that says nothing is indistinguishable from no reap at all")
