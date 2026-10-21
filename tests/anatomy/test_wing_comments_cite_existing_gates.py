"""A Wing PHP comment that names a gate names one that exists.

BasePresenter::requireSuperAdmin cited `test_security_admin_gate_unchanged`
as its pin; no such test ever existed (RBAC audit 2026-10-21). A reader who
trusts the comment trusts a gate nobody runs.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing/app"
_COMMENT = re.compile(r"^\s*(?:\*|//|/\*|#)")
_CITE = re.compile(r"\btest_[a-z0-9_]+(?:\.py)?")
# Dead citations in files this gate's row does not own. Each must stay dead:
# once fixed, the entry fails and is deleted.
_KNOWN_DEAD = {
    # renamed to test_agentkit_write_tool_scope.py; fix belongs to its owner
    ("files/anatomy/wing/app/AgentKit/Tools/MigrationWriteTool.php", "test_security_agentkit_filewrite.py"),
}


def _known() -> set[str]:
    names: set[str] = set()
    for py in list((REPO / "tests").rglob("test_*.py")) + list((REPO / "files").rglob("test_*.py")):
        names.add(py.stem)
        names.update(re.findall(r"^\s*def (test_\w+)", py.read_text(encoding="utf-8", errors="replace"), re.M))
    return names


def _dead() -> set[tuple[str, str, int]]:
    known = _known()
    out = set()
    for php in sorted(WING.rglob("*.php")):
        for no, line in enumerate(php.read_text(encoding="utf-8").splitlines(), 1):
            if _COMMENT.match(line):
                for cite in _CITE.findall(line):
                    if cite.removesuffix(".py") not in known:
                        out.add((str(php.relative_to(REPO)), cite, no))
    return out


def test_every_cited_gate_exists() -> None:
    dead = sorted(d for d in _dead() if d[:2] not in _KNOWN_DEAD)
    assert not dead, "Wing comments cite gates that do not exist:\n" + "\n".join(f"{p}:{n}: {c}" for p, c, n in dead)


def test_known_dead_entries_are_still_dead() -> None:
    still = {d[:2] for d in _dead()}
    fixed = _KNOWN_DEAD - still
    assert not fixed, f"fixed — delete from _KNOWN_DEAD: {sorted(fixed)}"
