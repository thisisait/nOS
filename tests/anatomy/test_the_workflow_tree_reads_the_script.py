"""The workflow tree must read the script, not a story about it.

`tools/workflow-tree.py` and `tools/wf-panel.sh` shipped ungated on 2026-08-28
and the build review named it the run's one real gap. The risk is specific: this
renderer is what an operator reads before deciding to spend a run, so a tree that
quietly omits agents is worse than no tree — it shows a workflow with three
phases that have no agents and looks entirely plausible.

That is not hypothetical. It happened twice while the tool was being written:

  * blanking comments BEFORE strings made `http://127.0.0.1` inside a prompt look
    like a comment, which ate the rest of that line including the backtick that
    closed the template — five of twenty call sites vanished;
  * the paren walk counted brackets inside prose, and the Surface phase lost
    three of its four agents to one unbalanced parenthesis.

Both rendered without error. So this gate does not check that the tool RUNS; it
checks that what it draws matches what the script declares, and it uses the real
committed workflow as its fixture rather than a toy.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
TREE = REPO / "tools/workflow-tree.py"
PANEL = REPO / "tools/wf-panel.sh"
SCRIPT = REPO / "docs/plans/rsi-research/04-implementation-workflow.js"


def _render(*args: str) -> str:
    out = subprocess.run([sys.executable, str(TREE), *args, "--no-color"],
                         capture_output=True, text=True, timeout=60, cwd=REPO)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_the_tools_exist_and_are_executable() -> None:
    for p in (TREE, PANEL):
        assert p.is_file(), f"{p.relative_to(REPO)} is gone"
        assert p.stat().st_mode & 0o111, f"{p.relative_to(REPO)} is not executable"


def test_every_declared_agent_appears() -> None:
    """The count is not decoration — a silently short tree is the failure mode."""
    src = SCRIPT.read_text(encoding="utf-8")
    labels = set(re.findall(r"label:\s*'([^']+)'", src))
    assert len(labels) >= 15, f"the fixture workflow declares only {len(labels)} labels"
    rendered = _render(str(SCRIPT))
    missing = sorted(l for l in labels if l not in rendered)
    assert not missing, (
        f"the tree omits {len(missing)} of {len(labels)} agents: {missing}. "
        "A renderer that drops call sites draws a plausible, wrong workflow."
    )


def test_every_declared_phase_appears() -> None:
    src = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"export\s+const\s+meta\s*=\s*\{.*?\n\}", src, re.S)
    assert m, "the fixture workflow has no meta block"
    titles = re.findall(r"title:\s*'([^']+)'", m.group(0))
    assert len(titles) >= 5
    rendered = _render(str(SCRIPT))
    for t in titles:
        assert t in rendered, f"the tree omits the phase {t!r}"


def test_a_phase_with_no_agents_says_so() -> None:
    """Absence must be rendered as absence — the house rule this tool serves."""
    src = TREE.read_text(encoding="utf-8")
    assert "no agent declares this phase" in src, (
        "an empty phase renders as a bare heading, which reads as a phase whose "
        "agents are simply further down"
    )


def test_progress_never_infers_done_from_time() -> None:
    """Scoped to `progress()` — `newest_run()` legitimately compares mtimes to
    pick which journal to read, and a whole-file grep would call that the bug."""
    src = TREE.read_text(encoding="utf-8")
    body = src[src.index("def progress("):src.index("MARK = {")]
    assert '"running"' in body and '"done"' in body
    assert "started" in body and "result" in body, (
        "progress is no longer derived from the journal's started/result lines"
    )
    for forbidden in ("time.time", "datetime.now", "mtime"):
        assert forbidden not in body, (
            f"{forbidden} inside progress() — an agent that has started and not "
            "finished must render as RUNNING, never as done because time passed"
        )


def test_the_panel_pushes_and_does_not_own_the_pane() -> None:
    """`nos-watch` clears its pane every tick; a definition is read by scrolling."""
    # ABSENCE is asserted against the CODE, presence against the whole file.
    # wf-panel.sh explains at length why it does not use nos-watch and does not
    # respawn the pane, and the first two versions of this gate read those
    # explanations as the offence — a detector reading prose about the thing
    # instead of the thing, in a gate written to enforce that very rule.
    src = PANEL.read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "nos-watch" not in code, "the panel must not hand the pane to the clearing loop"
    assert "clear; cat" in src, "the render no longer lands in the pane's own scrollback"
    assert "respawn-pane" not in code, "respawn would kill the shell the operator types in"
    assert 'has-session -t "=' in src, (
        "the session target is unanchored — tmux matches by PREFIX and would reach "
        "the operator's own sessions"
    )
    assert "exit 0" in src, "a missing tmux or pane must not fail the hook that calls this"
