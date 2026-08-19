"""The suite's environment contract — absence is counted, promised presence is enforced.

Born 2026-08-19, the day the forge CI ran this suite for the first time and
exit-2'd on a COLLECTION error: three loop gates import fastapi at module
level, fastapi was not installed, and so THE ENTIRE SUITE HAD NEVER RUN in
that CI for the whole life of the loop engine. The same day found the estate's
signature defect four more times in unrelated components: a probe that goes
green by not asking. A `skipif(which("x") is None)` is that defect one layer
up — CI goes green because the binary is absent, forever, silently.

Two rules close it:

  1. PROMISED PRESENCE IS ENFORCED. An environment that is SUPPOSED to run the
     php/jq/ansible-gated gates declares so via the env var NOS_TEST_PROVIDES
     (comma-separated tool names). If a declared tool does not resolve on
     PATH, the whole session ABORTS before a single test runs — a runner
     image quietly dropping a tool must never demote a hundred gates into
     skips that nobody reads.
  2. UNDECLARED ABSENCE IS COUNTED. Every skip is grouped by reason and
     printed as its own outcome in the terminal summary, with the declaration
     (or its absence) named. A skip may be honest; an unreported one is not.

The declarations live in the CI configs (.woodpecker/tests.yml environment
block, .github/workflows/ci.yml pytest job env) and are pinned — together
with this mechanism's own failure branch — by
tests/anatomy/test_absence_is_counted.py.

conftest.py calls enforce_contract() at import time (so it cannot be bypassed
per-test) and re-exports pytest_terminal_summary from here.
"""

from __future__ import annotations

import os
import shutil

ENV_VAR = "NOS_TEST_PROVIDES"


def declared_tools(environ: dict | None = None) -> list[str]:
    raw = (environ if environ is not None else os.environ).get(ENV_VAR, "")
    return [t.strip() for t in raw.split(",") if t.strip()]


def broken_promises(environ: dict | None = None, which=shutil.which) -> list[str]:
    """Tools the environment PROMISED that do not resolve on PATH."""
    return [t for t in declared_tools(environ) if which(t) is None]


def enforce_contract() -> None:
    """Abort the session if the environment breaks its own declaration.

    Raised at conftest IMPORT time so no test — passing, skipping, or
    otherwise — ever runs in an environment that lied about itself.
    """
    missing = broken_promises()
    if missing:
        import pytest

        raise pytest.UsageError(
            f"ENVIRONMENT CONTRACT BROKEN: {ENV_VAR} declares "
            f"{', '.join(missing)} but the tool(s) do not resolve on PATH. "
            "This environment is supposed to run the gates that need them; "
            "running without would silently demote those gates to skips. "
            "Fix the environment (or its declaration in the CI config) — "
            "do not delete the declaration to go green."
        )


def _skip_reason(report) -> str:
    longrepr = getattr(report, "longrepr", None)
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        msg = str(longrepr[2])
    else:
        msg = str(longrepr)
    return msg.removeprefix("Skipped: ").strip() or "(no reason given)"


def skip_census(skipped_reports) -> dict[str, int]:
    census: dict[str, int] = {}
    for rep in skipped_reports:
        reason = _skip_reason(rep)
        census[reason] = census.get(reason, 0) + 1
    return dict(sorted(census.items(), key=lambda kv: (-kv[1], kv[0])))


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:  # noqa: ARG001
    """ALWAYS printed, even when zero gates skipped — a report that only
    appears on bad days is a report whose disappearance nobody notices."""
    tr = terminalreporter
    declared = declared_tools()
    tr.write_sep("-", "absence report (a skip is an outcome, not a pass)")
    if declared:
        tr.write_line(f"environment declares it provides: {', '.join(declared)} "
                      "(each was verified present before any test ran)")
    else:
        tr.write_line(f"{ENV_VAR} is UNSET — this environment promises nothing, "
                      "so nothing enforces that the tool-gated gates ran here. "
                      "CI environments must declare; see tests/anatomy/_environment_contract.py.")
    census = skip_census(terminalreporter.stats.get("skipped", []))
    if not census:
        tr.write_line("0 gates were absent: every collected gate ran.")
        return
    total = sum(census.values())
    tr.write_line(f"{total} gate(s) did NOT run here, counted by reason:")
    for reason, n in census.items():
        tr.write_line(f"  {n:4d} × {reason}")
