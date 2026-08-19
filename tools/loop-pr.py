#!/usr/bin/env python3
"""The loop's driver: what happens after the judges say pass.

WHY THIS EXISTS. The engine could propose and it could judge, and between the
two there was a cliff. Measured 2026-08-19: two proposals passed every judge on
08-16 — `rem:REM-204` and `rem:REM-159` — and three days later neither patch was
in the tree, both queue rows still read `pending`, and both verdicts had decayed
(their judged tree moved, so no judge had ruled on anything you could apply).
`tools/loop-status.py --awaiting` made that visible. This acts on it.

WHAT IT DOES NOT DO, AND WHY THAT IS THE WHOLE DESIGN

  It does not merge. It does not touch `master`. It does not write one byte to
  the ledger. It opens a merge request and stops.

  Not writing to the ledger is constraint B (`docs/idea/11-agentic-loop-contract.md`
  §3.5) at this layer: a driver that stamped "landed" would be a step recording
  its own success, and this estate has bought that lesson four times — a
  `dispatched_at` written by the sender, a `status=scanned` written by a scan
  that never ran. Whether a patch reached the tree is git's answer, read back by
  `loop-status.py --awaiting`, which asks `git apply --check` and cannot be told
  what to think.

THE IDENTITY IT HOLDS. The driver is the EVALUATOR, not the proposer — §3.4 says
so plainly: *"the proposer proposes and stops; the driver — a distinct process
holding a distinct token — triggers judgment."* So it may re-judge, and it does,
because that is the only honest repair for a decayed verdict. It holds no
propose scope and never will: a driver that could also author the patch it lands
is the loop grading its own homework.

WHY A DECAYED VERDICT IS RE-JUDGED RATHER THAN TRUSTED. The engine applies a
proposal's diff at ITS OWN base — current HEAD, never the proposer's declared
`tree_sha` (`looproutes.py::_execute`). So a fresh run against today's tree is a
real answer about today's tree, and it is cheap next to the alternative, which is
landing a patch on the strength of a verdict about a tree that no longer exists.

WHICH FORGE, AND WHY BOTH. The branch goes to Gitea AND GitLab; the merge request
is opened on GitLab only. That is not redundancy, it is the two halves of a
review:

  * **Gitea** carries the CI. Woodpecker watches Gitea and `.woodpecker/tests.yml`
    fires on a push to ANY branch, so a branch that never reaches Gitea has no
    green light to show.
  * **GitLab** carries the review. It is the operator's MR surface (T32.2 — the
    Gitea oauth2 source row kept vanishing and locking the operator out of the
    Gitea UI) and it has NO CI: no `.gitlab-ci.yml`, no runner. An MR there is a
    conversation, not a test.

The join between them is the commit sha, which is identical on both because it is
the same commit. Anything downstream that wants to ask "did this pass?" asks
Woodpecker for that sha.

GITHUB IS NOT IN THIS FILE, deliberately, and the same sentence appears in both
sibling tools: the agent loop stays off the public internet. `dev → master` and
non-beta release tags are operator acts. `tools/promote-public.sh` is the only
thing here that holds a GitHub credential and a human runs it.

IT NEVER TOUCHES THE OPERATOR'S CHECKOUT. Its siblings `git switch` the live
tree and stash around it; that stranded the tree on a `fix/recipe-*` branch more
than once, and on this host a second interactive session is routinely working in
the same clone. This uses a detached `git worktree` in a temp dir and removes it
on every exit path, so the operator's branch, index and stash are untouched
whatever happens here.

DRY RUN BY DEFAULT (operator doctrine — dry-run default, explicit confirm):

    tools/loop-pr.py                    # say what would happen, touch nothing
    tools/loop-pr.py --open-mr          # act on every ready proposal
    tools/loop-pr.py --open-mr --uuid <proposal>   # act on exactly one
    tools/loop-pr.py --open-mr --rejudge           # also re-judge decayed ones
    tools/loop-pr.py --base master      # (refused — see _refuse_master)

Exit 0 when it did what it said, 1 on a failure that left work half-done (a
pushed branch with no MR is called out explicitly), 2 on configuration it will
not guess at.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]

#: Where each forge's coordinates come from, in the order the sibling tools read
#: them. Duplicated from `tools/recipe-pr.sh` as DATA rather than shared as code
#: — the bash there is proven and mid-flight refactoring of two working tools is
#: a worse trade than a drift gate. `test_the_driver_reads_the_same_forge.py`
#: pins these keys against the bash, so a rename cannot silently split them.
FORGE_KEYS = {
    "gitlab": {
        "token_env": "GITLAB_TOKEN", "token_key": "gitlab_api_token",
        "domain_env": "GITLAB_DOMAIN", "domain_key": "gitlab_domain",
        "owner_key": "gitlab_nos_repo_owner", "owner_default": "root",
        "name_key": "gitlab_nos_repo_name", "name_default": "nOS",
        "domain_prefix": "gitlab",
        "role_defaults": "roles/pazny.gitlab/defaults/main.yml",
    },
    "gitea": {
        "token_env": "GITEA_TOKEN", "token_key": "gitea_api_token",
        "domain_env": "GITEA_DOMAIN", "domain_key": "gitea_domain",
        "owner_key": "gitea_nos_repo_owner", "owner_default": os.environ.get("USER", "nos"),
        "name_key": "gitea_nos_repo_name", "name_default": "nOS",
        "domain_prefix": "git",
        "role_defaults": "roles/pazny.gitea/defaults/main.yml",
    },
}

#: A weakness source → the commit scope it lands under. `rem:` rows are the
#: security queue, and calling that anything else would hide security work from
#: `git log --grep`.
SCOPE_BY_SOURCE = {"rem": "security", "fee": "debt", "scan": "security",
                   "pulse": "ops", "alert": "ops", "git": "repo"}


class Refused(Exception):
    """A condition the driver will not work around. Message is operator-facing."""


# ── reading the estate ───────────────────────────────────────────────────────

def _load_loop_status():
    """The reader is the authority on state; the driver never re-derives it.

    Two implementations of "is this patch in the tree" is two things to be
    wrong, and the one in `loop-status.py` is the one with a gate on it.
    """
    spec = importlib.util.spec_from_file_location(
        "_loop_status", REPO / "tools" / "loop-status.py")
    if spec is None or spec.loader is None:
        raise Refused("cannot load tools/loop-status.py — the state reader is missing")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _yaml_lookup(key: str, *files: pathlib.Path) -> str:
    """First scalar value for `key:` across these files, Jinja rows skipped.

    Same contract as `yaml_lookup` in the bash siblings, including the reason
    for the Jinja filter: a rendered-but-empty secrets entry once leaked the
    literal `{{ ... }}` line into $TOKEN and defeated the empty check.
    """
    pattern = re.compile(rf"^{re.escape(key)}:\s*\"?([^\"#]*[^\"#\s])\"?\s*(#.*)?$")
    for path in files:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            match = pattern.match(line)
            if match and "{{" not in match.group(1):
                return match.group(1).strip()
    return ""


def _forge(name: str) -> dict:
    """Token, domain, owner and repo for one forge, or raise Refused."""
    keys = FORGE_KEYS[name]
    here = [REPO / "credentials.yml", REPO / "config.yml",
            pathlib.Path.home() / ".nos" / "secrets.yml"]
    conf = [REPO / "config.yml", REPO / "default.config.yml",
            REPO / keys["role_defaults"]]

    token = os.environ.get(keys["token_env"]) or _yaml_lookup(keys["token_key"], *here)
    domain = os.environ.get(keys["domain_env"]) or _yaml_lookup(keys["domain_key"], *here[:2])
    if not domain:
        tenant = _yaml_lookup("tenant_domain", REPO / "config.yml", REPO / "default.config.yml")
        domain = f"{keys['domain_prefix']}.{tenant}" if tenant else ""
    if not token or not domain:
        raise Refused(
            f"missing {keys['token_env']}/{keys['token_key']} or "
            f"{keys['domain_key']} for {name} — is the forge provisioned? "
            f"({name}_agent_forge=true + a run of the {name} tag)"
        )
    return {
        "name": name, "token": token, "domain": domain,
        "owner": _yaml_lookup(keys["owner_key"], *conf) or keys["owner_default"],
        "repo": _yaml_lookup(keys["name_key"], *conf) or keys["name_default"],
    }


# ── git, always in a worktree that is not the operator's ─────────────────────

def _git(*argv: str, cwd: pathlib.Path | None = None, check: bool = True) -> str:
    done = subprocess.run(  # noqa: S603 — fixed argv, no shell
        ["git", *argv], cwd=str(cwd or REPO), text=True,
        capture_output=True, check=False,
    )
    if check and done.returncode != 0:
        # git echoes the push URL on failure and that URL embeds a token, so the
        # stderr is scrubbed before it can reach a log, a devlog or a terminal.
        raise Refused(f"git {argv[0]} failed: {_scrub(done.stderr.strip())}")
    return done.stdout.strip()


def _scrub(text: str) -> str:
    """Never let a credential out of this process."""
    return re.sub(r"https://[^@\s]+@", "https://***@", text)


def _refuse_master(base: str) -> None:
    """`master` is protected, PR-only and an operator's to move.

    Refused here rather than left to the server so the failure names the rule
    instead of arriving as a push rejection three steps later.
    """
    if base in ("master", "main"):
        raise Refused(
            f"the driver will not target '{base}'. dev → master is a PR the "
            f"operator opens; this lands on dev and stops "
            f"(CLAUDE.md § Git Workflow)"
        )


# ── the act ──────────────────────────────────────────────────────────────────

def _commit_message(row: dict) -> tuple[str, str]:
    """Conventional Commits, subject ≤ 50, body bullets ≤ 6 (CLAUDE.md).

    The subject carries the weakness id and nothing derived from the diff: a
    subject built from a version string would be a second place for the version
    to be wrong.
    """
    wid = str(row["weakness_id"])
    source, _, ident = wid.partition(":")
    scope = SCOPE_BY_SOURCE.get(source, "loop")
    subject = f"fix({scope}): {ident or wid} {row['intent_class'].replace('-', ' ')}"
    if len(subject) > 50:
        subject = f"fix({scope}): {ident or wid}"[:50]
    body = "\n".join([
        f"- weakness: {wid}, proposed by {row['proposer_id']}",
        f"- proposal {row['uuid']}, judged pass on the repo gate set",
        f"- patch applies to {', '.join(row['target_paths']) or 'the tree'}",
        "- opened by tools/loop-pr.py; review + CI gate the merge",
    ])
    return subject, body


def _open_merge_request(forge: dict, branch: str, base: str,
                        title: str, description: str) -> tuple[int, str]:
    """POST the MR to GitLab over the LOCAL port. Returns (http, url-or-body).

    Local port, never the public domain: the Cloudflare edge normalizes the
    URL-encoded slash in `/projects/OWNER%2FNAME`, the path arrives as plain
    segments and GitLab 400s. Measured 2026-06-10 and rediscovered since; the
    git push keeps the domain because a git URL has no %2F in it.
    """
    port = _yaml_lookup("gitlab_http_port", REPO / "config.yml",
                        REPO / "default.config.yml",
                        REPO / "roles/pazny.gitlab/defaults/main.yml") or "8929"
    project = f"{forge['owner']}%2F{forge['repo']}"
    url = f"http://127.0.0.1:{port}/api/v4/projects/{project}/merge_requests"
    payload = json.dumps({
        "source_branch": branch, "target_branch": base,
        "title": title, "description": description,
        "remove_source_branch": True,
    }).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 — loopback, fixed scheme
        url, data=payload, method="POST",
        headers={"PRIVATE-TOKEN": forge["token"], "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
            return response.status, body.get("web_url", "")
    except urllib.error.HTTPError as exc:
        return exc.code, _scrub(exc.read().decode("utf-8", "replace")[:400])
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return 0, f"{type(exc).__name__}: {_scrub(str(exc))}"


def _rejudge(uuid: str, gate_set: str, timeout: int) -> tuple[str, str]:
    """Re-run the judges against today's HEAD. Returns (result, detail).

    Shells out to `nos-loop` rather than speaking HTTP: ENGINE.md is explicit
    that the plugin holds no rules and the addresses live in one place, and the
    judge token belongs to that client. A driver with its own HTTP path would be
    a second place for the base URL and the credential to be wrong.
    """
    binary = shutil.which("nos-loop")
    if binary is None:
        return "indeterminate", "nos-loop is not on PATH — cannot re-judge"
    done = subprocess.run(  # noqa: S603
        [binary, "judge", "--gate-set", gate_set, "--proposal", uuid,
         "--wait", "--timeout", str(timeout), "--json"],
        text=True, capture_output=True, check=False,
    )
    try:
        payload = json.loads(done.stdout or "{}")
    except ValueError:
        return "indeterminate", f"nos-loop returned unparseable output (rc={done.returncode})"
    result = str(payload.get("result") or payload.get("verdict", {}).get("result") or "")
    # An unrecognised result is INDETERMINATE, never a pass — the same fallback
    # `nos-loop` itself applies at the shell boundary (DECISION 6a).
    if result not in ("pass", "fail", "indeterminate"):
        return "indeterminate", f"no verdict in the response (rc={done.returncode})"
    return result, ""


def land(row: dict, *, base: str, gate_set: str, rejudge: bool,
         timeout: int, act: bool, log) -> int:
    """Take one passed proposal as far as an open merge request."""
    wid = row["weakness_id"]
    state = row["state"]

    if state == "re-judge":
        if not rejudge:
            log(f"  {wid}: verdict decayed — re-run the judges with --rejudge")
            return 0
        if not act:
            log(f"  {wid}: WOULD re-judge against HEAD, then land if it passes")
            return 0
        log(f"  {wid}: re-judging against HEAD (the gate set runs pytest; minutes)")
        result, detail = _rejudge(row["uuid"], gate_set, timeout)
        if result != "pass":
            log(f"  {wid}: re-judge returned {result}"
                f"{' — ' + detail if detail else ''}; nothing landed")
            return 0
        log(f"  {wid}: re-judged pass on HEAD")
    elif state != "ready":
        log(f"  {wid}: state is {state} — not the driver's to fix "
            f"(a conflicted or malformed patch needs a new proposal)")
        return 0

    if not act:
        log(f"  {wid}: WOULD branch, push to gitea + gitlab, and open an MR → {base}")
        return 0

    gitea, gitlab = _forge("gitea"), _forge("gitlab")
    subject, body = _commit_message(row)
    branch = f"fix/loop-{str(wid).replace(':', '-').lower()}-{row['uuid'][:8]}"

    base_ref = base if _git("rev-parse", "--verify", "--quiet",
                            f"refs/heads/{base}", check=False) else "HEAD"
    work = pathlib.Path(tempfile.mkdtemp(prefix="nos-loop-pr-"))
    tree = work / "t"
    try:
        # Detached, off BASE — never the operator's checkout, and never their
        # current HEAD (on a leading branch the MR would carry unrelated commits).
        _git("worktree", "add", "--detach", "-q", str(tree), base_ref)
        _git("switch", "-qc", branch, cwd=tree)
        apply_ = subprocess.run(  # noqa: S603
            ["git", "apply", "-"], cwd=str(tree), input=row["_diff"],
            text=True, capture_output=True, check=False,
        )
        if apply_.returncode != 0:
            log(f"  {wid}: the patch did not apply on {base_ref} "
                f"({apply_.stderr.strip().splitlines()[0] if apply_.stderr else 'no reason given'})")
            return 1
        _git("add", "-A", cwd=tree)
        _git("commit", "-q", "-m", subject, "-m", body, cwd=tree)
        sha = _git("rev-parse", "HEAD", cwd=tree)

        # Gitea FIRST — it carries the CI, and a branch on the review surface
        # with no pipeline behind it is the thing the reviewer cannot act on.
        for forge in (gitea, gitlab):
            url = (f"https://oauth2:{forge['token']}@{forge['domain']}"
                   f"/{forge['owner']}/{forge['repo']}.git")
            done = subprocess.run(  # noqa: S603
                ["git", "push", url, branch], cwd=str(tree),
                text=True, capture_output=True, check=False,
            )
            if done.returncode != 0:
                log(f"  {wid}: push to {forge['name']} failed — "
                    f"{_scrub(done.stderr.strip().splitlines()[-1] if done.stderr else '')}")
                return 1
            log(f"  {wid}: pushed {branch} → {forge['name']}")
        log(f"  {wid}: commit {sha[:8]} — Woodpecker runs against this sha on gitea")

        http, detail = _open_merge_request(gitlab, branch, base, subject, body)
        if http == 201:
            log(f"  {wid}: MR opened — {detail}")
            return 0
        if http == 409:
            log(f"  {wid}: an MR for {branch} → {base} already exists")
            return 0
        # A pushed branch with no MR is half-done work and must say so; a silent
        # exit 0 here left a commit stranded once already (recipe-pr, 2026-06-10).
        log(f"  {wid}: MR create returned {http or 'no response'} — the branch IS "
            f"pushed to both forges; open the MR by hand: {detail}")
        return 1
    finally:
        _git("worktree", "remove", "--force", str(tree), check=False)
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--open-mr", action="store_true",
                    help="act; without it this is a dry run and touches nothing")
    ap.add_argument("--uuid", help="act on exactly one proposal")
    ap.add_argument("--rejudge", action="store_true",
                    help="re-run the judges on proposals whose verdict decayed")
    ap.add_argument("--base", default="dev", help="target branch (default: dev)")
    ap.add_argument("--gate-set", default="repo")
    ap.add_argument("--timeout", type=int, default=1800,
                    help="seconds to wait for a re-judge (the repo set runs pytest)")
    args = ap.parse_args()

    def log(line: str) -> None:
        print(line, flush=True)

    try:
        _refuse_master(args.base)
        loop = _load_loop_status()
        report = loop.awaiting()
        if report.get("error"):
            raise Refused(report["error"])

        rows = [r for r in report["rows"] if r["state"] in ("ready", "re-judge")]
        if args.uuid:
            rows = [r for r in rows if r["uuid"].startswith(args.uuid)]
            if not rows:
                raise Refused(f"no ready or decayed proposal matches {args.uuid!r}")

        if not rows:
            log("no passed proposal is waiting to land")
            return 0

        # The reader deliberately does not hand back the patch — it reports
        # state, and a diff in a status object invites someone to apply it from
        # there. The driver fetches it from the ledger itself, read-only.
        diffs = _diffs_for(loop, [r["uuid"] for r in rows])

        log(f"{len(rows)} proposal(s) waiting; "
            f"{'acting' if args.open_mr else 'DRY RUN — nothing will be touched'}")
        worst = 0
        for row in rows:
            row["_diff"] = diffs.get(row["uuid"], "")
            if not row["_diff"]:
                log(f"  {row['weakness_id']}: the ledger row carries no patch")
                continue
            # One proposal's git failure must not abandon the others. A batch
            # that stops at the first bad patch processes the queue in an order
            # nobody chose, and the tail never gets looked at.
            try:
                outcome = land(
                    row, base=args.base, gate_set=args.gate_set,
                    rejudge=args.rejudge, timeout=args.timeout,
                    act=args.open_mr, log=log,
                )
            except Refused as exc:
                log(f"  {row['weakness_id']}: {exc}")
                outcome = 1
            worst = max(worst, outcome)
        if not args.open_mr:
            log("\n  re-run with --open-mr to act "
                "(add --rejudge to refresh a decayed verdict first)")
        return worst
    except Refused as exc:
        print(f"[loop-pr] {exc}", file=sys.stderr)
        return 2


def _diffs_for(loop, uuids: list[str]) -> dict[str, str]:
    """Patch text straight from the ledger, read-only, by uuid."""
    import sqlite3  # noqa: PLC0415 — only this function needs it

    if not uuids:
        return {}
    conn = sqlite3.connect(f"file:{loop.WING_DB}?mode=ro", uri=True)
    try:
        marks = ",".join("?" * len(uuids))
        return {
            row[0]: row[1] or ""
            for row in conn.execute(
                f"SELECT uuid, diff_text FROM loop_proposals WHERE uuid IN ({marks})",
                uuids,
            )
        }
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
