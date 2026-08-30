"""The estate may not name a macOS grant it does not have.

MEASURED 2026-08-30 with `tools/permission-status.py --grants`, which
correlates the TCC subsystem's own request/verdict pairs out of the system log:

    com.docker.docker    SystemPolicyAllFiles         DENIED  x16
    ghostty (terminal)   SystemPolicyAllFiles         DENIED  x34
    restic, python, node SystemPolicyAllFiles         DENIED
    docker, ghostty, …   SystemPolicyRemovableVolumes ALLOWED

`roles/pazny.backup/files/backup.sh` justified routing the keap-db backup
through the container with *"Docker Desktop holds the grant"*, and
`defaults/main.yml` restated it. Docker does not hold Full Disk Access; it is
refused it. What it holds is Removable Volumes — and since `/Volumes/SSD1TB` is
a removable volume, that is the grant the path actually needs.

**The route was right and the reason on the label was wrong**, which is the
expensive kind of wrong: the next person to reason from it concludes that
anything Docker can reach is FDA-reachable, and designs a path that fails.

The same file claimed the host fallback "works when the process running this
script HAS Full Disk Access (an interactive Terminal.app does)". On this host
the terminal is refused FDA 34 times in two days. The fallback works from a
shell for the *other* reason — Removable Volumes again.

WHAT THIS GATE CAN AND CANNOT DO. It cannot verify a grant; no test can, because
neither TCC database is readable without the grant being tested. What it can do
is refuse the two specific sentences that were measured false, and require that
anything asserting a grant points at the reader instead of restating a
remembered fact. That is the same rule the estate applies to the security queue
and the plugin-wiring tally: do not carry a moving value in prose.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools/permission-status.py"

#: Sentences measured false on 2026-08-30. Each maps to what is actually true.
REFUTED = {
    "Docker Desktop holds the grant":
        "Docker is refused SystemPolicyAllFiles; it holds RemovableVolumes",
    "Docker Desktop does have the grant":
        "same claim, restated in defaults/main.yml",
    "an interactive Terminal.app does":
        "the terminal is refused Full Disk Access 34x in two days",
}

SEARCH = ("roles", "tasks", "files/anatomy", "docs", "tools", "main.yml")


def _files() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for rel in SEARCH:
        base = REPO / rel
        if base.is_file():
            out.append(base)
            continue
        for p in base.rglob("*"):
            if (p.is_file() and p.suffix in {".sh", ".yml", ".yaml", ".py", ".md", ".j2"}
                    and "node_modules" not in p.parts and "vendor" not in p.parts
                    and "archive" not in p.parts):
                out.append(p)
    return out


def test_the_reader_exists_and_cannot_write() -> None:
    """A permission checker that could change a permission is a different and
    much more dangerous tool."""
    assert TOOL.is_file(), "tools/permission-status.py is gone"
    src = TOOL.read_text(encoding="utf-8")
    for forbidden in ("tccutil", "sqlite3 TCC.db", "sudo ", "open -a 'System Settings'"):
        assert forbidden not in src, f"the reader tries to {forbidden!r}"


#: Words that turn a refuted sentence into a CITATION of one. Third time in a
#: day that a text detector here flagged the correction rather than the error
#: (see test_agent_memory_does_not_return and test_backup_reaches_the_brain) —
#: the reader's own docstring quotes "Docker Desktop holds the grant" to say it
#: was wrong, and a gate that forbids writing that sentence forbids recording
#: why it was wrong.
CITED = re.compile(r"wrong|corrected|refuted|measured false|it does not|"
                   r"was not|used to say|is refused", re.I)


def test_no_file_repeats_a_refuted_claim() -> None:
    offenders = []
    for path in _files():
        if path == pathlib.Path(__file__):
            continue
        body = path.read_text(encoding="utf-8", errors="replace")
        for claim, truth in REFUTED.items():
            for m in re.finditer(re.escape(claim), body):
                window = body[max(0, m.start() - 500):m.end() + 500]
                if CITED.search(window):
                    continue          # quoted in order to correct it
                offenders.append(f"{path.relative_to(REPO)}: {claim!r} — {truth}")
    assert not offenders, (
        "a measured-false claim about a macOS grant is back in the tree:\n  "
        + "\n  ".join(offenders)
        + "\nAsk `tools/permission-status.py --grants`; do not restate a grant "
          "from memory. The route these sentences defend may still be correct — "
          "it is the REASON that was wrong, and reasoning from it designs the "
          "next path badly.")


def test_the_reader_states_the_per_binary_rule() -> None:
    """The single fact that makes every probe here interpretable. Without it a
    green run reads as "the estate is fine" when it only means "your terminal
    is fine", and the launchd agents are the half that actually runs unattended."""
    src = TOOL.read_text(encoding="utf-8")
    assert "belongs to a BINARY" in src and "launchd" in src, (
        "the reader no longer says that a grant is per-binary — its output "
        "becomes unreadable without that, because every probe speaks only for "
        "the interpreter that ran it")


def test_it_does_not_raise_a_dialog_unasked() -> None:
    """The tool exists because a dialog stalls the estate. One that pops one on
    every run would be self-defeating; the Apple Events probe is opt-in."""
    src = TOOL.read_text(encoding="utf-8")
    assert "NOS_PERM_PROBE_AUTOMATION" in src, "the automation probe is no longer opt-in"
    # INVOCATIONS, not mentions: the string also appears as a subject label and
    # in prose. `_run(["osascript"` is the only shape that executes one.
    calls = re.findall(r'_run\(\s*\[\s*"osascript"', src)
    assert len(calls) <= 1, (
        f"{len(calls)} osascript invocations — each one can raise an Automation "
        "dialog, and only the guarded one may exist")
    assert calls, "the guarded automation probe is gone entirely"
