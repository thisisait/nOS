"""Anatomy gate — CLAUDE.md references anatomy tests with resolvable names.

WHY (2026-06-14): the AgentKit "Key contracts" block in CLAUDE.md cites the
gates that lock each contract. Two of them — `test_llm_client_protocol_is_minimal`
and `test_all_agentkit_tables_declared` — were cited by BARE function name with
no file, while the sibling bullet above used the qualified pytest form
`tests/anatomy/test_agentkit_naming.py::test_uri_scheme_uses_dash_separator`.
Both bare names actually live in test_agentkit_naming.py, so a reader grepping
the tree for a `test_…py` file by that name found nothing — a dead reference
in the agent contract. Fixed by qualifying both to the `<file>::<func>` form.

This gate pins the relocation-proof citation style: every `tests/anatomy/
<file>.py::<func>` reference in CLAUDE.md MUST resolve to a real test function
in that file. Trips if a contract bullet cites a gate that has moved, been
renamed, or never existed — or if a future edit re-introduces a bare,
un-findable test name in this block.
"""
from __future__ import annotations

import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
CLAUDE_MD = REPO / "CLAUDE.md"
ANATOMY_TESTS = REPO / "tests" / "anatomy"

# Capture `tests/anatomy/<file>.py::<func>` citations (qualified pytest nodeids).
_QUALIFIED_REF = re.compile(r"tests/anatomy/(test_[\w-]+\.py)::(test_[\w]+)")

# The two gate names that MUST be cited in qualified form (the finding):
# bare citation here is un-findable and is what regressed.
_MUST_BE_QUALIFIED = (
    "test_llm_client_protocol_is_minimal",
    "test_all_agentkit_tables_declared",
)


def _test_funcs_in(path: pathlib.Path) -> set[str]:
    """Top-level `def test_*` function names declared in a test module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }


def test_qualified_test_refs_resolve():
    """Every `tests/anatomy/<file>.py::<func>` cited in CLAUDE.md exists on disk."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    refs = _QUALIFIED_REF.findall(text)
    assert refs, "CLAUDE.md must cite anatomy gates in qualified <file>.py::<func> form"

    offenders: list[str] = []
    for filename, func in refs:
        path = ANATOMY_TESTS / filename
        if not path.is_file():
            offenders.append(f"{filename}::{func} — file does not exist")
            continue
        if func not in _test_funcs_in(path):
            offenders.append(
                f"{filename}::{func} — function not found in {filename}"
            )
    assert not offenders, (
        "CLAUDE.md cites anatomy gate(s) that do not resolve — a gate moved, "
        "was renamed, or the citation is wrong:\n  " + "\n  ".join(offenders)
    )


def test_agentkit_contract_gates_are_qualified():
    """The two AgentKit-contract gates are cited in qualified form, not bare.

    Pins the specific finding: a bare `test_llm_client_protocol_is_minimal` /
    `test_all_agentkit_tables_declared` mention (no file) is un-findable. Each
    must appear at least once as `tests/anatomy/<file>.py::<func>`.
    """
    text = CLAUDE_MD.read_text(encoding="utf-8")
    qualified = {func for _, func in _QUALIFIED_REF.findall(text)}
    missing = [name for name in _MUST_BE_QUALIFIED if name not in qualified]
    assert not missing, (
        "These AgentKit-contract gates must be cited in qualified "
        "`tests/anatomy/<file>.py::<func>` form (bare names are un-findable): "
        + ", ".join(missing)
    )
