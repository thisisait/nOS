"""`speech.py`'s MUTATING set is a SECOND copy of the registry's `mutating` flags.

WHY THIS GATE EXISTS. The voice layer's whole safety story is the last clause:
a mutating chain says "this changes something" where the operator cannot miss
it. That clause fires off `speech.MUTATING` — a hand-copied set whose own
comment claimed it was "kept in sync by the gate, not by memory" while no such
gate existed (found 2026-09-02; the comment even named a registry field,
`effect`, that `cortex-opcodes.ts` does not have — the real field is
`mutating`). A new mutating opcode landing only in the registry would be
announced to the operator's ear as read-only. This file is the gate that
comment promised.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "files/anatomy/cortex/server/cortex-opcodes.ts"

#: `name: 'link', … mutating: true,` — same anchored style as
#: test_cortex_grammar_matches_registry.py, non-greedy inside one entry.
_OPCODE_RE = re.compile(r"name: '([a-z][a-z0-9-]*)',.*?mutating: (true|false),", re.S)


def _registry_mutating() -> set[str]:
    src = REGISTRY.read_text(encoding="utf-8")
    block = src[src.index("export const CORTEX_OPCODES") :]
    pairs = _OPCODE_RE.findall(block)
    assert len(pairs) >= 15, "opcode parse collapsed — fix the regex, not the set"
    return {name for name, flag in pairs if flag == "true"}


def test_speech_mutating_matches_registry():
    sys.path.insert(0, str(REPO / "files/anatomy/ears"))
    try:
        import speech
    finally:
        sys.path.pop(0)
    assert speech.MUTATING == _registry_mutating(), (
        "speech.py MUTATING drifted from cortex-opcodes.ts `mutating:` flags — "
        "the voice layer would announce a state-changing chain as read-only"
    )
