"""The supervised-run wrapper must refuse a half environment, not improvise one.

MEASURED 2026-08-16, running the first supervised AgentKit night. The
documented entry point `bin/run-agent.php` cannot work from a shell: the
daemon's environment lives in the launchd plist and a terminal inherits none of
it. Three failures in a row, each naming the wrong thing:

  * no `NOS_REPO_ROOT` -> the DI container dies with
    `MigrationWriteTool::__construct(): Argument #1 must be of type string,
    false given` — because `::getenv()` yields FALSE for unset, while
    common.neon's own comment promises "empty -> the tool fail-softs". A
    fail-soft that cannot happen.
  * no `NOS_ARMED_BACKENDS` -> a BOUND agent resolves UNBOUND and reports
    `ANTHROPIC_API_KEY missing`. The binding was fine; it was never armed in
    that process.
  * no tier model env -> the resolver refuses correctly, and confusingly.

Each error pointed somewhere other than the cause, which is the expensive kind.
The wrapper exists so the refusal happens BEFORE a session opens and spends.

WHAT IS PINNED: that it refuses rather than defaults, that it reads the RUNNING
job (`launchctl print`) rather than the plist file — those differ exactly when
a converge has rendered a variable the daemon has not reloaded, which is the
drift `roles/pazny.wing` documents — and that `--show-env` redacts.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
WRAPPER = REPO / "tools/run-agent.sh"


def _src() -> str:
    return WRAPPER.read_text(encoding="utf-8")


def test_the_wrapper_exists_and_is_executable():
    assert WRAPPER.is_file(), "tools/run-agent.sh is gone"
    assert WRAPPER.stat().st_mode & 0o111, "run-agent.sh is not executable"


def test_it_is_valid_shell():
    res = subprocess.run(["bash", "-n", str(WRAPPER)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_it_reads_the_running_job_not_the_plist_file():
    """The file is what the daemon WILL have; the job is what it HAS."""
    src = _src()
    assert "launchctl print" in src, (
        "the wrapper no longer reads the running job. Reading the plist file "
        "instead would export values the daemon has not loaded — the exact "
        "drift roles/pazny.wing carries a comment about."
    )
    assert "plutil" not in src and "plistlib" not in src, (
        "the wrapper parses the plist FILE. That is the copy that can be ahead "
        "of the process; the child would then run with an environment the "
        "daemon itself does not have."
    )


def test_a_missing_required_variable_refuses():
    src = _src()
    assert re.search(r"REFUSING", src), "the wrapper no longer refuses anything"
    body = src[src.index("missing=()"):]
    assert "exit 1" in body, (
        "a missing required variable no longer aborts. Defaulting it would "
        "reproduce exactly the three failures this wrapper was written for."
    )
    assert "NOS_REPO_ROOT" in src, "the variable whose absence is a TypeError is not required"


def test_show_env_redacts_secrets():
    """It prints an environment that includes bearer tokens."""
    src = _src()
    assert re.search(r"\*TOKEN\|\*SECRET\|\*KEY", src), (
        "--show-env no longer has a redaction branch for credential-shaped "
        "names; it prints WING_API_TOKEN among others."
    )
    assert "chars" in src, "the redaction no longer reports a length instead of a value"


def test_it_announces_the_backend_before_spending():
    """A supervised run is supervised only if the operator can see, before the
    spend, which third party is about to receive the prompt."""
    src = _src()
    idx_exec = src.index("exec php bin/run-agent.php")
    announce = src.rindex("armed backends", 0, idx_exec)
    assert announce < idx_exec, "the backend is announced after the run starts"
