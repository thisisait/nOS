"""Every committed workflow script must pass the lint, and the lint must bite.

Two workflow launches died on 2026-08-28 inside 32 seconds each, on defects
visible in the source: `meta.description` built with `+` (the runtime wants a
pure literal) and five `pipeline()` calls handed their stages where the items
array goes. `node --check` passes both — they are valid JavaScript that breaks
the workflow contract.

This gate has two halves, and the second is the one that matters. Running a
linter over files that already pass proves only that nobody edited them. So it
also runs the linter against the ACTUAL broken text of both failures, held here
as fixtures, and fails if the linter now reads either as fine — a lint that
stops catching what it was written for is worse than none, because its green
gets quoted.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
LINT = REPO / "tools/workflow-lint.py"

#: The exact shapes that cost two launches. Not paraphrases — the first is the
#: concatenated description, the second the stage-where-items-go call.
BROKEN_META = """export const meta = {
  name: 'x',
  description:
    'one ' +
    'two',
  phases: [{ title: 'A' }],
}
phase('A')
"""

#: A falsy item is ALREADY DROPPED — measured 2026-08-28, `pipeline([null], stage)`
#: invoked its stage zero times and said nothing. The repair for the bug above
#: introduced this one, so both are held here.
BROKEN_NULL_ITEM = """export const meta = {
  name: 'x',
  description: 'one',
  phases: [{ title: 'A' }],
}
phase('A')
await pipeline([null], () => agent('write'))
"""

BROKEN_PIPELINE = """export const meta = {
  name: 'x',
  description: 'one',
  phases: [{ title: 'A' }],
}
phase('A')
await pipeline(
  () => agent('write'),
  () => agent('verify'),
)
"""

GOOD = """export const meta = {
  name: 'x',
  description: 'one',
  phases: [{ title: 'A' }],
}
phase('A')
await pipeline([1],
  () => agent('write'),
  () => agent('verify'),
)
"""


def _lint(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(LINT), *args],
                          capture_output=True, text=True, timeout=120)


def test_the_linter_exists_and_runs() -> None:
    assert LINT.is_file(), "tools/workflow-lint.py is gone"
    out = _lint("--all")
    assert "scripts pass" in out.stdout, out.stdout + out.stderr


def test_every_committed_workflow_script_passes() -> None:
    out = _lint("--all")
    assert out.returncode == 0, f"a committed workflow script would fail at launch:\n{out.stdout}"


def test_it_refuses_a_concatenated_meta(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "meta.js"
    p.write_text(BROKEN_META, encoding="utf-8")
    out = _lint(str(p))
    assert out.returncode == 1, f"the concatenated meta was accepted:\n{out.stdout}"
    assert "PURE LITERAL" in out.stdout


def test_it_refuses_a_stage_where_the_items_go(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "pipe.js"
    p.write_text(BROKEN_PIPELINE, encoding="utf-8")
    out = _lint(str(p))
    assert out.returncode == 1, f"pipeline(stage, stage) was accepted:\n{out.stdout}"
    assert "items" in out.stdout


def test_it_refuses_a_falsy_item(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "null.js"
    p.write_text(BROKEN_NULL_ITEM, encoding="utf-8")
    out = _lint(str(p))
    assert out.returncode == 1, f"pipeline([null]) was accepted:\n{out.stdout}"
    assert "ALREADY DROPPED" in out.stdout


def test_it_passes_the_corrected_shape(tmp_path: pathlib.Path) -> None:
    """A linter that fails everything is not a linter."""
    p = tmp_path / "good.js"
    p.write_text(GOOD, encoding="utf-8")
    out = _lint(str(p))
    assert out.returncode == 0, f"the corrected shape was refused:\n{out.stdout}"


def test_it_says_what_it_cannot_see() -> None:
    """The research workflow died on an undefined identifier, which needs scope
    analysis this linter does not do. The docstring must keep saying so — a tool
    whose limits are undocumented gets read as complete."""
    doc = LINT.read_text(encoding="utf-8")
    assert "CANNOT SEE" in doc.upper(), (
        "the linter no longer states its limits; its green would then read as "
        "'this script will run', which it cannot promise"
    )
