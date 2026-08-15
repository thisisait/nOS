"""`launchctl bootout` is asynchronous. Bootstrapping into it kills the daemon.

MEASURED 2026-08-15, twice, on the live estate — and reproduced deliberately
afterwards to be sure it was the cause and not a coincidence:

    $ launchctl bootout gui/501/eu.thisisait.nos.wing 2>/dev/null || true
    $ launchctl bootstrap gui/501 "$PLIST"
    Bootstrap failed: 5: Input/output error          rc=5
    -> job NOT LOADED, port 9000 dead

    $ launchctl bootout ... ; sleep 1 ; launchctl bootstrap ...
    rc=0                                             -> HTTP 403, running

WHY IT HID. The reload path only runs when a plist actually CHANGES, so a
steady-state converge takes the `kickstart` branch and never races. When it
did fire, every layer swallowed it: `bootout` redirects its own stderr and
`|| true`s, the enclosing task is `failed_when: false` (deliberately — the
health probe below it owns the verdict), and that probe is `failed_when: false`
too. So Wing went down and the converge continued; the first loud failure was
a Pulse job registration three tasks later reporting `Connection refused`,
blaming a connection it had no part in breaking. The health probe in between
reported `ok` while receiving that same refusal.

IT WAS A CLASS, NOT AN INCIDENT. Four reload sites across three host daemons:
`bone/tasks/post.yml` and `bone/tasks/main.yml`'s canary reload had the sleep;
`wing/tasks/main.yml`, `bone/tasks/main.yml` and `pulse/tasks/main.yml` did
not. Pulse losing this race is the worst of them — nothing else fires the
scheduled jobs, so the estate would just stop having nights.

WHAT THIS PINS: every `launchctl bootout` that is followed by a `bootstrap` in
the same shell block must have something between them. Keyed on the shell
source, so a new organ copied from an old one is covered on the day it lands.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLES = REPO / "roles"

#: bootout … bootstrap with nothing but blank/comment lines between them.
RACE = re.compile(
    r"launchctl\s+bootout[^\n]*\n"          # the bootout
    r"(?:\s*(?:#[^\n]*)?\n)*"               # only blanks/comments may intervene
    r"\s*launchctl\s+bootstrap",
)


#: Where a shell block starts. Anything reached after a `msg:` that opened
#: later is operator-facing PROSE — `pazny.openclaw` documents the manual
#: recovery inside a `fail:` message, and the first draft of this gate flagged
#: it as a defect. A gate that reads instructions-for-humans as code is the
#: same mistake in the other direction.
EXECUTORS = ("ansible.builtin.shell", "ansible.builtin.command", "shell:", "command:")
PROSE = ("ansible.builtin.fail", "ansible.builtin.debug", "msg:")


def _shell_files() -> list[pathlib.Path]:
    out = []
    for path in sorted(ROLES.glob("pazny.*/tasks/*.yml")):
        if "launchctl bootout" in path.read_text(encoding="utf-8"):
            out.append(path)
    return out


def _is_executed(text: str, at: int) -> bool:
    head = text[:at]
    last_exec = max((head.rfind(tok) for tok in EXECUTORS), default=-1)
    if last_exec < 0:
        return False
    return not any(head.rfind(p) > last_exec for p in PROSE)


def test_the_sweep_finds_the_organs_that_reload_themselves():
    """Positive control: no files means no assertions, which is how a gate
    against a whole class quietly stops guarding it."""
    files = _shell_files()
    names = {p.parent.parent.name for p in files}
    assert len(files) >= 3, (
        f"only {len(files)} task file(s) contain `launchctl bootout`; the "
        "sweep has stopped seeing the host daemons it guards (wing, bone, "
        "pulse on 2026-08-15)."
    )
    assert {"pazny.wing", "pazny.bone", "pazny.pulse"} <= names, (
        f"the three host daemons are not all in the sweep; found {sorted(names)}"
    )


def test_no_bootout_is_immediately_followed_by_a_bootstrap():
    offenders = []
    for path in _shell_files():
        text = path.read_text(encoding="utf-8")
        for match in RACE.finditer(text):
            if not _is_executed(text, match.start()):
                continue
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"  {path.relative_to(REPO)}:{line}")
    assert not offenders, (
        "`launchctl bootstrap` fires immediately after a `bootout` in the same "
        "block. bootout is asynchronous: the bootstrap races the teardown, "
        "returns `5: Input/output error`, and leaves the daemon DOWN — "
        "silently, because bootout swallows its errors and the enclosing tasks "
        "are failed_when:false. Put a `sleep 1` between them:\n"
        + "\n".join(offenders)
    )


#: A RELOAD: bootout, then (anything short) then bootstrap. Only these matter
#: for the check below — the FIRST bootstrap of a job that is not running is
#: legitimately fire-and-forget, because there is nothing to lose.
RELOAD = re.compile(
    r"launchctl\s+bootout[^\n]*\n(?:[^\n]*\n){0,4}?\s*launchctl\s+bootstrap[^\n]*"
)


def test_a_reload_that_fails_to_bootstrap_says_so():
    """rc=5 with no output is how a dead daemon reads as a green converge.

    Not a `failed_when` — the health probe after it owns that verdict — but a
    reload must not exit silently, or the diagnostic task downstream has
    nothing to explain and the next loud error names an innocent bystander
    (here: a Pulse registration blaming a connection it never broke).

    An earlier draft asserted `len(silent) <= 6` — a number chosen to match
    what happened to be there rather than measured against anything. It is
    replaced by the precise question: of the RELOAD sites, do any swallow the
    bootstrap's exit code?
    """
    silent = []
    for path in _shell_files():
        text = path.read_text(encoding="utf-8")
        for match in RELOAD.finditer(text):
            if not _is_executed(text, match.start()):
                continue
            if "BOOTSTRAP-FAILED" in match.group(0) or "||" in match.group(0).split("bootstrap")[-1]:
                continue
            line = text[: match.start()].count("\n") + 1
            silent.append(f"  {path.relative_to(REPO)}:{line}")
    assert not silent, (
        "a RELOAD swallows its bootstrap's exit code. When the race is lost the "
        "command returns 5 and prints nothing, so the converge walks on with the "
        "daemon down:\n" + "\n".join(silent)
    )
