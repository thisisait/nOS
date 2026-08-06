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

WHEN `git pull` REFUSES. That the working tree stays dirty is the design, not a
fault: it holds scan output `dev` has not been given yet, and giving it is a
human decision. But `--ff-only` then aborts with "your local changes would be
overwritten", and nothing on hand answers the only question that matters —
whether those local changes are precious or already superseded. `--status`
answers it by comparing rows, and refuses to say "safe" on doubt.

    tools/scan-state-snapshot.py --status          # vs dev; exit 0 = discardable
    tools/scan-state-snapshot.py --status master

Usage:  scan-state-snapshot.py [--branch NAME] [--status BASE] [--promote]
                               [--dry-run] [--push REMOTE]

Exit codes
----------
  0  recorded, or nothing had changed, or --status found nothing to lose
  1  refused — the target branch is checked out somewhere
  2  git failed, or a declared file is missing
  3  --status: the working tree carries rows the base does not
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


def blob(rev_path: str) -> str | None:
    """A blob's EXACT bytes. `git()` strips its output, which is right for a
    sha and wrong for a file: every JSON here ends in a newline, so a stripped
    read never compares equal to the file on disk. That bug made this tool's
    first run report two identical files as differing."""
    out = subprocess.run(["git", "-C", str(REPO), "show", rev_path],
                         capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else None


def _rows(text: str) -> dict[str, dict]:
    """Queue rows by id. An unparseable file yields {} — the caller says so
    rather than reporting a confident zero."""
    try:
        data = json.loads(text)
        items = data if isinstance(data, list) else data.get("items", [])
        return {str(it["id"]): it for it in items if isinstance(it, dict) and "id" in it}
    except Exception:
        return {}


def resolve_base(base: str) -> str:
    """Resolve what `git pull` would ACTUALLY bring in, and say so.

    THE TRAP THIS EXISTS FOR, caught on its first run. `--status dev` compared
    against the LOCAL branch `dev`, which in a worktree-driven flow is whatever
    the operator's checkout last landed on — here five commits behind, because
    the agent had pushed `HEAD:dev` to the remote without ever moving the local
    ref. The tool then reported four findings as "carried only by the working
    tree" that the incoming tip already had, and told the operator not to
    discard. Confidently, about a ref nobody asked about.

    A pull merges the UPSTREAM. So resolve `<name>` to `origin/<name>` when a
    remote-tracking ref by that name exists, and print the resolution with its
    sha, because an answer whose input is invisible is how the first version
    got it wrong.
    """
    explicit_remote = "/" in base
    candidate = base if explicit_remote else f"origin/{base}"
    for ref in ([candidate] if explicit_remote else [candidate, base]):
        sha = git("rev-parse", "-q", "--verify", f"{ref}^{{commit}}", check=False)
        if sha:
            if ref != base:
                print(f"[i] {base} → {ref} ({sha[:8]}): a pull merges the upstream, "
                      f"not the local branch of the same name")
            else:
                print(f"[i] base {ref} ({sha[:8]}) — no remote-tracking ref by that name")
            return ref
    print(f"[-] cannot resolve {base} to a commit", file=sys.stderr)
    raise SystemExit(2)


def status(branch: str, base: str) -> int:
    """Answer the one question a blocked `git pull` asks: does my dirty working
    tree carry anything the branch I am pulling does not?

    WHY THIS EXISTS. The design is deliberate — the scan writes into the
    working tree, this tool records that onto `scan-data` by moving one ref,
    and promoting into `dev` stays a human decision because a status change
    carries a rationale worth reading. What the design never covered is the
    moment the operator meets its consequence: `git pull --ff-only` aborts with
    "your local changes would be overwritten", and nothing on hand says whether
    those local changes are precious or already superseded.

    On 2026-08-06 the answer was "already superseded" — scan-state.json was
    byte-identical to the incoming tip and the queue differed by one row the
    incoming tip had MORE of — but establishing that took a row-by-row
    comparison by hand. Doing it by hand is how a real finding eventually gets
    discarded on the assumption that it is noise again.

    Exit 0 = safe to discard the working copy. Exit 3 = it carries rows the
    base does not; promote or commit them first. Never 0 on doubt.
    """
    base = resolve_base(base)

    verdicts: list[str] = []
    at_risk = False

    for rel in TRACKED:
        live_path = REPO / rel
        if not live_path.is_file():
            print(f"  {rel}: ABSENT from the working tree", file=sys.stderr)
            at_risk = True
            continue
        live = live_path.read_text(encoding="utf-8")
        incoming = blob(f"{base}:{rel}")
        if incoming is None:
            verdicts.append(f"  {rel}: not present at {base} — pulling cannot overwrite it")
            continue

        if live == incoming:
            verdicts.append(f"  {rel}: identical to {base} ({len(live)} B) — nothing to lose")
            continue

        # RECORDED ELSEWHERE IS NOT LOST. The whole point of `scan-data` is that
        # the working copy is preserved without touching the tree, so a
        # difference the branch already holds is recoverable and discarding it
        # is reversible. Only what NOTHING holds is a loss.
        recorded = blob(f"{branch}:{rel}") == live

        live_rows, incoming_rows = _rows(live), _rows(incoming)
        if not live_rows or not incoming_rows:
            # Not row-shaped (scan-state.json), or unparseable — no finer
            # comparison is available, so the branch is the only assurance.
            if recorded:
                verdicts.append(f"  {rel}: differs from {base}, but this exact copy is "
                                f"recorded on {branch} — discarding is recoverable")
            else:
                at_risk = True
                verdicts.append(f"  {rel}: differs from {base} and is NOT recorded on "
                                f"{branch} — review by hand")
            continue

        only_live = sorted(set(live_rows) - set(incoming_rows))
        changed = sorted(k for k in set(live_rows) & set(incoming_rows)
                         if live_rows[k] != incoming_rows[k])
        only_incoming = sorted(set(incoming_rows) - set(live_rows))

        # Both branches below are exit 3: a row the base lacks means the
        # operator has a decision to make either way. `recorded` changes how
        # BAD it is, not whether there is work — saying "safe to discard" and
        # "promote these first" in one breath is the kind of message that
        # teaches people to skip the output.
        if only_live:
            at_risk = True
            if recorded:
                verdicts.append(f"  {rel}: {len(only_live)} row(s) {base} lacks. This exact "
                                f"copy IS recorded on {branch}, so nothing is lost — but "
                                f"promote them before the working copy goes")
            else:
                verdicts.append(f"  {rel}: {len(only_live)} row(s) exist ONLY in the working "
                                f"tree and are recorded NOWHERE — DO NOT discard")
        else:
            verdicts.append(f"  {rel}: {base} holds every row here (+{len(only_incoming)} "
                            f"it has in addition) — safe to discard the working copy")
        for k in only_live[:10]:
            verdicts.append(f"      only here  {k}: {live_rows[k].get('severity','?')} "
                            f"{live_rows[k].get('status','?')} · {live_rows[k].get('component','?')}")
        # A differing row is NOT a loss — `base` carries a version of it and the
        # pull replaces yours with that one. Named anyway, because "replaced by
        # a version I did not read" is how a rationale quietly disappears.
        for k in changed[:10]:
            verdicts.append(f"      replaced   {k}: {live_rows[k].get('status','?')} → "
                            f"{incoming_rows[k].get('status','?')}")

    print(f"working tree {REPO} vs {base}:")
    for line in verdicts:
        print(line)

    if at_risk:
        print(f"\nThe working tree holds scan output {base} has never seen. Record it, so "
              f"the copy survives whatever you do next:\n"
              f"  tools/scan-state-snapshot.py --repo {REPO}   # onto {branch}, no tree touched\n"
              f"then promote what belongs in {base} — a status change carries a rationale, "
              f"which is why that stays your call and not this tool's.")
        return 3

    print(f"\nSafe to discard and pull:\n"
          f"  git checkout -- {' '.join(TRACKED)} && git pull --ff-only")
    return 0


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
    ap.add_argument("--status", nargs="?", const="dev", metavar="BASE",
                    help="does the dirty working tree carry anything BASE (default dev) "
                         "lacks? exit 0 safe to discard, 3 it does")
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

    if args.status:
        return status(args.branch, args.status)

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
