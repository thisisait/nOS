"""Anatomy gate — homebrew_prefix is ISA-bound (arm64), not die-variant-bound.

WHY: `homebrew_prefix` in default.config.yml selects the Homebrew root from the
instruction-set architecture: `ansible_facts['machine'] == 'arm64'` →
`/opt/homebrew`, else `/usr/local`. A reviewer flagged this as "hardcoded to
arm64 with no future Apple Silicon variant detection (M4 Pro/Max, M5+)". That
misframes the layout: Homebrew keys its prefix on the ISA (`arm64` vs `x86_64`),
NOT on the CPU die. Every Apple Silicon family — M1…M5+, incl. Pro/Max/Ultra —
reports `machine == 'arm64'` and shares `/opt/homebrew`, so the existing
conditional already covers all current and future Apple Silicon sub-variants.

This gate pins that invariant so a well-meant "add per-die detection" refactor
(which would break the ISA contract, or drift the value off Homebrew's actual
prefix) trips here, and keeps the CLAUDE.md doctrine note in sync with the code.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
CONFIG = REPO / "default.config.yml"
CLAUDE = REPO / "CLAUDE.md"


def _homebrew_prefix_value() -> str:
    for line in CONFIG.read_text().splitlines():
        m = re.match(r"^homebrew_prefix:\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    raise AssertionError("homebrew_prefix not defined in default.config.yml")


def test_homebrew_prefix_branches_on_machine_arm64():
    """The selector must key off the ISA fact, the two branches must be the
    canonical Homebrew prefixes, and nothing else (no die-variant detection)."""
    val = _homebrew_prefix_value()
    # ISA fact, not die-variant fact
    assert "ansible_facts['machine']" in val, (
        "homebrew_prefix must branch on the ISA fact ansible_facts['machine']; "
        f"got: {val!r}"
    )
    assert "'arm64'" in val or '"arm64"' in val, (
        "homebrew_prefix must compare machine against the 'arm64' ISA identifier "
        "(shared by every Apple Silicon die — M1…M5+, Pro/Max/Ultra); "
        f"got: {val!r}"
    )
    # the two canonical Homebrew prefixes, ISA-bound
    assert "/opt/homebrew" in val, "arm64 branch must resolve /opt/homebrew"
    assert "/usr/local" in val, "x86_64 fallback must resolve /usr/local"
    # guard against a die-variant 'detection' creep that would break the ISA contract
    forbidden = ("M1", "M2", "M3", "M4", "M5", "Pro", "Max", "Ultra", "brew --prefix")
    leaked = [tok for tok in forbidden if tok in val]
    assert not leaked, (
        "homebrew_prefix is ISA-bound (arm64 vs x86_64), not die-variant-bound. "
        "Every Apple Silicon die reports machine=='arm64' → /opt/homebrew; do NOT "
        f"add per-variant branching. Offending token(s): {leaked} in {val!r}"
    )


def test_claude_md_documents_isa_binding():
    """The Apple Silicon Constraints doctrine must state the ISA-binding so the
    'add variant detection' finding stays explicitly closed."""
    txt = CLAUDE.read_text()
    assert "ISA-bound" in txt, "CLAUDE.md must document homebrew_prefix as ISA-bound"
    assert "test_homebrew_prefix_isa_bound.py" in txt, (
        "CLAUDE.md Apple Silicon note must point at this gate"
    )
    # the note must name the die families it covers, so the claim is auditable
    for die in ("M1", "M5"):
        assert die in txt, f"CLAUDE.md ISA note should name the {die} family it covers"
