"""A probe may not decide by counting lines of something written for a human.

WHAT HAPPENED, 2026-08-23. `sec-rem` is the roadmap's only row for the open
HIGH findings, and the roadmap is what dictates the order of work here. Its
probe was:

    test "$(python3 tools/rem-status.py | grep -c 'HIGH ')" -eq 0

`rem-status.py` renders for a person. Six of its lines contain `HIGH ` today
and only two are open findings; the other four are headings —

    pending by severity: 2 HIGH · 26 MEDIUM · 19 LOW
    6 CRITICAL/HIGH are BLOCKED, not fixed — no upstream remedy exists:
    REM-126   HIGH      ollama         mitigated
    +45 pending below HIGH — `--all` lists them.

— and three of those four survive every possible state of the queue. So the
probe could not reach 0 with every HIGH closed. It had read `contradicted`
since the day it was filed and would have gone on reading `contradicted` after
the work was finished: a gate that only ever reports its own defeat, which is
the same shape CLAUDE.md already records for the ruleset's signature rule
(`Found 188 violations`, bypassed on every release, never once satisfied).

The reader has had a `--json` mode the whole time. `pending_by_severity` answers
the question exactly, in one field, and moves to `{}` when the queue is clean.

WHY IT IS A GATE AND NOT A NOTE. This is the third form of the estate's oldest
defect inside the probe catalogue alone. `test_a_probe_cannot_match_its_own
_description.py` closed the first (a probe reading the PLAN and reporting it as
the work) and the second (a probe that cannot fail). This is its mirror: a probe
that cannot PASS. Both directions make `verified` a constant, and the column
exists so it can disagree with `status`.

WHAT IT ENFORCES. If a probe invokes one of this repo's readers and decides by
COUNTING that reader's output, the reader must have been asked in its machine
mode — when it has one. The condition matters: where no `--json` exists there is
no better option available, and a gate that demands one would be asking for a
tool that does not exist rather than for a probe that is correct.

WHAT IT CANNOT SEE. Whether the machine field a probe reads is the RIGHT field.
`pending_by_severity` excludes `vendor-blocked` rows, which is deliberate here —
six CRITICAL/HIGH carry recorded dispositions and are not open work — but no
gate can tell that choice from an oversight. That judgement stays with whoever
writes the probe.
"""

from __future__ import annotations

import re

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
PROBES = REPO / "state/roadmap-probes.yml"

#: The decision comes from a tally rather than from the reader's own verdict.
COUNTERS = (("grep", "-c"), ("wc", "-l"), ("wc", "-w"))


def commands() -> dict[str, str]:
    cat = yaml.safe_load(PROBES.read_text(encoding="utf-8")) or {}
    return {k: v for k, v in cat.items() if isinstance(v, str)}


#: A tool named as an ARGUMENT to one of these is being read as a file, not run.
READS_A_FILE = ("grep", "cat", "head", "tail", "test", "ls", "wc")

_INVOCATION = re.compile(r"(?:(\S+)\s+)?(tools/[\w.-]+\.py)((?:\s+-{1,2}[\w-]+)*)")


def _readers_invoked(cmd: str) -> list[tuple[str, str]]:
    """(tool, its flags) for this repo's tools the probe RUNS, not greps at.

    Works on the RAW string rather than on shlex tokens, because the shape this
    gate exists for hides inside a command substitution: shlex reads all of
    `"$(python3 tools/rem-status.py | grep -c 'HIGH ')"` as ONE token, so the
    tool path never appears on its own. The first cut of this gate did use
    tokens and passed the very probe it was written for.
    """
    found = []
    for lead, tool, flags in _INVOCATION.findall(cmd):
        if lead and lead.strip("\"'$(") in READS_A_FILE:
            continue
        if (REPO / tool).exists():
            found.append((tool, flags))
    return found


def _counts_output(cmd: str) -> bool:
    for head, flag in COUNTERS:
        if re.search(rf"\|\s*{head}\b[^|]*\s{re.escape(flag)}\b", cmd):
            return True
    return False


def _offers_json(tool: str) -> bool:
    src = (REPO / tool).read_text(encoding="utf-8")
    return '"--json"' in src or "'--json'" in src


def test_a_counted_reader_was_asked_in_its_machine_mode():
    offenders: list[str] = []
    for slug, cmd in commands().items():
        if not _counts_output(cmd):
            continue
        for tool, flags in _readers_invoked(cmd):
            if _offers_json(tool) and "--json" not in flags.split():
                offenders.append(
                    f"{slug}: counts lines of `{tool}` human output, "
                    f"though `{tool} --json` exists")
    assert not offenders, (
        "these probes decide by tallying prose, so a heading counts as a "
        "finding and the verdict cannot reach the state the row is waiting "
        "for:\n  " + "\n  ".join(offenders)
        + "\n(this is how sec-rem read `contradicted` from the day it was "
          "filed — four of the six lines its grep matched are headings that "
          "survive an empty queue)")


def test_the_reader_this_gate_was_written_for_still_answers_in_json():
    """The rule above is only fair while the machine half exists. If
    `rem-status.py` ever loses `--json`, the demand becomes unmeetable and this
    gate would be asking for a tool rather than for a correct probe."""
    assert _offers_json("tools/rem-status.py"), (
        "tools/rem-status.py no longer offers --json; the probe for sec-rem "
        "and this gate's premise both depend on it")
