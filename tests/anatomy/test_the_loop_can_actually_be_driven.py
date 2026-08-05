"""An engine nobody can invoke is indistinguishable from one that is absent.

THE MEASUREMENT THAT PROMPTED THIS (2026-08-05). Steps 1–4 of the contract's
§10 build order are complete: five judges, the ledger with its WORM chain, the
weakness reader, the budget and its refusals — all live, all gated, all tested.
And the ledger had not moved since it was built: 9 proposals, 13 verdicts and 19
judge runs, every one dated 2026-08-02/03.

Nothing was broken. `nos-loop` shipped exactly one verb of the seven §6.2 names,
so the only way to run an attended cycle was hand-written curl with the correct
bearer token of three. §7.2 makes attended cycles the precondition for ever
shipping the one Pulse job, which means the missing verbs were not a convenience
gap — they were the reason the loop could not start.

WHAT THIS FILE PINS

  1. Every verb §6.2 documents is either implemented or explicitly deferred with
     a reason IN THE SOURCE. The contract is the spec; a spec that lists a verb
     nobody wrote is how this happened once already.
  2. `propose` and `judge` do not share a credential. Constraint A is a sentence
     about credentials, and the terminal is the one place a human holds all
     three — a client that authenticated everything with one bearer would
     dissolve the split exactly where it matters most.
  3. INDETERMINATE never maps to the success exit. DECISION 6a separates it from
     FAIL at the shell boundary so a wrapper cannot collapse them; mapping it to
     0 would be worse than collapsing them.
  4. Bone's staleness canary compares the plist to the RUNNING JOB, not to its
     own template.

ON (4), MEASURED THE SAME DAY, and it is why the verbs could not be exercised
even after they existed: the plist declared 22 environment variables and the
loaded launchd job carried 21. The missing one was BONE_LOOP_OPERATOR_TOKEN —
the credential behind `nos-loop forget`, the operator's only exit from a wedged
fingerprint. It had been missing for at least two days while the existing canary
reported the environment healthy, because that canary reads one route with one
token and the token it reads was one of the 21.

No converge could repair it: the reload is notify-driven off the plist template,
the template was already correct, so it never fired again. A comparison between
a template and a file cannot see a process that drifted from both.

CI-safe: pure source reading. No network, no launchd, no live estate.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "files/anatomy/bone/bin/nos-loop"
CONTRACT = REPO / "docs/idea/11-agentic-loop-contract.md"
BONE_TASKS = REPO / "roles/pazny.bone/tasks/main.yml"


def _cli_source() -> str:
    return CLI.read_text(encoding="utf-8")


def _cli_tree() -> ast.Module:
    return ast.parse(_cli_source())


def _declared_verbs() -> set[str]:
    """The verbs argparse actually registers — read from the AST, not a regex.

    `sub.add_parser("weaknesses", ...)` with the name as a literal. A regex over
    the help text would pass on a verb that is only documented.
    """
    verbs: set[str] = set()
    for node in ast.walk(_cli_tree()):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_parser"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            verbs.add(node.args[0].value)
    return verbs


def _contract_verbs() -> set[str]:
    """Verbs the contract's §6.2 block documents, e.g. `nos-loop judge ...`."""
    text = CONTRACT.read_text(encoding="utf-8")
    block = re.search(r"### 6\.2 CLI.*?```(.*?)```", text, re.S)
    assert block, "§6.2's CLI block is gone from the contract — this gate is blind"
    return set(re.findall(r"^nos-loop\s+([a-z-]+)", block.group(1), re.M))


def test_the_sources_are_readable():
    """Positive control: every assertion below reads one of these."""
    assert CLI.is_file(), f"{CLI} is missing"
    assert _declared_verbs(), "no argparse verbs found — the AST walk is broken"
    assert _contract_verbs(), "no verbs parsed out of §6.2"
    assert BONE_TASKS.is_file()


def test_every_verb_the_contract_names_is_implemented_or_refused_in_writing():
    documented = _contract_verbs()
    implemented = _declared_verbs()
    missing = documented - implemented
    source = _cli_source()
    # A deferral is legitimate — `verdict --replay` needs a route that does not
    # exist and cannot be faked client-side without importing the engine. What
    # is not legitimate is silence: the reason must be in this file, where the
    # next reader looks, not in a commit message.
    undocumented_gaps = sorted(v for v in missing if v not in source)
    assert not undocumented_gaps, (
        f"§6.2 documents {undocumented_gaps} and nos-loop neither implements "
        f"them nor says why. That is the exact state that left the ledger "
        f"frozen for three days with nothing broken."
    )


def test_the_proposer_and_the_evaluator_do_not_share_a_credential():
    tree = _cli_tree()
    identity = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "IDENTITY" for t in node.targets)):
            identity = ast.literal_eval(node.value)
    assert isinstance(identity, dict) and len(identity) >= 3, (
        "nos-loop no longer maps scopes to distinct credentials; one bearer for "
        "every verb makes the §3.4 identity split a naming convention"
    )
    env_vars = [v[0] for v in identity.values()]
    assert len(set(env_vars)) == len(env_vars), (
        f"two scopes read the same env var: {identity}"
    )
    assert identity["propose"][0] != identity["judge"][0], (
        "propose and judge share a token — Constraint A at the one boundary "
        "where a human is holding all three"
    )


def test_indeterminate_is_never_the_success_exit():
    tree = _cli_tree()
    mapping = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "_VERDICT_EXIT" for t in node.targets)):
            mapping = {k: v for k, v in zip(
                [c.value for c in node.value.keys],
                [c.id for c in node.value.values])}
    assert mapping, "the verdict→exit map is gone; DECISION 6a is unenforced"
    assert mapping["pass"] == "EXIT_OK"
    assert mapping["fail"] == "EXIT_FAIL"
    assert mapping["indeterminate"] == "EXIT_INDETERMINATE", (
        "INDETERMINATE must not map to OK or FAIL: §2.4's whole claim is that "
        "absence is neither success nor a judge's no"
    )
    # And the fallback for an unrecognised result must not be OK either.
    assert "_VERDICT_EXIT.get(str(verdict.get(\"result\")), EXIT_INDETERMINATE)" in _cli_source(), (
        "an unknown verdict result falls back to something other than "
        "INDETERMINATE — a new result string would then read as a pass"
    )


def test_the_bone_canary_compares_the_plist_to_the_running_job():
    """A template-vs-file check cannot see a process that drifted from both."""
    tasks = BONE_TASKS.read_text(encoding="utf-8")
    assert "_bone_env_canary" in tasks, (
        "the env-drift canary is gone; Bone is back to certifying 22 variables "
        "by reading one"
    )
    assert "launchctl print" in tasks and "EnvironmentVariables" in tasks, (
        "the canary no longer reads the LOADED job's environment, so it is "
        "comparing the plist to itself"
    )
    reload_block = tasks.split("Reload Bone when a canary shows stale")[-1]
    assert "_bone_env_canary" in reload_block[:900], (
        "the env canary runs but the reload does not consult it — a probe whose "
        "answer changes nothing is the shape it was written to replace"
    )


@pytest.mark.parametrize("verb", ["weaknesses", "budget", "propose", "judge", "history", "forget"])
def test_each_shipped_verb_has_a_handler(verb):
    """argparse registering a name is not the same as a function existing."""
    fn = "cmd_" + verb.replace("-", "_")
    assert re.search(rf"^def {fn}\(", _cli_source(), re.M), (
        f"verb {verb!r} is registered but {fn}() is missing"
    )
