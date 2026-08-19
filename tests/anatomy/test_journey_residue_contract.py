"""An e2e journey may not leave anything in the live estate (2026-08-19).

MEASURED, the two leaks this pins. `test_approval_flow` POSTed an approval
question as `e2e-mock-agent` on every run and never took back the
`Agent asks:` notification the repository filed with it: 29 runs between
2026-08-11 and 08-16 became 29 permanent HIGH rows in the operator's inbox —
the single largest block of a 69-row triage. Sixty orphaned
`nos-tester-e2e-*` Authentik accounts grew from the same root: every cleanup
path was best-effort and NOTHING FAILED when cleanup had not happened.

The structural answer lives in tests/e2e/lib/residue.py + the journey
harness (tests/e2e/conftest.py): PREFLIGHT (residue from any earlier run —
including a SIGKILLed one — fails the next run, named), UNDO (registered at
mutation time, unwound on pass and fail alike), POSTFLIGHT (probes re-read
the estate after cleanup; the cleanup code never reports its own success).

This gate holds three things:

  1. the ledger's semantics, functionally — leaks refuse to start, undo
     failures are collected not swallowed, postflight is a read;
  2. the harness wiring — preflight before the start event, unwind +
     postflight in the finally, a leak failing a green run without
     shadowing a red one;
  3. the journey contract — a journey file that mutates the estate
     (csrf_post / raw POST) must register undos via `j.mutates(`.

Point 3 is the one that would have caught the 29 rows on run #2.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RESIDUE_PY = REPO / "tests/e2e/lib/residue.py"
CONFTEST_PY = REPO / "tests/e2e/conftest.py"
JOURNEYS_DIR = REPO / "tests/e2e/journeys"


def _load_residue():
    spec = importlib.util.spec_from_file_location("nos_e2e_residue", RESIDUE_PY)
    mod = importlib.util.module_from_spec(spec)
    # dataclasses resolves string annotations via sys.modules[cls.__module__];
    # an unregistered module makes @dataclass itself blow up on 3.13.
    sys.modules["nos_e2e_residue"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── 1. Ledger semantics ──────────────────────────────────────────────────────

def test_preflight_refuses_to_start_over_residue():
    r = _load_residue()
    ledger = r.ResidueLedger(
        journey="approval_flow",
        probes=(r.ResidueProbe("unread ask row", lambda: ["uuid-1", "uuid-2"]),),
    )
    with pytest.raises(r.ResidueLeakError) as exc:
        ledger.preflight()
    msg = str(exc.value)
    assert "uuid-1" in msg and "uuid-2" in msg, "the leak must be NAMED"
    assert "previous run" in msg


def test_preflight_on_a_clean_estate_is_silent():
    r = _load_residue()
    ledger = r.ResidueLedger(journey="x", probes=(r.ResidueProbe("p", list),))
    ledger.preflight()  # must not raise


def test_an_unreadable_probe_raises_instead_of_reading_as_clean():
    # Absence of an answer is not absence of residue — the estate's oldest rule.
    r = _load_residue()

    def _broken() -> list[str]:
        raise OSError("wing.db unreadable")

    ledger = r.ResidueLedger(journey="x", probes=(r.ResidueProbe("p", _broken),))
    with pytest.raises(OSError):
        ledger.preflight()


def test_unwind_runs_every_undo_newest_first_and_collects_failures():
    r = _load_residue()
    ledger = r.ResidueLedger(journey="x")
    order: list[str] = []

    def _boom() -> None:
        order.append("second")
        raise RuntimeError("undo blew up")

    ledger.register("kind-a", "ref-a", lambda: order.append("first-made"))
    ledger.register("kind-b", "ref-b", _boom)
    errors = ledger.unwind()
    # LIFO: the later mutation is taken back first; its failure must not
    # stop the earlier one's undo from running.
    assert order == ["second", "first-made"]
    assert len(errors) == 1
    assert "kind-b ref-b" in errors[0] and "undo blew up" in errors[0]


def test_postflight_reports_what_the_probe_reads_not_what_undo_claims():
    r = _load_residue()
    still_there = ["uuid-9"]
    ledger = r.ResidueLedger(
        journey="x", probes=(r.ResidueProbe("row", lambda: list(still_there)),),
    )
    # An undo that "succeeds" (no exception) while removing nothing:
    ledger.register("row", "uuid-9", lambda: None)
    assert ledger.unwind() == []
    assert ledger.postflight() == ["row: uuid-9"], (
        "postflight must read the estate; a green undo is not evidence"
    )


# ── 2. Harness wiring ────────────────────────────────────────────────────────

def test_journey_factory_wires_preflight_unwind_and_postflight():
    src = CONFTEST_PY.read_text(encoding="utf-8")
    # Ordered: preflight before the start event is emitted; unwind +
    # postflight inside the finally; a leak raises on an otherwise-green run.
    preflight_at = src.find("ledger.preflight()")
    start_emit_at = src.find('"type": "e2e_journey_start"')
    unwind_at = src.find("ledger.unwind()")
    postflight_at = src.find("ledger.postflight()")
    raise_at = src.find("if passed_overall and leaked:")
    assert -1 not in (preflight_at, start_emit_at, unwind_at, postflight_at, raise_at), (
        "the journey factory lost part of its residue wiring "
        "(preflight / unwind / postflight / leak-raise)"
    )
    assert preflight_at < start_emit_at, (
        "preflight must run BEFORE the journey emits anything — residue from "
        "a crashed run fails the next run before it mutates"
    )
    assert unwind_at < postflight_at < raise_at, (
        "unwind, then re-read the estate, then fail the green run on a leak"
    )
    assert "def mutates(" in src, "JourneyRecorder.mutates() is the registration point"


def test_tester_identity_fixture_fails_over_orphans_before_minting_more():
    src = CONFTEST_PY.read_text(encoding="utf-8")
    fixture_at = src.find("def tester_identity(")
    provision_at = src.find("identity = provision_tester(tier)")
    probe_at = src.find("sweep_orphans(max_age_seconds=0, dry_run=True)")
    assert -1 not in (fixture_at, provision_at, probe_at), (
        "the orphan preflight left the tester_identity fixture — 60 "
        "nos-tester-e2e-* accounts is how its absence looks"
    )
    assert fixture_at < probe_at < provision_at, (
        "the orphan check must run inside the fixture BEFORE provisioning"
    )
    assert "dry_run=True" in src[probe_at:probe_at + 60], (
        "the preflight is a READER; deletion stays an operator act (A13.6)"
    )


# ── 3. The journey contract ──────────────────────────────────────────────────

#: What a mutation looks like in a journey file. csrf_post is Wing's only
#: state-changing browser path; a raw method="POST"/PUT/DELETE or an _api(...,
#: "POST") call is the agent path. GETs never register.
_MUTATION_MARKERS = re.compile(
    r'csrf_post\(|method="(POST|PUT|DELETE)"|_api\([^)]*"POST"',
)


def test_every_mutating_journey_registers_its_undos():
    journeys = sorted(JOURNEYS_DIR.glob("test_*.py"))
    assert journeys, f"no journeys under {JOURNEYS_DIR}"
    offenders = []
    for path in journeys:
        src = path.read_text(encoding="utf-8")
        if not _MUTATION_MARKERS.search(src):
            continue  # read-only journey — nothing to take back
        if "j.mutates(" not in src or "residue_probes=" not in src:
            offenders.append(path.name)
    assert not offenders, (
        f"journey(s) mutate the live estate without registering undos + "
        f"residue probes: {offenders}. 29 permanent HIGH inbox rows and 60 "
        "orphaned Authentik accounts are what this looks like two weeks "
        "later — register every mutation via j.mutates(...) the moment it "
        "is made, and give journey() residue_probes= so a crashed run's "
        "leak fails the NEXT run."
    )


def test_mutation_scanner_still_sees_the_known_mutators():
    # A regex gate you can defeat by breaking the regex is not a gate. The two
    # journeys KNOWN to mutate must always match; if a refactor renames the
    # helpers, this fails and the scanner gets updated with it.
    for name in ("test_approval_flow.py", "test_halt_resume.py"):
        src = (JOURNEYS_DIR / name).read_text(encoding="utf-8")
        assert _MUTATION_MARKERS.search(src), (
            f"{name} no longer matches the mutation scanner — update "
            "_MUTATION_MARKERS so the contract keeps reaching it"
        )
