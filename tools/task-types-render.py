#!/usr/bin/env python3
"""Render AGENTS.md — the task-type contract — from state/task-types.yml.

state/task-types.yml is the ONE source (the enum lives in code, §14.2). AGENTS.md
is what a "dumber" agent reads FIRST: for its row's task_type, which tools, does
it write, does it need the operator, what is "done". Generating it here means the
page can never drift from the contract; its three invariants are quoted from
CLAUDE.md at render time, so the charter stays the one text — the gate
(tests/anatomy/test_task_types_contract.py) runs `--check` and fails on drift.

    tools/task-types-render.py            # write AGENTS.md
    tools/task-types-render.py --check    # exit 1 if AGENTS.md != render (no write)
"""

from __future__ import annotations

import os
import sys

import yaml

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC = os.path.join(_REPO, "state", "task-types.yml")
_OUT = os.path.join(_REPO, "AGENTS.md")
_CHARTER = os.path.join(_REPO, "CLAUDE.md")

_HEADER = """<!-- GENERATED from state/task-types.yml by tools/task-types-render.py — do not edit by hand. -->
# AGENTS.md — the task-type contract

Every row on the board carries a **`task_type`**. A row is a *claim*; its
task_type is the tiny contract for HOW to work it. Read your row's type below,
reach for its tools, and end it with its evidence — nothing more.

This page is the task-type contract. The full estate reference is [CLAUDE.md](CLAUDE.md); the
machine-readable source of this table is
[`state/task-types.yml`](state/task-types.yml). Adding or changing a type is a
**proposal** through the loop, not a free edit.

**Before anything else, read "Working in nOS" at the top of
[CLAUDE.md](CLAUDE.md)** — the charter every agent here works under; it is kept
in that one place.

## Three invariants that outrank every task type

Quoted from [CLAUDE.md](CLAUDE.md) at render time.

{invariants}

## The types
"""


def _section(text: str, heading: str) -> str:
    """The body under a `## heading` line, up to the next `## ` (imprint-gen.py's)."""
    return text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


def _invariants() -> str:
    """The charter's three invariants, verbatim, from CLAUDE.md."""
    charter = open(_CHARTER, encoding="utf-8").read()
    bullets = _section(charter, "Working in nOS").split("\n- ")
    one = next(b for b in bullets if b.startswith("Success is written by"))
    gates = _section(charter, "Gates and evidence").split(". ")[0] + "."
    repo = " ".join(_section(charter, "The repo is not the running system").strip().split("\n\n")[0].split())
    repo = repo[:repo.index('never "what is running"')] + 'never "what is running"'
    items = [" ".join(s.split()) for s in (one, gates, repo)]
    return "\n".join(f"{n}. {s}" for n, s in enumerate(items, 1))


def _render(doc: dict) -> str:
    types = doc["task_types"]
    out = [_HEADER.format(invariants=_invariants())]
    for name, c in types.items():
        writes = c["writes"]
        op = "operator-run" if c["needs_operator"] else "agent-run"
        tools = ", ".join(f"`{t}`" for t in c["tools"])
        out.append(f"### `{name}` — {c['summary']}")
        out.append("")
        out.append(f"- **tools**: {tools}")
        out.append(f"- **writes**: {writes} · **{op}**")
        out.append(f"- **done**: {c['done'].strip()}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    with open(_SRC, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    rendered = _render(doc)
    if "--check" in sys.argv:
        current = open(_OUT, encoding="utf-8").read() if os.path.exists(_OUT) else ""
        if current != rendered:
            print("AGENTS.md is STALE — run tools/task-types-render.py", file=sys.stderr)
            return 1
        print("AGENTS.md in sync with state/task-types.yml")
        return 0
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write(rendered)
    print(f"wrote {os.path.relpath(_OUT, _REPO)} ({len(doc['task_types'])} types)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
