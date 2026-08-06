"""An unattended committer runs in a tree somebody is working in. Bound it.

WHY THIS EXISTS. `tools/scan-state-snapshot.py` runs nightly, from the
operator's own checkout, and commits. That is a genuinely dangerous shape — the
obvious implementation (`git add -A && git commit`) would eventually sweep up
half a refactor, or collide with a rebase, or move a branch out from under a
worktree. The tool avoids all of it by building a commit with plumbing against
a temporary index and moving one ref.

These checks pin the properties that make that safe. Every one of them is a
thing the tool could quietly acquire in a later edit, and none of them would
show up as a test failure anywhere else.

  1. It stages an ALLOW-LIST, never a wildcard. `add -A`, `add .` and
     `update-index --add .` are all ways to commit whatever the operator was
     holding, and the difference between them and a named path is the whole
     safety argument.
  2. The allow-list stays OUT of `.claude/`. The triage gate
     (test_triage_gate_is_a_commit.py) rests on discovery having no path into
     git; a nightly committer that could write a workflow spec would hand it
     one by the back door.
  3. It never touches the working tree or HEAD — no checkout, switch, reset,
     stash, clean, rebase, merge or pull.
  4. It refuses when the target branch is checked out, because moving that ref
     leaves the worktree holding it showing every file as deleted.

Retro-red: verified by adding `git("add", "-A")` to the tool (red on 1), by
adding `.claude/workflows/x.js` to TRACKED (red on 2), and by deleting the
`branch_is_checked_out` guard (red on 4).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools/scan-state-snapshot.py"

_COMMENT = re.compile(r"^\s*#.*$", re.MULTILINE)
_DOCSTRING = re.compile(r'"""..*?"""', re.DOTALL)


def _code() -> str:
    """Source with docstrings and comments stripped.

    The header explains what the tool refuses to do, in the words it refuses to
    use. A check that read the prose would fire on every explanation — which is
    how a gate teaches people to stop writing explanations. Fifth time this
    shape has come up in one day's gates.
    """
    src = TOOL.read_text(encoding="utf-8")
    src = _DOCSTRING.sub("", src)
    return _COMMENT.sub("", src)


def test_the_tool_exists():
    assert TOOL.is_file(), "tools/scan-state-snapshot.py is gone; this gate is blind"


@pytest.mark.parametrize(
    "pattern,what",
    [
        (r'["\']add["\']\s*,\s*["\']-A', "git add -A"),
        (r'["\']add["\']\s*,\s*["\']\.["\']', "git add ."),
        (r'["\']-A["\']', "a bare -A argument"),
    ],
)
def test_it_never_stages_a_wildcard(pattern, what):
    assert not re.search(pattern, _code()), (
        f"scan-state-snapshot.py uses {what}. It runs unattended in the "
        f"operator's own checkout; the only thing standing between it and "
        f"somebody's half-finished refactor is that it names its paths."
    )


def test_the_allow_list_is_a_literal_list_of_named_paths():
    src = _code()
    m = re.search(r"TRACKED\s*=\s*\[(.*?)\]", src, re.DOTALL)
    assert m, "TRACKED is gone or is no longer a literal list — it is the allow-list"
    paths = re.findall(r'["\']([^"\']+)["\']', m.group(1))
    assert paths, "the allow-list is empty; the tool would commit nothing"
    for p in paths:
        assert not p.startswith(".claude/"), (
            f"the allow-list contains {p!r}. A nightly committer that can write "
            f"under .claude/ hands discovery the git path the triage gate says "
            f"it must not have — see test_triage_gate_is_a_commit.py."
        )
        assert "*" not in p and "?" not in p, (
            f"{p!r} is a glob, not a path. A glob is a wildcard with extra steps."
        )


@pytest.mark.parametrize(
    "verb",
    ["checkout", "switch", "reset", "stash", "clean", "rebase", "merge", "pull"],
)
def test_it_never_moves_the_working_tree_or_head(verb):
    assert not re.search(rf'["\']{verb}["\']', _code()), (
        f"scan-state-snapshot.py calls `git {verb}`. This tool records; it does "
        f"not navigate. Anything that moves HEAD or the working tree can be felt "
        f"by whoever is using the checkout, which is the one thing it must never do."
    )


def test_it_refuses_when_the_target_branch_is_checked_out():
    """CALLED, not merely defined — and the difference is not pedantry.

    The first version of this check asserted the guard's NAME appeared in the
    source. Retro-red then deleted the call site and left the function behind:
    the tool would have moved the ref regardless, and the gate stayed green.
    That is the dormant-probe defect, in the gate that was supposed to prevent
    a worse one. Parsed properly now.
    """
    import ast

    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "branch_is_checked_out" in names, (
        "the checked-out guard is gone. Moving a ref that a worktree holds "
        "leaves that worktree showing every tracked file as deleted — a silent, "
        "alarming and entirely avoidable way to ruin somebody's afternoon."
    )

    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    called = {
        node.func.id
        for node in ast.walk(main)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "branch_is_checked_out" in called, (
        "branch_is_checked_out() is defined but main() never calls it. A guard "
        "that is not invoked is decoration; the ref moves anyway and the "
        "worktree holding that branch breaks silently."
    )

    src = _code()
    assert "worktree" in src and "list" in src, (
        "the guard no longer consults `git worktree list`, so it cannot know "
        "which worktree holds what"
    )


def test_promotion_does_not_stage_anything():
    """Promoting a scan state into a branch is a human decision.

    A status flipped to `resolved` carries a rationale; a machine is not in a
    position to approve it. So `--promote` writes the files and stops.
    """
    src = _code()
    m = re.search(r"def promote\(.*?\n(?=\ndef |\nif __name__)", src, re.DOTALL)
    assert m, "promote() is gone — is the review path still there?"
    body = m.group(0)
    assert '"add"' not in body and "'add'" not in body, (
        "promote() stages files. It must leave them in the working tree for the "
        "operator to read and commit; staging is the first half of deciding."
    )


# ── --status: the answer a blocked `git pull` needs ──────────────────────────
#
# Added 2026-08-06, after the operator's `git pull --ff-only` aborted on these
# two files for the second time and asked whether that was a manual decision
# step. It is one — the design says promoting into dev stays human — but the
# operator was given no way to see whether the local copy was precious or
# already superseded, so the decision was made on a hunch each time.
#
# Both of this feature's own first-run defects are pinned below, because each
# produced a CONFIDENT WRONG ANSWER, which is worse than no feature.


def test_status_compares_against_the_upstream_not_the_local_branch():
    """`--status dev` compared the working tree against the LOCAL `dev` ref,
    which in a worktree flow trails the remote by however many pushes the agent
    made with `HEAD:dev`. It then named four findings as carried only by the
    working tree that the incoming tip already had.

    A pull merges the upstream. Resolving to it is the fix; PRINTING the
    resolution is what makes the answer auditable.
    """
    src = TOOL.read_text(encoding="utf-8")
    assert "def resolve_base" in src, "the base is no longer resolved before comparing"
    assert 'f"origin/{base}"' in src, (
        "--status no longer prefers the remote-tracking ref, so it compares "
        "against whatever the local branch happens to be"
    )
    body = src[src.find("def resolve_base"):src.find("def status(")]
    assert "print(" in body, (
        "the resolution is silent — an answer whose input is invisible is how "
        "the first version of this got it wrong"
    )


def test_status_reads_blob_bytes_not_stripped_output():
    """`git()` strips its stdout, which is right for a sha and wrong for a
    file: every JSON here ends in a newline, so a stripped read can never equal
    the file on disk. The first run reported two byte-identical files as
    differing because of it."""
    src = TOOL.read_text(encoding="utf-8")
    assert "def blob(" in src, "the exact-bytes blob reader is gone"
    status_body = src[src.find("def status("):src.find("def promote(")]
    assert 'git("show"' not in status_body, (
        "--status reads a file through git(), whose .strip() makes every "
        "comparison against an on-disk file false"
    )


def test_status_never_says_safe_while_rows_exist_only_here():
    """The one irreversible outcome is discarding a row nothing else holds.

    Exit 0 must mean exactly "the base holds every row you have". A row the
    base lacks is exit 3 whether or not `scan-data` recorded it — recording
    changes how bad it is, not whether there is a decision to make.
    """
    src = TOOL.read_text(encoding="utf-8")
    body = src[src.find("def status("):src.find("def promote(")]
    branch_idx = body.find("if only_live:")
    assert branch_idx != -1, "the only-in-working-tree branch is gone"
    guarded = body[branch_idx:branch_idx + 400]
    assert "at_risk = True" in guarded, (
        "a row that exists only in the working tree no longer sets at_risk, so "
        "--status can answer 'safe to discard' over unrecorded findings"
    )
