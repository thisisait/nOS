"""A findings code must be a code nothing else can produce by accident.

MEASURED 2026-10-27: `discovery:contradiction-scan` crashed on 5 of 5 runs
from 2026-10-23 on, and nothing turned red. It declared
`findings_exit_codes: [1]`, and an uncaught Python exception exits 1 too — so
Wing, Grafana and `red-status.py` read every traceback as "found contradictions".
Seven jobs declared `[1]` and `loop:propose` declared `[1, 3]`.

THE RULE: a declared findings code is never 0, 1, 2 or >= 126. The estate's
findings code is 10; a second non-failure meaning takes 11 and up, documented
next to the constant that produces it.

WHY THESE: 0 is success. 1 is what Python exits on an uncaught exception and
what bash `set -e` exits on a failing command. 2 is argparse's usage error and
bash's builtin misuse. 126/127 are the shell's "cannot execute" / "not found"
(the Pulse runner reserves both), and 128+n is death by signal n. A crash in
any of those shapes must stay red, so none of them may mean "found something".
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _declarations():
    """(where, job, codes) for every pulse job that declares findings codes."""
    out = []
    for pattern in ("files/anatomy/plugins/*/plugin.yml",
                    "files/anatomy/agents/*/agent.yml",
                    "files/anatomy/loops/*.loop.yml"):
        for path in sorted(REPO.glob(pattern)):
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            pulse = doc.get("pulse") if isinstance(doc, dict) else None
            if not isinstance(pulse, dict):
                continue
            # A plugin lists jobs; an agent or loop manifest IS one job.
            for job in pulse.get("jobs") or [pulse]:
                codes = job.get("findings_exit_codes")
                if codes is not None:
                    name = job.get("name") or doc.get("id") or path.parent.name
                    out.append((str(path.relative_to(REPO)), name, codes))
    return out


def test_declarations_exist():
    """Positive control: with nothing declared the gate below is vacuous."""
    assert len(_declarations()) >= 8, _declarations()


def test_no_findings_code_is_a_crash_code():
    offenders = [f"{where}:{name} declares {codes}"
                 for where, name, codes in _declarations()
                 if any(not isinstance(c, int) or c <= 2 or c >= 126 for c in codes)]
    assert not offenders, (
        "a findings code collides with a crash code, so a job that dies reads "
        "as a job that found something (use 10; 11+ for a second meaning):\n  "
        + "\n  ".join(offenders))
