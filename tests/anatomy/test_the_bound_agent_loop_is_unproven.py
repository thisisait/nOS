"""No ceremony has ever completed on AgentKit's own LLM loop. Say so.

MEASURED 2026-08-17 against the live `agent_sessions` table, after five
supervised runs of a new agent produced no report and roughly a million
MiniMax input tokens.

Every session that has ever reached `stop_reason: run_end`:

    conductor  run_end   177 in   8452 out   cli:unrecorded
    conductor  run_end    97 in  10128 out   cli:unrecorded
    conductor  run_end    35 in  14345 out   claude-cli
    conductor  run_end    24 in  14819 out   claude-cli
    conductor  run_end    35 in  15604 out   claude-cli

All five are the CLI path. On AgentKit's IN-PROCESS bound loop the tally is
fourteen sessions and zero completions — six `error`, five `outcome_failed`,
three `ceiling`. The shape is consistent across two different agents and two
different authors: the model emits a one-line preamble, calls a tool, and
repeats until the budget ends. The longest prose any bound session ever
produced measured 142 characters.

WHY THIS NEEDS A GATE RATHER THAN A PARAGRAPH. Nothing in the estate was
wrong. The agent loaded, the tools worked, the guards held, the ceiling fired
correctly and recorded its spend, the audit lineage reconstructed the run
perfectly. Every surface reported success at its own level, and the ceremony
still produced nothing — so the only way to learn this is to spend the budget
and read the sessions table afterwards. That is a floor, and a floor nobody
wrote down gets rediscovered at full price. It was rediscovered at full price
once already: the librarian's runs on 2026-08-16 say exactly the same thing a
day earlier.

WHAT IS PINNED: that an agent bound to a backend — i.e. one that runs on the
in-process loop rather than the CLI — is never advertised as `live`. The
claim is deliberately narrow. It does not say the loop cannot work, it says
nobody has shown it working, and an estate that refuses a dangling
`upstream:` at compile time should not carry a runner that has never
finished under a label that means it has.

RETIRE THIS FILE when a bound session reaches `run_end` with a graded
outcome. That is a good day and this gate should not survive it: delete the
file, and move the agent to `live` in the same commit that shows the session.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTS = REPO / "files/anatomy/agents"

#: Statuses that assert the ceremony runs and finishes today.
CLAIMS_IT_WORKS = {"live"}


def _agents() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for entry in sorted(AGENTS.iterdir()):
        manifest = entry / "agent.yml"
        if entry.is_dir() and manifest.is_file():
            doc = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            out[doc.get("name", entry.name)] = doc
    return out


def _bound(doc: dict) -> str | None:
    """The backend a session would be routed to, or None for the CLI path."""
    return ((doc.get("model") or {}).get("backend")) or None


def test_the_sweep_sees_the_agents():
    """Positive control — an empty sweep makes everything below vacuous."""
    agents = _agents()
    assert len(agents) >= 10, (
        f"only {len(agents)} agent definition(s) found; this gate reasons over "
        "what those files declare, so a short sweep proves nothing."
    )


def test_at_least_one_agent_is_bound_or_this_gate_is_vacuous():
    """The premise. If nothing routes to a backend any more, the in-process
    loop is unused and this file should be deleted rather than left passing."""
    bound = {n: _bound(d) for n, d in _agents().items() if _bound(d)}
    assert bound, (
        "no agent declares model.backend, so nothing runs on the in-process "
        "loop and this gate asserts nothing. Delete it."
    )


def test_a_bound_agent_is_never_advertised_as_live():
    offenders = {}
    for name, doc in _agents().items():
        backend = _bound(doc)
        if not backend:
            continue
        status = str(((doc.get("metadata") or {}).get("runner_status", ""))).lower()
        if status in CLAIMS_IT_WORKS:
            offenders[name] = f"backend={backend} runner_status={status}"

    assert not offenders, (
        f"agent(s) claim a working runner they have never demonstrated: "
        f"{offenders}. As of 2026-08-17 the in-process bound loop has 14 "
        "sessions and 0 completions, across two agents; every ceremony that "
        "has ever finished ran on the CLI path. Mark it `on-demand` or "
        "`unproven`, or show a bound session that reached run_end with a "
        "graded outcome — and if you have one, delete this file instead."
    )


def test_a_bound_agent_says_which_runner_it_expects():
    """Silence is the failure this cost a day to. An unset `runner_status`
    reads as 'ordinary, working agent' to every reader and every listing."""
    silent = [
        name for name, doc in _agents().items()
        if _bound(doc) and not ((doc.get("metadata") or {}).get("runner_status"))
    ]
    assert not silent, (
        f"agent(s) route to a backend without declaring metadata.runner_status: "
        f"{silent}. An unset status is read as working. Say what is actually "
        "true of the runner — the honest value today is `unproven`."
    )
