"""The loop has a cadence, the cadence keeps the identity split, and the
entry half is honest about never having run unattended.

WHAT WAS MEASURED (2026-08-19, the operator's own question — "does any loop
drive development, or must I keep pushing it from a chat session?"): zero
Pulse jobs referenced the loop; every proposal in the ledger was filed by
`agent:librarian` or `agent:claude-opus-5` with a human typing at it; 63 of 66
reported weaknesses had never been proposed against. docs/idea/11-agentic-loop-contract.md §10 step 6 says
"one Pulse job, only after enough attended cycles to trust the above" — and
the honest reading of that bar is PER HALF:

  * the judged half (drive + review) has three attended green cycles and its
    refusal paths were seen refusing → its jobs ship ACTIVE;
  * the entry half (a model authoring unattended) has zero cycles in that
    shape → its job ships PAUSED, with the reason written into the row.

WHAT THIS FILE PINS

  1. `loop-base` declares exactly the three jobs, with the exact argv of the
     operator tools — the cadence runs THE SAME code an attended cycle runs,
     never a parallel implementation.
  2. `propose` is paused and its reason names the unmet bar. Unpausing is a
     deliberate operator act in Wing, not a converge side effect.
  3. No loop job carries a secret in env. Every tool resolves its own from
     ~/.nos/secrets.yml — which is also what keeps this manifest out of the
     two-allowlist substitution trap (memory: pulse-catalog-literal-
     substitution: a token missing from EITHER list vanishes silently).
  4. The entry runner holds no judge identity: it never reads
     `loop_judge_token` and never invokes `nos-loop`. The proposer proposes
     and stops (docs/idea/11-agentic-loop-contract.md §3.4).
  5. The committed-evidence deadlock is refused with its remedy, not spent a
     model run on: `pick()` raises with the commit named when nothing
     proposable is also fixable, and the ledger's refusal distinguishes
     "uncommitted-evidence" from "unknown-weakness".

CI-safe: manifest parsing, pure functions, and source shape. No network, no
model, no live daemon.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "files" / "anatomy" / "plugins" / "loop-base" / "plugin.yml"
ENTRY = REPO / "tools" / "loop-propose.py"
BONE = REPO / "files" / "anatomy" / "bone"


@pytest.fixture(scope="module")
def jobs() -> dict[str, dict]:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    return {j["name"]: j for j in manifest["pulse"]["jobs"]}


@pytest.fixture(scope="module")
def entry():
    spec = importlib.util.spec_from_file_location("_loop_propose_gate", ENTRY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_cadence_runs_the_operator_tools_verbatim(jobs):
    assert set(jobs) == {"propose", "drive", "review"}
    assert jobs["drive"]["command"].endswith("tools/loop-pr.py")
    assert jobs["drive"]["args"] == ["--open-mr", "--rejudge"]
    assert jobs["review"]["command"].endswith("tools/loop-review.py")
    assert jobs["review"]["args"] == ["--merge"]
    assert jobs["propose"]["command"].endswith("tools/loop-propose.py")
    assert jobs["propose"]["args"] == ["--invoke"], (
        "the tool is dry-run by default; a cadence that forgets --invoke "
        "would tick green nightly while doing nothing — absence as success")


def test_the_entry_job_is_paused_and_says_why(jobs):
    propose = jobs["propose"]
    assert propose.get("paused") is True, (
        "the entry half has zero attended unattended-shaped cycles; §10 step "
        "6's bar is not met for it. If that has changed, change this gate in "
        "the same commit that records the attended runs")
    assert "attended" in propose.get("paused_reason", ""), (
        "the pause must name its bar, or the row reads as an accident to unpause")


def test_no_loop_job_carries_a_secret(jobs):
    for name, job in jobs.items():
        env = job.get("env") or {}
        assert env == {}, (
            f"job {name!r} carries env {list(env)} — loop tools resolve their "
            f"own credentials from ~/.nos/secrets.yml; env here re-enters the "
            f"two-allowlist substitution trap")


def test_the_entry_runner_holds_no_judge_identity():
    # The module docstring may NAME the token it forswears; the code may not
    # CONTAIN it. Scan everything after the docstring closes.
    src = ENTRY.read_text(encoding="utf-8").split('"""', 2)[2]
    assert "loop_judge_token" not in src, (
        "the proposer's runner reached for the evaluator's token — §3.4's "
        "split is gone")
    # The only subprocess this runner may spawn is `claude`. `"nos-loop"` as
    # a standalone argv token would be the runner reaching for the loop CLI
    # (whose judge subcommand is the evaluator's act); the plugin PATHS in the
    # prompt (".claude/plugins/nos-loop/…") are longer strings and don't match.
    assert '"nos-loop"' not in src and "'nos-loop'" not in src, (
        "the entry runner invokes the loop CLI — judging is the driver's act")


def test_pick_refuses_the_deadlock_with_the_remedy(entry):
    """Nothing proposable-and-fixable → Refused naming the commit, never a
    model run. The fake reader stipulates the measured 2026-08-19 state:
    every rem: withheld (evidence uncommitted), only fee: proposable."""
    class FakeStatus:
        @staticmethod
        def live_weaknesses():
            return [
                {"id": "rem:REM-1", "severity": "high", "title": "t",
                 "proposable": False},
                {"id": "fee:07", "severity": "high", "title": "t",
                 "proposable": True},
            ], None

        @staticmethod
        def collect():
            return {"sources": []}

        @staticmethod
        def _source_of(wid):
            return wid.split(":", 1)[0]

    with pytest.raises(entry.Refused) as exc:
        entry.pick(FakeStatus, None)
    msg = str(exc.value)
    assert "deadlock" in msg.lower()
    assert "commit" in msg.lower(), "the refusal must carry its own remedy"


def test_pick_hands_over_the_worst_fixable_weakness(entry):
    class FakeStatus:
        @staticmethod
        def live_weaknesses():
            return [
                {"id": "rem:R-med", "severity": "medium", "title": "t", "proposable": True},
                {"id": "rem:R-high", "severity": "high", "title": "t", "proposable": True},
                {"id": "rem:R-blocked", "severity": "critical",
                 "title": "x: vendor_blocked — abandoned", "proposable": True},
                {"id": "fee:1", "severity": "critical", "title": "t", "proposable": True},
            ], None

        @staticmethod
        def collect():
            return {"sources": [{"weaknesses": ["rem:R-done"]}]}

        @staticmethod
        def _source_of(wid):
            return wid.split(":", 1)[0]

    chosen = entry.pick(FakeStatus, None)
    assert chosen["id"] == "rem:R-high", (
        "expected the worst ACTIONABLE row: fee: is budget-unfixable and a "
        "vendor_blocked row has no upstream fix to propose")


def test_the_ledger_distinguishes_withheld_from_unseen(monkeypatch):
    """`uncommitted-evidence` vs `unknown-weakness`: the first refusal's text
    was literally false during the deadlock ('not reported by any weakness
    source' about a weakness the source was reporting loudly)."""
    sys.path.insert(0, str(BONE))
    try:
        import ledger  # noqa: PLC0415

        monkeypatch.setattr(ledger, "default_uncommitted_weakness_ids",
                            lambda: {"rem:WITHHELD"})
        led = ledger.open_ledger("reader", weakness_index={"rem:KNOWN": "sha"})
        try:
            with pytest.raises(ledger.ProposalRefused) as withheld:
                led._weakness_evidence_sha("rem:WITHHELD")
            assert withheld.value.reason == "uncommitted-evidence"
            assert "commit" in str(withheld.value).lower()

            with pytest.raises(ledger.ProposalRefused) as unseen:
                led._weakness_evidence_sha("rem:NOBODY-REPORTS")
            assert unseen.value.reason == "unknown-weakness"
        finally:
            led.close()
    finally:
        sys.path.remove(str(BONE))
