"""A chained audit log may not be appended to by a writer that cannot sign.

MEASURED 2026-08-16, found 2026-08-18. `bin/run-agent.php` invoked from a
shell inherits none of the Wing daemon's launchd environment, so
`WING_AUDIT_CHAIN_ENABLED` was unset. `EventRepository::insert` reads that
variable to decide whether to sign, an absent variable reads as "this estate
has no chain", and the librarian appended **37 unsigned rows** to a database
holding 337k signed ones. Every night since:

    audit-chain-verify  rc=2
    {"ok":false,"checked":337462,"unsigned":37,
     "first_break":{"why":"segment start prev_hash neither genesis nor anchor"}}

Nothing failed. The inserts succeeded, the agent exited 0, and the
tamper-evident log stopped being tamper-evident — the one failure the control
exists to prevent, reached by a missing environment variable.

TWO CHANGES, and the second is the one that matters:

1. `EventRepository::insert` no longer asks the ENVIRONMENT whether this
   estate is chained. It asks the DATABASE — if the table holds a signed row,
   this log is chained, and an unsigned append is corruption rather than a
   legacy insert. A caller cannot misconfigure that. Chain-off estates are
   untouched: they have no signed row to find.

2. `AuditEmitter` stops swallowing it. It catches `\\Throwable` and continues,
   which is right for a transient insert failure — a hole in the trail is
   survivable — and wrong for this: the run is producing history nobody can
   verify, and each further row buries the break deeper. `UnchainedAuditWrite`
   exists to be told apart, and is rethrown.

The estate's own rule (`docs/hidden_fees/07`): a step that cannot do its job
must not exit 0. An agent that cannot be audited cannot do its job.

WHAT THIS GATE CANNOT DO: repair the existing break. Re-anchoring a
tamper-evident log is an operator act, deliberately outside every agent's
reach. The 37 rows are still there and the nightly verify still fails; what
changed is that a 38th cannot be added.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
REPOSITORY = REPO / "files/anatomy/wing/app/Model/EventRepository.php"
EMITTER = REPO / "files/anatomy/wing/app/AgentKit/Telemetry/AuditEmitter.php"
EXCEPTION = REPO / "files/anatomy/wing/app/Model/UnchainedAuditWrite.php"


def test_the_files_this_gate_describes_exist():
    """Positive control — a renamed writer makes every check below vacuous."""
    for path in (REPOSITORY, EMITTER, EXCEPTION):
        assert path.is_file(), f"{path.relative_to(REPO)} is gone"
    assert "function insert(" in REPOSITORY.read_text(encoding="utf-8")


def test_the_unsigned_path_asks_the_database_not_the_environment():
    src = REPOSITORY.read_text(encoding="utf-8")
    assert "row_hash IS NOT NULL LIMIT 1" in src, (
        "the unsigned-insert path no longer probes the table for a signed row. "
        "Whether this estate is chained would once again be answered by an env "
        "var, and an env var a caller forgot to export reads as 'no chain'."
    )
    assert "UnchainedAuditWrite(" in src, (
        "the unsigned append no longer throws the typed refusal; a caller "
        "cannot distinguish corruption from a disk error."
    )


def test_the_refusal_comes_after_the_signing_branch():
    """Order matters: the check must guard the FALLTHROUGH, not the signed
    path. Placed above, it would refuse every write on a chained estate —
    including the correctly signed ones."""
    src = REPOSITORY.read_text(encoding="utf-8")
    signing = src.index("WING_AUDIT_CHAIN_ENABLED")
    refusal = src.index("UnchainedAuditWrite(")
    assert signing < refusal, (
        "the unsigned-append refusal now precedes the signing branch, so a "
        "chained estate would refuse its own valid writes."
    )


def test_the_emitter_rethrows_a_chain_refusal():
    src = EMITTER.read_text(encoding="utf-8")
    assert "catch (UnchainedAuditWrite" in src, (
        "AuditEmitter no longer distinguishes the chain refusal from an "
        "ordinary insert failure. Its \\Throwable catch would swallow it and "
        "the agent would run to completion writing unverifiable history — "
        "exactly the 2026-08-16 shape."
    )
    body = src[src.index("catch (UnchainedAuditWrite"):]
    body = body[: body.index("catch (\\Throwable")]
    assert "throw $exc;" in body, (
        "the chain refusal is caught but not rethrown, which is worse than not "
        "catching it: it reads as handled."
    )


def test_the_transient_case_is_still_survivable():
    """The counterweight. If the emitter starts crashing on every insert
    failure, a full disk takes the agent down instead of leaving a hole in
    the trail — and this gate would have traded one silent failure for one
    loud unnecessary one."""
    src = EMITTER.read_text(encoding="utf-8")
    assert "catch (\\Throwable $exc)" in src, "the transient-failure catch is gone"
    tail = src[src.index("catch (\\Throwable $exc)"):]
    assert "error_log(" in tail and "throw" not in tail.split("}")[0], (
        "the generic catch now rethrows too; a transient insert failure should "
        "leave a hole in the trail, not end the run."
    )


def test_the_exception_is_narrow_enough_to_be_meaningful():
    """A refusal class that also covers transient failures would defeat the
    asymmetry the emitter depends on."""
    src = EXCEPTION.read_text(encoding="utf-8")
    assert re.search(r"final class UnchainedAuditWrite extends \\RuntimeException", src), (
        "UnchainedAuditWrite is no longer a narrow final class; if it widens, "
        "AuditEmitter's rethrow starts catching failures that should be holes."
    )
