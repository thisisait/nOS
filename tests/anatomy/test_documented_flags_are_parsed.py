"""A flag a tool documents must be a flag the tool reads.

MEASURED 2026-08-04, by being caught out by it.

`tools/roadmap-seed.py` carried `Usage: python3 tools/roadmap-seed.py
[--dry-run]` in its docstring and had NO argv handling whatsoever. A run
intended as a rehearsal therefore wrote 43 rows into the live KEAP roadmap
table, duplicating 38 slugs, and reported success while doing it. The flag was
not broken — it never existed. Only the sentence describing it did.

That is this estate's standing defect in its cheapest form: a claim with no
mechanism behind it. It has been found in a backup that reported success over
empty archives, a scan that stamped freshness without scanning, a container
that reported healthy while serving its own installer, and a notification
posted to a service that could not verify it. This one is smaller and easier to
prevent than any of those, which is why it is worth a gate.

WHY A PROPERTY, NOT A PIN. The narrow version of this test would assert that
roadmap-seed.py parses `--dry-run` — true, checkable, and worth almost nothing:
it generalises to no other file and a proposer can satisfy it without
understanding why. The property version asks of EVERY tool: is each flag you
advertise one you actually read? Passing that implies something about the whole
directory. (docs/doctrine/workflows.md §3: prefer the weakest gate that still
fails.)

WHAT IT CANNOT DO: it cannot tell whether the flag's behaviour is correct, only
whether the string reaches the code at all. A `--dry-run` that is parsed and
ignored still passes. That is a real limit and the reason the seeder's own
dry-run path was additionally exercised by hand.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools"

# `Usage:` blocks list flags as --like-this, sometimes [--optional].
_FLAG = re.compile(r"--[a-z][a-z0-9-]{1,30}")
# A usage line is the convention this repo already uses in tool docstrings.
_USAGE = re.compile(r"^\s*Usage[:\s]", re.IGNORECASE)


def _python_tools() -> list[Path]:
    if not TOOLS.is_dir():
        return []
    return sorted(p for p in TOOLS.rglob("*.py") if p.is_file())


def _documented_flags(source: str) -> set[str]:
    """Flags named in the module docstring's Usage section."""
    try:
        doc = ast.get_docstring(ast.parse(source)) or ""
    except SyntaxError:
        return set()
    flags: set[str] = set()
    in_usage = False
    for line in doc.splitlines():
        if _USAGE.match(line):
            in_usage = True
        elif in_usage and line.strip() and not line.startswith((" ", "\t")):
            # A new unindented paragraph ends the usage block.
            in_usage = False
        if in_usage:
            flags.update(_FLAG.findall(line))
    return flags


def _flags_the_code_reads(source: str, doc: str) -> set[str]:
    """Every flag string appearing OUTSIDE the docstring."""
    body = source.replace(doc, "", 1) if doc else source
    return set(_FLAG.findall(body))


def test_there_are_tools_to_check():
    """Positive control — an empty tools/ would satisfy everything below."""
    assert _python_tools(), "no python tools found under tools/"


@pytest.mark.parametrize("path", _python_tools(), ids=lambda p: p.name)
def test_every_documented_flag_is_parsed(path):
    """The defect, as the thing that must stay false."""
    source = path.read_text(encoding="utf-8", errors="ignore")
    documented = _documented_flags(source)
    if not documented:
        pytest.skip("no Usage: flags documented")

    try:
        doc = ast.get_docstring(ast.parse(source)) or ""
    except SyntaxError:
        pytest.skip("does not parse")

    read = _flags_the_code_reads(source, doc)
    phantom = sorted(documented - read)

    assert not phantom, (
        f"{path.relative_to(REPO)} documents {phantom} in its Usage line, and "
        f"the string appears nowhere in the code. Running the tool with that "
        f"flag does exactly what running it without would — which for a "
        f"--dry-run means a rehearsal writes to production. Either parse it or "
        f"stop advertising it."
    )
