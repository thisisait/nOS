#!/usr/bin/env python3
"""The trunk's four holders, and the only tool that moves refs between them.

WHY THIS EXISTS. Four places hold this repository — the local clone, GitHub
(`origin`, the public trunk), Gitea (the CI forge) and GitLab (the MR review
forge) — and until 2026-08-19 the rules between them were LEARNED, not
enforced. Measured that day, twice in one working session:

  1. `tools/loop-pr.py` cut a branch off the LOCAL `dev` while the forges'
     `dev` was five commits behind, so the merge request carried a 598 KB diff
     instead of two lines. The reviewer refused it — correctly — but the
     refusal cost a full CI cycle, a diagnosis and a re-run.
  2. After the reviewer merged on GitLab, the merge existed ONLY on GitLab.
     Promoting it was a hand-built `git fetch https://oauth2:<token>@…` +
     `merge --ff-only` + two pushes, typed from memory, with a credential on
     the command line.

`tools/sync-trunk-to-gitlab.sh` had already written the intended model down
("Model A: when an agent merge has landed in GitLab but not yet on GitHub, the
GitLab trunk leads; promote it to GitHub first, then this sync FF-converges")
— and nothing enforced it, so it was re-derived by hand every time, sometimes
wrongly. This file is that model as code.

THE INVARIANT. For the trunk branch, the four holders must be
FAST-FORWARD-CONVERGENT: one of them is the LEADER — the unique tip that is a
descendant of every other holder's tip — and every sync is a fast-forward of a
follower to the leader. There is no merge, no rebase and no force anywhere in
this file. Two holders whose tips have diverged are an operator problem by
definition, and this tool's whole answer to divergence is to refuse and say so.

READER FIRST, ACTOR ON REQUEST (the estate's dry-run doctrine):

    tools/forge-sync.py                 # report: where the four disagree, and
                                        # the exact plan — touches nothing
    tools/forge-sync.py --apply         # fast-forward the followers to the
                                        # leader, EXCEPT the GitHub push
    tools/forge-sync.py --apply --push-github
                                        # also push GitHub (ff-only). This is
                                        # the promotion step and an operator act
    tools/forge-sync.py --branch dev    # default; --apply refuses any other

WHAT --apply WILL AND WILL NOT DO

  * Push a follower FORGE (Gitea/GitLab) to the leader's sha — plain push, so
    the server refuses anything that is not a fast-forward.
  * Fast-forward the LOCAL `dev` only when this clone has `dev` checked out
    with a clean working tree; otherwise it reports and leaves the tree alone.
    A second interactive session routinely works in this clone — it never
    switches, stashes or resets on anyone's behalf.
  * Push GitHub only behind `--push-github`. GitHub is the public trunk;
    keeping its credential path an explicit act is the same boundary
    `tools/promote-public.sh` draws.

TOKENS NEVER REACH A COMMAND LINE OR A LOG. The sibling sync scripts embed the
token in the push URL (`https://oauth2:<token>@…`), where `ps`, a traceback or
a copy-pasted terminal can all read it — and the hand-typed promotion this file
replaces did exactly that. Here every authenticated git call goes through a
GIT_ASKPASS helper that reads the token from the child process's environment;
the URL carries only the username. API reads carry the token in a header,
which never appears in argv or output. `test_forge_sync_owns_the_directions.py`
pins this.

Exit codes: 0 report printed / converged / nothing to do; 1 an apply step
failed and is named; 2 configuration or divergence this tool refuses to guess
at.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import pathlib
import stat
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]

#: The four holders, in report order. `local` and `github` are git-native;
#: the two forges get their coordinates from the driver's FORGE_KEYS (one
#: source, already drift-gated against the bash siblings).
HOLDERS = ("local", "github", "gitea", "gitlab")


class Refused(Exception):
    """A condition this tool will not work around. Message is operator-facing."""


def _load_driver():
    """Forge coordinate discovery lives in `tools/loop-pr.py` (FORGE_KEYS,
    `_forge`, `_yaml_lookup`, `_remote_tip`); importing it keeps one owner."""
    spec = importlib.util.spec_from_file_location(
        "_loop_pr_forge_sync", REPO / "tools" / "loop-pr.py")
    if spec is None or spec.loader is None:
        raise Refused("cannot load tools/loop-pr.py — the forge coordinates live there")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── git plumbing, credential-free argv ───────────────────────────────────────

def _git(*argv: str, env: dict | None = None, check: bool = True) -> tuple[int, str, str]:
    merged = {**os.environ, **(env or {})}
    # Never let git fall back to an interactive prompt inside a Pulse job.
    merged.setdefault("GIT_TERMINAL_PROMPT", "0")
    done = subprocess.run(  # noqa: S603 — fixed argv, no shell
        ["git", *argv], cwd=str(REPO), text=True,
        capture_output=True, check=False, env=merged,
    )
    if check and done.returncode != 0:
        raise Refused(f"git {argv[0]} failed: {done.stderr.strip()[:300]}")
    return done.returncode, done.stdout.strip(), done.stderr.strip()


class _TokenAuth:
    """GIT_ASKPASS bridge: the token rides the child's environment, never argv.

    The helper script itself contains NO secret — it echoes an env var — so a
    leaked temp file leaks nothing, and `ps` sees only the helper's path.
    """

    def __init__(self, token: str):
        self._token = token
        self._dir = tempfile.mkdtemp(prefix="nos-forge-askpass-")
        helper = pathlib.Path(self._dir) / "askpass.sh"
        helper.write_text('#!/bin/sh\nprintf \'%s\\n\' "$NOS_FORGE_SYNC_TOKEN"\n',
                          encoding="utf-8")
        helper.chmod(stat.S_IRWXU)
        self.env = {
            "GIT_ASKPASS": str(helper),
            "NOS_FORGE_SYNC_TOKEN": token,
            "GIT_TERMINAL_PROMPT": "0",
        }

    def close(self) -> None:
        try:
            for child in pathlib.Path(self._dir).iterdir():
                child.unlink(missing_ok=True)
            pathlib.Path(self._dir).rmdir()
        except OSError:
            pass


def _forge_url(forge: dict) -> str:
    """Push/fetch URL with the USERNAME only. The password is askpass's job."""
    return f"https://oauth2@{forge['domain']}/{forge['owner']}/{forge['repo']}.git"


# ── reading the four tips ────────────────────────────────────────────────────

def read_tips(driver, branch: str) -> dict[str, dict]:
    """One entry per holder: {'sha': str|None, 'error': str|None}.

    An unreadable holder is an ERROR, never 'absent' — the same fail-closed
    doctrine as the driver's `_remote_tip`, and for the same reason: a sync
    planned around a tip nobody saw converges toward a guess.
    """
    tips: dict[str, dict] = {}

    rc, sha, _ = _git("rev-parse", "--verify", "--quiet",
                      f"refs/heads/{branch}", check=False)
    tips["local"] = ({"sha": sha, "error": None} if rc == 0 and sha
                     else {"sha": None, "error": f"no local branch {branch!r}"})

    rc, out, err = _git("ls-remote", "origin", f"refs/heads/{branch}", check=False)
    if rc != 0:
        tips["github"] = {"sha": None, "error": f"origin unreadable: {err[:120]}"}
    elif not out:
        tips["github"] = {"sha": None, "error": f"origin has no branch {branch!r}"}
    else:
        tips["github"] = {"sha": out.split()[0], "error": None}

    for name in ("gitea", "gitlab"):
        try:
            forge = driver._forge(name)
        except Exception as exc:  # noqa: BLE001 — Refused or config gap, same answer
            tips[name] = {"sha": None, "error": str(exc)[:160]}
            continue
        sha, tip_err = driver._remote_tip(forge, branch)
        if tip_err:
            tips[name] = {"sha": None, "error": tip_err}
        elif sha is None:
            tips[name] = {"sha": None, "error": f"branch {branch!r} does not exist on {name}"}
        else:
            tips[name] = {"sha": sha, "error": None, "_forge": forge}
    return tips


def _have_object(sha: str) -> bool:
    rc, _, _ = _git("cat-file", "-e", f"{sha}^{{commit}}", check=False)
    return rc == 0


def _fetch_objects(tips: dict[str, dict], driver, branch: str) -> None:
    """Make every readable tip's commit locally inspectable.

    GitHub objects come via a plain `git fetch origin` (read-only). Forge
    objects come through the askpass bridge — never a token-in-URL fetch.
    """
    gh = tips["github"]
    if gh["sha"] and not _have_object(gh["sha"]):
        _git("fetch", "-q", "origin", branch, check=False)
    for name in ("gitea", "gitlab"):
        entry = tips[name]
        if not entry.get("sha") or _have_object(entry["sha"]):
            continue
        forge = entry.get("_forge") or driver._forge(name)
        auth = _TokenAuth(forge["token"])
        try:
            _git("fetch", "-q", _forge_url(forge), branch,
                 env=auth.env, check=False)
        finally:
            auth.close()


def _is_ancestor(a: str, b: str) -> bool | None:
    """True: a is an ancestor of (or equal to) b. None: cannot tell."""
    if not (_have_object(a) and _have_object(b)):
        return None
    rc, _, _ = _git("merge-base", "--is-ancestor", a, b, check=False)
    if rc == 0:
        return True
    if rc == 1:
        return False
    return None


# ── the plan ─────────────────────────────────────────────────────────────────

def elect_leader(tips: dict[str, dict]) -> tuple[str | None, str]:
    """The unique holder whose tip contains every other readable tip.

    Returns (holder_name, why). None when any holder is unreadable (a leader
    elected over a partial view can converge the estate toward a stale tip)
    or when two tips have diverged.
    """
    unreadable = [n for n in HOLDERS if tips[n]["error"]]
    if unreadable:
        return None, ("cannot elect a leader — unreadable holder(s): "
                      + "; ".join(f"{n}: {tips[n]['error']}" for n in unreadable))

    shas = {tips[n]["sha"] for n in HOLDERS}
    if len(shas) == 1:
        return "local", "all four tips are identical"

    for name in HOLDERS:
        candidate = tips[name]["sha"]
        verdicts = [_is_ancestor(tips[other]["sha"], candidate)
                    for other in HOLDERS if other != name]
        if all(v is True for v in verdicts):
            return name, f"{name}'s tip contains every other tip"
        if any(v is None for v in verdicts):
            return None, ("cannot compare tips — some objects are not in this "
                          "clone even after fetching; refusing to plan blind")
    return None, ("the tips have DIVERGED — no holder contains all the others. "
                  "That is an operator reconciliation, never a sync")


def build_plan(tips: dict[str, dict], leader: str) -> list[dict]:
    """One step per follower that is behind: {'holder', 'action', 'to_sha'}."""
    target = tips[leader]["sha"]
    steps = []
    for name in HOLDERS:
        if name == leader or tips[name]["sha"] == target:
            continue
        steps.append({"holder": name,
                      "action": {"local": "ff-merge",
                                 "github": "push (ff)",
                                 "gitea": "push (ff)",
                                 "gitlab": "push (ff)"}[name],
                      "to_sha": target})
    return steps


# ── acting ───────────────────────────────────────────────────────────────────

def _apply_step(step: dict, tips: dict[str, dict], driver, branch: str,
                *, push_github: bool, log) -> int:
    """Execute one fast-forward. Returns 0 done, 1 failed, 0 with a report
    when the step is deliberately left to the operator."""
    holder, target = step["holder"], step["to_sha"]

    if holder == "github":
        if not push_github:
            log(f"  github: NOT pushed (needs --push-github). The promotion is:")
            log(f"          git push origin {target[:12]}:refs/heads/{branch}")
            return 0
        rc, _, err = _git("push", "origin", f"{target}:refs/heads/{branch}", check=False)
        if rc != 0:
            log(f"  github: push refused — {err.splitlines()[-1] if err else 'no reason given'}")
            return 1
        log(f"  github: fast-forwarded to {target[:12]}")
        return 0

    if holder == "local":
        rc, head_branch, _ = _git("rev-parse", "--abbrev-ref", "HEAD", check=False)
        if head_branch != branch:
            log(f"  local: {branch} is not the checked-out branch here ({head_branch}) "
                f"— left alone; a sync never switches the operator's tree")
            return 0
        rc, dirty, _ = _git("status", "--porcelain", check=False)
        if dirty:
            log(f"  local: working tree has uncommitted changes — left alone; "
                f"fast-forward it yourself when the tree is clean:")
            log(f"          git merge --ff-only {target[:12]}")
            return 0
        rc, _, err = _git("merge", "--ff-only", target, check=False)
        if rc != 0:
            log(f"  local: ff-merge refused — {err.splitlines()[-1] if err else ''}")
            return 1
        log(f"  local: fast-forwarded {branch} to {target[:12]}")
        return 0

    forge = tips[holder].get("_forge") or driver._forge(holder)
    auth = _TokenAuth(forge["token"])
    try:
        # Plain push — the server's own non-fast-forward refusal is the guard.
        rc, _, err = _git("push", _forge_url(forge),
                          f"{target}:refs/heads/{branch}",
                          env=auth.env, check=False)
    finally:
        auth.close()
    if rc != 0:
        log(f"  {holder}: push refused — "
            f"{err.splitlines()[-1] if err else 'no reason given'}")
        return 1
    log(f"  {holder}: fast-forwarded to {target[:12]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--branch", default="dev",
                    help="branch to reconcile (default: dev; --apply accepts only dev)")
    ap.add_argument("--apply", action="store_true",
                    help="act; without it this reports and touches nothing")
    ap.add_argument("--push-github", action="store_true",
                    help="with --apply: also fast-forward GitHub (the promotion; operator act)")
    args = ap.parse_args()

    def log(line: str) -> None:
        print(line, flush=True)

    try:
        if args.apply and args.branch != "dev":
            raise Refused(
                f"--apply moves only 'dev'. master is PR-only and the "
                f"operator's (CLAUDE.md § Git Workflow); anything else is "
                f"not a trunk")

        driver = _load_driver()
        tips = read_tips(driver, args.branch)
        _fetch_objects(tips, driver, args.branch)

        log(f"branch {args.branch!r} across the four holders:")
        for name in HOLDERS:
            entry = tips[name]
            if entry["error"]:
                log(f"  {name:<7} UNREADABLE — {entry['error']}")
            else:
                log(f"  {name:<7} {entry['sha'][:12]}")

        leader, why = elect_leader(tips)
        if leader is None:
            log(f"\n{why}")
            return 2
        log(f"\nleader: {leader} — {why}")

        plan = build_plan(tips, leader)
        if not plan:
            log("nothing to do — all four holders agree")
            return 0

        if not args.apply:
            log("plan (DRY RUN — nothing will be touched):")
            for step in plan:
                log(f"  {step['holder']:<7} {step['action']} → {step['to_sha'][:12]}")
            log("\n  re-run with --apply to fast-forward the followers"
                " (add --push-github for the GitHub promotion)")
            return 0

        log("applying:")
        worst = 0
        for step in plan:
            worst = max(worst, _apply_step(step, tips, driver, args.branch,
                                           push_github=args.push_github, log=log))
        return worst
    except Refused as exc:
        print(f"[forge-sync] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
