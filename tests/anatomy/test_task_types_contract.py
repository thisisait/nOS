"""The task-type contract is well-shaped and AGENTS.md is its faithful render.

state/genome/task-types.yml is the ONE source of the task_type enum (operator decision
§14.2: the enum lives in code). Two ways it can rot, both gated here:

1. A type with a missing/blank field — a dumb agent reading a half-contract does
   not know whether it may write, or what "done" is. Every type must declare all
   five fields, non-empty.
2. AGENTS.md (the router a dumb agent reads first) drifting from the contract —
   the whole point is that the prose router and the machine contract are the SAME
   truth. tools/task-types-render.py --check fails on drift; regenerate to fix.
3. The three invariants AGENTS.md shows being a second copy of CLAUDE.md — they
   are extracted from CLAUDE.md at render time, so the charter is the one text.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest
import yaml

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SRC = os.path.join(_REPO, "state", "genome", "task-types.yml")
_RENDER = os.path.join(_REPO, "tools", "task-types-render.py")

_REQUIRED = {"summary", "tools", "writes", "needs_operator", "done"}
_WRITES = {"code", "data", "docs", "live", "none"}


def _doc() -> dict:
    with open(_SRC, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_source_exists_and_has_types():
    doc = _doc()
    assert doc.get("task_types"), "state/genome/task-types.yml declares no task_types"


@pytest.mark.parametrize("name", list(_doc()["task_types"].keys()))
def test_each_type_is_fully_declared(name):
    c = _doc()["task_types"][name]
    missing = _REQUIRED - set(c or {})
    assert not missing, f"task_type {name!r} is missing fields: {sorted(missing)}"
    for field in _REQUIRED:
        val = c[field]
        assert val not in (None, "", []), f"task_type {name!r}: {field} is blank"
    assert c["writes"] in _WRITES, (
        f"task_type {name!r}: writes={c['writes']!r} not one of {sorted(_WRITES)}")
    assert isinstance(c["needs_operator"], bool), (
        f"task_type {name!r}: needs_operator must be a bool")
    assert isinstance(c["tools"], list) and c["tools"], (
        f"task_type {name!r}: tools must be a non-empty list")


def test_agents_md_is_in_sync():
    """AGENTS.md must be the current render of the contract (no hand-drift)."""
    r = subprocess.run([sys.executable, _RENDER, "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        "AGENTS.md is stale vs state/genome/task-types.yml — run "
        "tools/task-types-render.py.\n" + (r.stderr or r.stdout))



def _norm(s: str) -> str:
    return " ".join(s.replace("**", "").split())


def test_invariants_are_quoted_from_claude_md():
    """Each numbered invariant in AGENTS.md is CLAUDE.md text, verbatim."""
    agents = open(os.path.join(_REPO, "AGENTS.md"), encoding="utf-8").read()
    block = agents.split("## Three invariants", 1)[1].split("\n## ", 1)[0]
    numbered = [x for x in re.split(r"\n(?=[123]\. )", block) if x[:2] in ("1.", "2.", "3.")]
    assert len(numbered) == 3, "AGENTS.md must list exactly three invariants"
    charter = _norm(open(os.path.join(_REPO, "CLAUDE.md"), encoding="utf-8").read())
    copied = [x[:60] for x in numbered if _norm(x[3:]) not in charter]
    assert not copied, f"AGENTS.md invariants not found verbatim in CLAUDE.md: {copied}"


def test_the_renderer_reads_claude_md(tmp_path):
    """Change the charter and the render changes: the invariants are read, not typed."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ttr", _RENDER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "_CHARTER"), "task-types-render.py does not read CLAUDE.md"
    charter = open(mod._CHARTER, encoding="utf-8").read()
    marked = charter.replace("Success is written by a reader", "Success is written by a MARKER", 1)
    assert marked != charter
    fake = tmp_path / "CLAUDE.md"
    fake.write_text(marked, encoding="utf-8")
    mod._CHARTER = str(fake)
    assert "written by a MARKER" in mod._render(_doc())


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
