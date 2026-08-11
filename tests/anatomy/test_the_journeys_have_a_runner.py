"""Anatomy gate: a test suite nothing can run is not a suite.

MEASURED 2026-08-11. `tests/e2e/journeys/` holds ten end-to-end journeys — the
only tests in this repository that exercise Wing, Authentik and the event
lineage against a real estate — and NOTHING ran them:

  * `.github/workflows/ci.yml` passes `--ignore=tests/e2e`, correctly: a GitHub
    runner has no Wing, no Authentik, no estate.
  * no playbook tag invokes them, no Pulse job schedules them.
  * bare `pytest tests/e2e` produces false results, because `tests/e2e/lib/`
    reads eight environment variables across four modules and silently falls
    back when they are absent — `authentik_login` to the `dev.local` tenant,
    which is not this estate.

So they ran when a person typed the right half-dozen exports, and otherwise
never. Two consequences, both found the day this gate was written:

  1. `ApprovalsPresenter` was retired 2026-08-08. Every anatomy gate was updated
     the same day. `test_approval_flow.py` kept walking `/approvals` and nothing
     said so for three days.
  2. `test_operator_login.py` had SKIPPED on every run anyone had ever done,
     for the whole life of the file, because of the `dev.local` fallback. Its
     skip line read like an unavailable dependency and was in fact a test that
     had never once executed.

WHAT THIS PINS. That a runner exists, that it resolves the estate's own values
rather than carrying a second copy of them, and that it refuses to call a
configuration-skip a pass. It deliberately does NOT run the journeys — they need
a live estate, and this gate must stay green on a laptop with nothing up.

WHAT IT CANNOT DO: make anyone run it. Scheduling `tools/run-journeys.sh` on a
Pulse cadence is the next step and is not done; until then this is a suite that
CAN run rather than one that DOES.
"""

from __future__ import annotations

import pathlib
import re
import stat

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNNER = REPO / "tools/run-journeys.sh"
JOURNEYS = REPO / "tests/e2e/journeys"
CI = REPO / ".github/workflows/ci.yml"


def test_the_runner_exists_and_is_executable() -> None:
    assert RUNNER.is_file(), (
        "tools/run-journeys.sh is gone. Without it the e2e journeys are back to "
        "'runs only when someone remembers eight environment variables', which "
        "is how test_operator_login skipped for its entire life."
    )
    mode = RUNNER.stat().st_mode
    assert mode & stat.S_IXUSR, "the runner is not executable"


def test_ci_still_ignores_the_journeys_so_the_runner_is_the_only_path() -> None:
    """Guard the premise. If CI starts running them, this gate's reason changes.

    Not an argument that CI SHOULD ignore them — it should, there is no estate
    on a runner. But if that ever changes, whoever changes it should be told
    that a second execution path now exists, rather than leaving two.
    """
    text = CI.read_text(encoding="utf-8")
    assert "--ignore=tests/e2e" in text, (
        "CI no longer ignores tests/e2e. Either a runner-side estate now exists "
        "(good — reconsider this whole gate) or the journeys are about to fail "
        "every build for want of a Wing."
    )


def test_the_runner_reads_the_estate_rather_than_hard_coding_it() -> None:
    """A second copy of the tenant domain is a third place for it to be wrong.

    The specific failure this prevents: the runner exporting `dev.local`, which
    is exactly what the library fallback already did.
    """
    src = RUNNER.read_text(encoding="utf-8")
    assert "config.yml" in src and "secrets.yml" in src, (
        "the runner no longer reads the config layers and ~/.nos/secrets.yml. "
        "Whatever it exports instead is a copy, and copies drift."
    )
    # `dev.local` may appear as the documented FALLBACK inside the resolver and
    # in prose; it must not be what the runner exports as the tenant.
    exports = [
        line for line in src.splitlines()
        if re.match(r"\s*(export\s+)?(NOS_HOST|TENANT_DOMAIN)\s*=", line)
    ]
    for line in exports:
        assert "dev.local" not in line, (
            f"the runner hard-codes a tenant: {line.strip()!r}. It must come "
            "from the resolved config, or every journey silently targets an "
            "estate that is not this one."
        )


def test_a_configuration_skip_is_not_reported_as_a_pass() -> None:
    """The design point, and the estate's oldest rule wearing new clothes.

    A journey that skips because Wing is down is news about the estate. One that
    skips because nobody exported NOS_HOST is a test switched off by accident,
    and counting it in '0 failed' is how it stays off.
    """
    src = RUNNER.read_text(encoding="utf-8")
    assert "REFUSING" in src, (
        "the runner lost its refusal. A skip that names missing configuration "
        "must fail the run — otherwise the suite reports success for tests it "
        "never executed, which is the whole defect being fixed here."
    )
    assert "SKIPPED" in src, "the runner no longer inspects skip lines at all"


def test_every_journey_is_reachable_by_the_runner() -> None:
    """No journey outside the directory the runner points at."""
    assert JOURNEYS.is_dir(), "tests/e2e/journeys is gone"
    found = sorted(p.name for p in JOURNEYS.glob("test_*.py"))
    assert found, "there are no journeys left — delete the runner and this gate"
    src = RUNNER.read_text(encoding="utf-8")
    assert "tests/e2e/" in src, (
        f"the runner does not point at tests/e2e/, so these {len(found)} "
        "journeys are unreachable again."
    )


def test_no_journey_still_walks_the_retired_approvals_surface() -> None:
    """The specific rot that motivated all of this, pinned by name.

    `/approvals/approve/<id>` and `/approvals/reject/<id>` died with
    ApprovalsPresenter on 2026-08-08. `/approvals` itself survives as a
    permanent redirect, so a journey may still GET it — but a journey POSTing a
    verb route is walking a surface that no longer exists.
    """
    offenders = []
    for path in JOURNEYS.glob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        for verb in ("/approvals/approve", "/approvals/reject"):
            if verb in text:
                offenders.append(f"{path.name} -> {verb}")
    assert not offenders, (
        f"journey(s) still target the retired A11 verb routes: {offenders}. "
        "Approvals are kind='approval' rows in agent_questions now, decided via "
        "POST /inbox/answer/<uuid>. See RouterFactory's retirement note."
    )
