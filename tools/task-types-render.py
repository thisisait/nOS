#!/usr/bin/env python3
"""Render AGENTS.md — the minimalistic task-type router — from state/task-types.yml.

state/task-types.yml is the ONE source (the enum lives in code, §14.2). AGENTS.md
is what a "dumber" agent reads FIRST: for its row's task_type, which tools, does
it write, does it need the operator, what is "done". Generating it here means the
router can never drift from the contract — the gate
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

_HEADER = """<!-- GENERATED from state/task-types.yml by tools/task-types-render.py — do not edit by hand. -->
# AGENTS.md — the task-type router

Every row on the board carries a **`task_type`**. A row is a *claim*; its
task_type is the tiny contract for HOW to work it. Read your row's type below,
reach for its tools, and end it with its evidence — nothing more.

This is the router. The full estate reference is [CLAUDE.md](CLAUDE.md); the
machine-readable source of this table is
[`state/task-types.yml`](state/task-types.yml). Adding or changing a type is a
**proposal** through the loop, not a free edit.

## Three invariants that outrank every task type

1. **Success is written by a READER, not by the thing that attempted the work.**
   A backup that reports its own success, a gate you can pass by editing the
   gate, a queue row that marks itself done — all lie. Prove it from the outside.
2. **Run the gate against the BROKEN state too.** A check that cannot fail on the
   pre-fix tree pins nothing.
3. **The repo is not the running system.** Source lives here; the estate runs
   from elsewhere and converges only on an operator's `nos`. A git ref answers
   "what is in the repo", never "what is running".

## The types
"""


def _render(doc: dict) -> str:
    types = doc["task_types"]
    out = [_HEADER]
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
