"""`tools/README.md` names every tool, or it is not an index.

WHY. `tools/` reached 105 scripts with no stated organising rule, and the
operator's complaint on 2026-08-29 was exactly that: too much, no structure. The
answer was NOT to move them — several hundred references across CLAUDE.md,
plugin manifests, pulse jobs, docs, tests and memories point at these paths by
name, and a categorical tidy-up would break all of them for cosmetic gain. What
shipped instead is a written convention plus this index.

An index only helps while it is complete. A partial one is worse than none: it
reads as the whole list, so a reader concludes a tool does not exist rather than
that nobody added the line. That is the same defect shape as a reader whose
unreadable source renders as empty — which is why this file exists rather than
a note asking people to remember.

It deliberately does NOT check the descriptions. A gate that compared each line
to the script's docstring would fail on every reworded summary and teach people
to edit the gate; this checks the one thing that can be checked without
judgement, which is that nothing is missing and nothing is stale.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools"
README = TOOLS / "README.md"


def _listed() -> set[str]:
    return set(re.findall(r"^- `([^`]+)`", README.read_text(encoding="utf-8"), re.M))


def _present() -> set[str]:
    """What a CHECKOUT has, which is `git ls-files` and not the filesystem.

    The index is a promise to whoever clones the repo. Reading the directory
    instead made the gate depend on the operator's untracked files, and it went
    red in CI the day the README picked up `calibre-sync.py` — real on this
    machine, gitignored, and absent from every other. Either half of that is a
    false answer: a tool nobody but the author can run does not belong in an
    index, and a gate that reports the author's working tree is not testing the
    repository.
    """
    out = subprocess.run(["git", "ls-files", "tools"], cwd=REPO,
                         capture_output=True, text=True, check=True)
    return {pathlib.Path(p).name for p in out.stdout.split()
            if pathlib.Path(p).parent.name == "tools"
            and (pathlib.Path(p).suffix in {".py", ".sh"} or pathlib.Path(p).name == "nos")}


def test_every_tool_is_listed() -> None:
    missing = sorted(_present() - _listed())
    assert not missing, (
        f"{missing} are in tools/ and not in tools/README.md. Add a line under "
        "the group it belongs to — or, if it fits no group, that is the signal "
        "to start a directory rather than a ninth prefix (see the README's own "
        "rule)."
    )


def test_the_index_names_nothing_that_is_gone() -> None:
    stale = sorted(_listed() - _present())
    assert not stale, (
        f"tools/README.md still lists {stale}, which no longer exist. An index "
        "that names a tool the reader cannot run sends them looking for a bug "
        "in their checkout."
    )


def test_the_convention_table_is_still_there() -> None:
    """The list is the cheap half; the RULE is why the list stays short."""
    text = README.read_text(encoding="utf-8")
    for shape in ("`*-status.py`", "`nos-*`", "`run-*.sh`", "`tools/<family>/`"):
        assert shape in text, f"the README no longer states what {shape} means"
    assert "a reader may not write" in text
