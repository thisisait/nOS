#!/usr/bin/env python3
"""Record the nightly scan's output on its own branch, without touching yours.

THE PROBLEM, and it is an omission rather than a policy. The nightly security
scan writes `remediation-queue.json` and `scan-state.json` INTO the repository
and nothing commits them — `files/vuln-scan/scan-runner.sh` does not mention
git at all. So the estate's knowledge of its own exposure accumulates as an
uncommitted diff in whichever checkout the scan happened to run from. Measured
2026-08-05: the main checkout carried 165 rows while `origin/dev` carried 152 —
thirteen findings, two of them HIGH, that only one directory on one machine
knew about. Any other checkout reads the stale committed copy and compares
against it without knowing; this repository's own discovery scanner did exactly
that.

WHY NOT JUST `git commit` IN THE WORKING TREE. Because a cron job that stages
files in a tree a human is working in is a job that will one day commit
somebody's half-finished edit, or collide with a rebase, or fail because the
branch moved under it. The operator's working tree belongs to the operator.

WHAT THIS DOES INSTEAD. It builds a commit with git PLUMBING against a
temporary index and moves one ref. No checkout, no HEAD change, no staging
area, nothing the operator can feel:

    hash-object -w      the file content becomes an object
    read-tree           a temp index seeded from the branch's current tree
    update-index        the declared paths, and ONLY those
    write-tree          → commit-tree → update-ref

The load-bearing safety property is that third step. There is no `add -A` here
and there cannot be: the paths are a hardcoded allow-list, so this tool is
structurally incapable of committing anything the operator was working on.

THE BRANCH IS AN ORPHAN. `scan-data` shares no history with `dev` and its tree
holds only these files, so `git log scan-data` is pure scan history — one entry
per night, each carrying the delta in its subject. That is the overview the
branch exists to give. It is a RECORD, not a source of truth: the working-tree
file stays authoritative for reading, and promoting a state into `dev` stays a
human decision, because status changes carry rationale that deserves review.

    git log --oneline scan-data                    what changed, per night
    git show scan-data:docs/llm/security/remediation-queue.json
    git diff dev scan-data -- docs/llm/security/   what dev is missing
    tools/scan-state-snapshot.py --promote         copy branch state into the
                                                   working tree, then review
                                                   and commit it yourself

Usage:  scan-state-snapshot.py [--branch NAME] [--promote] [--dry-run] [--push REMOTE]

Exit codes
----------
  0  recorded, or nothing had changed
  1  refused — the target branch is checked out somewhere
  2  git failed, or a declared file is missing
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# The checkout whose files are recorded. Defaults to the one this tool lives
# in; `--repo` points it elsewhere.
#
# The flag is not a convenience. The scan runs from `playbook_dir` — the
# operator's main checkout — while an agent doing repository work sits in a
# worktree, and the tool only exists on the branch that worktree is on. On
# 2026-08-05 that produced exactly the deadlock it was written to prevent: the
# recorder could not be run from the checkout that had the data, and could not
# read the data from the checkout that had the recorder. Worktrees share one
# object store and one ref namespace, so recording ACROSS them is correct and
# lands on the same branch either way; only the file content has to come from
# the right tree.
REPO = Path(__file__).resolve().parents[1]
BRANCH = "scan-data"

# The allow-list. This tool can commit these paths and nothing else — that is
# what makes it safe to run unattended in a tree somebody is working in.
TRACKED = [
    "docs/llm/security/remediation-queue.json",
    "docs/llm/security/scan-state.json",
]


def git(*args: str, env: dict | None = None, check: bool = True) -> str:
    out = subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True, text=True, env=env,
    )
    if check and out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {out.stderr.strip()[:300]}")
    return out.stdout.strip()


def branch_is_checked_out(branch: str) -> str | None:
    """Which worktree has `branch` checked out, if any.

    Moving a ref that a worktree has checked out leaves that worktree
    believing it holds commits it does not — every file shows as deleted. So
    this is a refusal, not a warning.
    """
    for line in git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            current = line.split(" ", 1)[1]
        elif line == f"branch refs/heads/{branch}":
            return current
    return None


def counts(path: Path) -> dict[str, int]:
    """Status tally of the queue, for the commit subject. Best-effort: a file
    that will not parse still gets recorded, just without a delta."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("items", [])
        out: dict[str, int] = {}
        for it in items:
            s = str(it.get("status", "?"))
            out[s] = out.get(s, 0) + 1
        out["_total"] = len(items)
        return out
    except Exception:
        return {}


def counts_at(branch: str, rel: str) -> dict[str, int]:
    try:
        blob = git("show", f"{branch}:{rel}")
    except RuntimeError:
        return {}
    try:
        data = json.loads(blob)
        items = data if isinstance(data, list) else data.get("items", [])
        out: dict[str, int] = {}
        for it in items:
            s = str(it.get("status", "?"))
            out[s] = out.get(s, 0) + 1
        out["_total"] = len(items)
        return out
    except Exception:
        return {}


def subject(before: dict[str, int], after: dict[str, int]) -> str:
    """One line that says what actually moved. A commit log of 'update scan
    state' × 90 is not an overview, which is the whole point of the branch."""
    if not after:
        return "scan state recorded"
    total = after.get("_total", 0)
    if not before:
        return f"scan state: {total} row(s), first record"
    deltas = []
    for k in sorted(set(before) | set(after)):
        if k == "_total":
            continue
        d = after.get(k, 0) - before.get(k, 0)
        if d:
            deltas.append(f"{k} {d:+d}")
    grew = after.get("_total", 0) - before.get("_total", 0)
    if grew:
        deltas.insert(0, f"{grew:+d} row(s)")
    return f"scan state: {', '.join(deltas) if deltas else 'edits only'} ({total} total)"


def promote(branch: str) -> int:
    """Copy the branch's state into the working tree for review.

    Deliberately does NOT stage or commit. The operator reads the diff and
    decides — a status flipped to `resolved` carries a rationale that a machine
    is not in a position to approve.
    """
    for rel in TRACKED:
        try:
            content = git("show", f"{branch}:{rel}")
        except RuntimeError:
            print(f"[-] {rel} is not on {branch}", file=sys.stderr)
            return 2
        (REPO / rel).write_text(content + "\n", encoding="utf-8")
        print(f"[+] {rel} <- {branch}")
    print("\nNothing was staged. Review with `git diff` and commit if you agree.")
    return 0


def main() -> int:
    global REPO
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--branch", default=BRANCH)
    ap.add_argument("--repo", metavar="PATH",
                    help="record this checkout's files instead of the tool's own "
                         "(worktrees share the ref, so the branch is the same)")
    ap.add_argument("--promote", action="store_true",
                    help="copy the branch's state into the working tree (no staging)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be recorded; move no ref")
    ap.add_argument("--push", metavar="REMOTE",
                    help="push the branch after recording (opt-in: this leaves the machine)")
    args = ap.parse_args()

    if args.repo:
        REPO = Path(args.repo).resolve()
        if not (REPO / ".git").exists():
            print(f"[-] {REPO} is not a git checkout", file=sys.stderr)
            return 2

    if args.promote:
        return promote(args.branch)

    where = branch_is_checked_out(args.branch)
    if where:
        print(f"[-] {args.branch} is checked out at {where}. Moving the ref would "
              f"leave that worktree showing every file as deleted.", file=sys.stderr)
        return 1

    missing = [r for r in TRACKED if not (REPO / r).is_file()]
    if missing:
        print(f"[-] declared file(s) absent from this checkout: {missing}", file=sys.stderr)
        return 2

    ref = f"refs/heads/{args.branch}"
    parent = git("rev-parse", "-q", "--verify", ref, check=False) or None

    before = counts_at(args.branch, TRACKED[0]) if parent else {}
    after = counts(REPO / TRACKED[0])

    with tempfile.TemporaryDirectory() as tmp:
        env = {**dict(__import__("os").environ), "GIT_INDEX_FILE": f"{tmp}/index"}
        if parent:
            git("read-tree", f"{args.branch}^{{tree}}", env=env)
        changed = []
        for rel in TRACKED:
            blob = git("hash-object", "-w", "--path", rel, str(REPO / rel))
            # Only the declared paths reach the index. There is no add -A here.
            git("update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}", env=env)
            prev = git("rev-parse", "-q", "--verify", f"{args.branch}:{rel}",
                       check=False) if parent else ""
            if prev != blob:
                changed.append(rel)
        tree = git("write-tree", env=env)

    if parent and not changed:
        print(f"nothing changed since {args.branch} — no commit")
        return 0

    msg = subject(before, after)
    body = "\n".join(f"  {r}" for r in changed)
    full = f"{msg}\n\nRecorded from the working tree by tools/scan-state-snapshot.py.\nFiles:\n{body}\n"

    if args.dry_run:
        print(f"[dry] would commit to {args.branch}: {msg}")
        for r in changed:
            print(f"[dry]   {r}")
        return 0

    ct = ["commit-tree", tree]
    if parent:
        ct += ["-p", parent]
    commit = subprocess.run(
        ["git", "-C", str(REPO), *ct], input=full,
        capture_output=True, text=True,
    )
    if commit.returncode != 0:
        print(f"[-] commit-tree failed: {commit.stderr.strip()[:300]}", file=sys.stderr)
        return 2
    sha = commit.stdout.strip()
    git("update-ref", ref, sha)
    print(f"{args.branch} {sha[:9]}  {msg}")

    if args.push:
        git("push", args.push, f"{ref}:{ref}")
        print(f"pushed to {args.push}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
