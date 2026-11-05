#!/usr/bin/env python3
"""List every worktree of a repo and remove the ones whose branch has landed.

Dry run by default: prints each worktree, its branch, its state and size, and
which ones would go. `--confirm` runs `git worktree remove` (no --force) on those.

A worktree is prunable only when ALL hold: not the main or current one, not
locked, no uncommitted or untracked change, its HEAD is an ancestor of --base
(default origin/dev, as last fetched; no fetch here), its admin HEAD/index were
not touched in the last --min-age-hours (default 24: a fresh or just-landed
worktree a live session works in looks landed too), and no kept worktree sits
inside it (nested agent chains live under the gitignored .claude/, which
`git worktree remove` would delete with the parent). A removal that fails keeps
its ancestors too. An unresolvable base is UNKNOWN: nothing is listed and
--confirm exits 2.

    tools/worktree-prune.py [--repo PATH] [--base origin/dev] [--json] [--no-size]
                            [--min-age-hours 24] [--confirm]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time


def git(cwd, *args):
    # No optional index locks: a scan of ~180 worktrees must not race a live session's git.
    return subprocess.run(["git", "--no-optional-locks", "-C", cwd, *args],
                          capture_output=True, text=True)


def worktrees(repo):
    out, cur = [], None
    for line in git(repo, "worktree", "list", "--porcelain").stdout.splitlines():
        key, _, val = line.partition(" ")
        if key == "worktree":
            cur = {"path": os.path.realpath(val), "branch": None, "locked": False}
            out.append(cur)
        elif key == "HEAD":
            cur["head"] = val
        elif key == "branch":
            cur["branch"] = val.removeprefix("refs/heads/")
        elif key == "locked":
            cur["locked"] = True
    return out


def last_used(path):
    gd = git(path, "rev-parse", "--absolute-git-dir").stdout.strip()
    return max((os.path.getmtime(os.path.join(gd, f)) for f in ("HEAD", "index", "logs/HEAD")
                if gd and os.path.exists(os.path.join(gd, f))), default=time.time())


def state(wt, base, min_age_s):
    if wt["locked"]:
        return "locked"
    if not os.path.isdir(wt["path"]):
        return "missing"  # `git worktree prune` clears these
    st = git(wt["path"], "status", "--porcelain")
    if st.returncode or st.stdout.strip():
        return "dirty"
    if git(wt["path"], "merge-base", "--is-ancestor", wt["head"], base).returncode:
        return "unmerged"
    if time.time() - last_used(wt["path"]) < min_age_s:
        return "recent"
    return "merged-clean"


def size_kb(path):
    r = subprocess.run(["du", "-sk", path], capture_output=True, text=True)
    return int(r.stdout.split()[0]) if r.returncode == 0 and r.stdout else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--base", default="origin/dev")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-size", action="store_true")
    ap.add_argument("--min-age-hours", type=float, default=24)
    ap.add_argument("--confirm", action="store_true")
    a = ap.parse_args()

    top = git(a.repo, "rev-parse", "--show-toplevel")
    if top.returncode:
        print(f"UNKNOWN: {a.repo} is not a git checkout", file=sys.stderr)
        return 2 if a.confirm else 0
    here = os.path.realpath(top.stdout.strip())
    base_ok = git(a.repo, "rev-parse", "--verify", "-q", a.base + "^{commit}").returncode == 0

    wts = worktrees(a.repo)
    rows = []
    for i, wt in enumerate(wts):
        if i == 0 or wt["path"] == here:
            continue  # the main worktree and the one we run from are never candidates
        s = state(wt, a.base, a.min_age_hours * 3600) if base_ok else "UNKNOWN"
        rows.append({"path": wt["path"], "branch": wt["branch"], "state": s,
                     "size_kb": None if a.no_size or s == "missing" else size_kb(wt["path"])})
    # Every worktree that stays (main and current included) pins its ancestors.
    keep = [w["path"] for w in wts if w["path"] not in
            {r["path"] for r in rows if r["state"] == "merged-clean"}]
    for r in rows:
        if r["state"] == "merged-clean" and any(k.startswith(r["path"] + os.sep) for k in keep):
            r["state"] = "holds-kept-child"
    prunable = [r for r in rows if r["state"] == "merged-clean"]
    report = {"status": "ok" if base_ok else "UNKNOWN", "base": a.base,
              "worktrees": rows, "prunable": prunable,
              "prunable_kb": sum(r["size_kb"] or 0 for r in prunable)}

    if a.json:
        print(json.dumps(report, indent=2))
    else:
        if not base_ok:
            print(f"UNKNOWN: base {a.base} does not resolve; run `git fetch` and retry")
        for r in rows:
            mb = "?" if r["size_kb"] is None else f"{r['size_kb'] // 1024}M"
            print(f"{r['state']:17} {mb:>8}  {r['branch'] or '(detached)'}  {r['path']}")
        verb = "removing" if a.confirm else "would remove (dry run; --confirm to act)"
        print(f"{verb}: {len(prunable)} worktree(s), {report['prunable_kb'] // 1024} MB")

    if not a.confirm:
        return 0
    if not base_ok:
        return 2
    rc, failed = 0, []
    # Deepest first; a child git refused (work since the scan) pins its ancestors.
    for r in sorted(prunable, key=lambda r: -len(r["path"])):
        if any(f.startswith(r["path"] + os.sep) for f in failed):
            print(f"kept {r['path']}: holds a child whose removal failed", file=sys.stderr)
            failed.append(r["path"])
            continue
        res = git(a.repo, "worktree", "remove", r["path"])
        if res.returncode:
            print(f"kept {r['path']}: {res.stderr.strip()}", file=sys.stderr)
            failed.append(r["path"])
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
