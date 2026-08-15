"""Two clients inside a bound session are built UNBOUND. Today that is harmless.

MEASURED 2026-08-15, reading `Runner.php` after the spine redirect made the
`anthropic` provider bindable. Three `fromUri` call sites:

    :155  primary  — receives $decision->binding          ✔
    :605  grader   — no binding, when `model.grader` is declared
    :796  fallback — no binding, always

Both silent paths are CORRECT TODAY, and only by what the agent files happen
to declare:

  * no agent declares `model.grader`, so every grader falls to `: $llm` — the
    already-bound primary client;
  * every agent's fallback is `openclaw-*`, which `Factory::fromUri` refuses
    to bind anyway (its gateway speaks neither mechanism).

So this gate asserts the FACTS THE SAFETY RESTS ON, not the code. The day
either fact changes, a bound session would quietly split: a MiniMax-served run
whose JUDGE runs on the default backend — a different party grading the work,
recorded as one session — or whose fallback answers from a backend the agent's
own Article-30 record does not name. Neither would throw; the run would look
ordinary.

WHY NOT JUST FIX IT. Whether a bound session should BIND its grader and
fallback, or REFUSE them, is a design decision that belongs with the binding
design (the fallback half was raised by its author the same day). Deciding it
here by editing behaviour would be the cheaper and worse move. This gate holds
the ground until then: it cannot be satisfied by editing itself, because its
premises are what the nine agent files declare.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTS = REPO / "files/anatomy/agents"
RUNNER = REPO / "files/anatomy/wing/app/AgentKit/Runner.php"


def _agent_models() -> dict[str, dict]:
    out = {}
    for entry in sorted(AGENTS.iterdir()):
        manifest = entry / "agent.yml"
        if entry.is_dir() and manifest.is_file():
            doc = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            out[doc.get("name", entry.name)] = doc.get("model") or {}
    return out


def test_the_sweep_sees_the_agents():
    """Positive control — an empty sweep would make both checks below vacuous."""
    models = _agent_models()
    assert len(models) >= 9, (
        f"only {len(models)} agent definition(s) found; the premises of this "
        "gate are what those files declare, so a short sweep proves nothing."
    )


def test_no_agent_declares_a_grader_while_the_grader_is_built_unbound():
    """`model.grader` is a legitimate feature — this is not a ban on it.

    It is a tripwire: the first agent to declare one must also decide whether
    a bound session's judge may run on a different backend from the work it
    judges. Declaring one and changing nothing else is the silent split.
    """
    offenders = {n: m["grader"] for n, m in _agent_models().items() if m.get("grader")}
    assert not offenders, (
        f"agent(s) declare model.grader: {offenders}. Runner builds the grader "
        "client without the session's binding (Runner.php:605), so on a bound "
        "run the judge would be served by the DEFAULT backend while the work "
        "was served by the bound one — one session, two parties, no error. "
        "Bind it, or refuse it, before declaring one."
    )


def test_every_fallback_is_a_provider_that_refuses_binding_anyway():
    """The fallback is always built unbound (Runner.php:796). That is safe only
    while no fallback names a provider a binding COULD have reached."""
    bindable = ("anthropic-", "claude-")
    offenders = {
        n: m["fallback"]
        for n, m in _agent_models().items()
        if m.get("fallback") and str(m["fallback"]).startswith(bindable)
    }
    assert not offenders, (
        f"agent(s) declare a bindable fallback: {offenders}. `serveFallback` "
        "builds it with no binding, so a bound agent would fall back to the "
        "default backend — answering from a party its own Article-30 record "
        "does not name, and recorded under this session's attribution."
    )


def test_the_call_sites_this_gate_describes_still_look_like_this():
    """If Runner starts passing bindings to all three, this gate's premise is
    gone and it should be RETIRED, not left passing for the wrong reason."""
    src = RUNNER.read_text(encoding="utf-8")
    calls = re.findall(r"fromUri\(([^)]*)\)", src)
    assert len(calls) >= 3, (
        f"expected at least 3 fromUri call sites in Runner, found {len(calls)}; "
        "the shape this gate reasons about has changed."
    )
    bound = [c for c in calls if "binding" in c]
    assert len(bound) == 1, (
        f"{len(bound)} of {len(calls)} fromUri call sites now pass a binding "
        "(was 1 of 3 on 2026-08-15). If the grader and fallback are bound now, "
        "delete this file — its reason to exist is gone. If MORE are unbound, "
        "the split it guards against has grown."
    )
