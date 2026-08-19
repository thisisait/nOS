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
import urllib.parse
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


def _base_exists(forge: dict, base: str) -> tuple[bool, str]:
    """Does BASE exist on this forge? Returns (ok, why-not).

    MEASURED THE DAY THIS WAS WRITTEN, and it is why the check is here rather
    than left to the push: GitLab's `root/nOS` was `empty_repo: true` with zero
    branches, and Gitea's token answered 401. Pushing into an empty project
    makes the pushed branch the project's DEFAULT — so the driver's first act
    would have been to install `fix/loop-rem-204-6f139e22` as the protected
    trunk of the review forge. The sibling bash guards this for the same reason
    (recipe-pr.sh, 2026-06-10); the driver shipped without it for about an hour.

    Fails CLOSED: an unreachable forge is not permission to push.
    """
    if forge["name"] == "gitlab":
        port = _yaml_lookup("gitlab_http_port", REPO / "config.yml",
                            REPO / "default.config.yml",
                            REPO / "roles/pazny.gitlab/defaults/main.yml") or "8929"
        url = (f"http://127.0.0.1:{port}/api/v4/projects/"
               f"{forge['owner']}%2F{forge['repo']}/repository/branches/{base}")
        headers = {"PRIVATE-TOKEN": forge["token"]}
    else:
        url = (f"https://{forge['domain']}/api/v1/repos/"
               f"{forge['owner']}/{forge['repo']}/branches/{base}")
        headers = {"Authorization": f"token {forge['token']}"}

    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return response.status == 200, ""
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return False, (
                f"{forge['name']} rejected the token (HTTP {exc.code}) — "
                f"re-provision it with the {forge['name']} playbook tag"
            )
        return False, (
            f"branch {base!r} not found on {forge['name']} (HTTP {exc.code}) — "
            f"push the trunk first: tools/sync-trunk-to-{forge['name']}.sh"
        )
    except (urllib.error.URLError, OSError) as exc:
        return False, (
            f"{forge['name']} unreachable ({type(exc).__name__}) — refusing to "
            f"push, because an unreachable forge is not an empty one"
        )


def _remote_tip(forge: dict, branch: str) -> tuple[str | None, str | None]:
    """The sha this branch points at on the forge, or None if it does not exist.

    Returns (sha, error). A forge that cannot be asked is an ERROR, never
    "absent" — a plain push into a branch we could not see would either fail
    non-fast-forward (the MR !1 wedge this exists to fix) or, worse, race a
    state nobody examined. Fail closed, same doctrine as `_base_exists`.

    THE SLASH IN THE BRANCH NAME IS PER-FORGE, and both readings were paid
    for on 2026-08-19, one run apart: GitLab's branches endpoint 404s on the
    RAW slash — and 404 is this function's word for "absent", so the first
    live refresh read an EXISTING GitLab branch as missing, plain-pushed and
    was refused non-fast-forward. Encoding BOTH then broke the other half:
    Gitea answers 400 to `%2F` in the path (its router splits on raw slashes).
    So: GitLab gets `%2F`, Gitea gets the slash, and the gate pins each to
    its forge rather than to a tidy-looking rule.
    """
    if forge["name"] == "gitlab":
        port = _yaml_lookup("gitlab_http_port", REPO / "config.yml",
                            REPO / "default.config.yml",
                            REPO / "roles/pazny.gitlab/defaults/main.yml") or "8929"
        encoded = urllib.parse.quote(branch, safe="")
        url = (f"http://127.0.0.1:{port}/api/v4/projects/"
               f"{forge['owner']}%2F{forge['repo']}/repository/branches/{encoded}")
        headers = {"PRIVATE-TOKEN": forge["token"]}
    else:
        url = (f"https://{forge['domain']}/api/v1/repos/"
               f"{forge['owner']}/{forge['repo']}/branches/{branch}")
        headers = {"Authorization": f"token {forge['token']}"}
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, None
        return None, f"{forge['name']} answered HTTP {exc.code} for branch {branch!r}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, f"{forge['name']} unreachable asking for {branch!r} ({type(exc).__name__})"
    sha = (body.get("commit") or {}).get("id") or (body.get("commit") or {}).get("sha")
    if not sha:
        return None, f"{forge['name']} returned no commit sha for {branch!r}"
    return str(sha), None


def _edit_lines(diff_text: str) -> list[str]:
    """The +/- payload of a diff, headers dropped — same normalization as the
    reviewer's `_same_change`, duplicated as data-shape rather than shared,
    because the reviewer must not import the tool it audits."""
    return [
        line.rstrip()
        for line in diff_text.splitlines()
        if line[:1] in ("+", "-") and not line.startswith(("+++", "---"))
    ]


def _owns_remote_tip(tree: pathlib.Path, url: str, remote_sha: str,
                     proposal_uuid: str, judged_diff: str) -> tuple[bool, str]:
    """Is the branch tip on the forge a commit THIS driver made for THIS
    proposal? Only then may the driver overwrite it.

    Two proofs, both required:
      1. the tip's commit message names the proposal uuid (the driver writes
         it into every body — see `_commit_message`'s caller);
      2. the tip's diff against its parent makes the same +/- edits as the
         judged patch, so "a human reused our branch name for real work" can
         never be swept away by matching one line of prose.

    Anything unverifiable is NOT ours. A force that cannot prove its target
    is the driver's own work is a force onto somebody else's.
    """
    fetched = subprocess.run(  # noqa: S603
        ["git", "fetch", "-q", url, remote_sha], cwd=str(tree),
        text=True, capture_output=True, check=False,
    )
    if fetched.returncode != 0:
        return False, f"could not fetch {remote_sha[:8]} to examine it"
    message = _git("show", "-s", "--format=%B", remote_sha, cwd=tree, check=False)
    if proposal_uuid not in message:
        return False, (f"tip {remote_sha[:8]} does not name proposal "
                       f"{proposal_uuid[:8]} — not the driver's commit")
    tip_diff = _git("show", "--format=", remote_sha, cwd=tree, check=False)
    if _edit_lines(tip_diff) != _edit_lines(judged_diff):
        return False, (f"tip {remote_sha[:8]} names the proposal but carries a "
                       f"different change — refusing to overwrite it")
    return True, ""


def _ci_hook_count(forge: dict) -> int | None:
    """How many webhooks the Gitea repo carries, or None if we could not ask.

    A push to a repo with no hook produces no pipeline, and a missing pipeline
    looks exactly like a pending one to anybody reading the merge request. None
    is returned rather than 0 on a failed question, because "we could not ask"
    and "there are none" are the two readings this estate most often confuses.
    """
    url = (f"https://{forge['domain']}/api/v1/repos/"
           f"{forge['owner']}/{forge['repo']}/hooks")
    request = urllib.request.Request(  # noqa: S310
        url, headers={"Authorization": f"token {forge['token']}"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
            return len(payload) if isinstance(payload, list) else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


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
    # A refusal carries the engine's own reason and ENGINE.md is explicit that a
    # client quotes it rather than restating it. Swallowing this cost the first
    # live run its diagnosis: "no verdict in the response" was true and useless,
    # where the engine had said exactly what was wrong.
    detail = payload.get("detail")
    if isinstance(detail, dict) and detail.get("reason"):
        return "indeterminate", f"engine refused ({detail['reason']}): {detail.get('detail', '')}"
    result = str(payload.get("result") or payload.get("verdict", {}).get("result") or "")
    # An unrecognised result is INDETERMINATE, never a pass — the same fallback
    # `nos-loop` itself applies at the shell boundary (DECISION 6a).
    if result not in ("pass", "fail", "indeterminate"):
        return "indeterminate", f"no verdict in the response (rc={done.returncode})"
    return result, ""


def land(row: dict, *, base: str, gate_set: str, rejudge: bool,
         timeout: int, act: bool, log) -> int:
    """Take one passed proposal as far as an open merge request.

    `gate_set` is the one the PROPOSAL declared — see `_diffs_for`.
    """
    wid = row["weakness_id"]
    state = row["state"]
    if state == "re-judge" and rejudge and not gate_set:
        log(f"  {wid}: the ledger row declares no gate set — cannot re-judge")
        return 1

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
    # Both forges must be able to receive this BEFORE any branch is cut. Half a
    # landing — a commit on Gitea, nothing on GitLab — is worse than none: the
    # CI goes green on a change no reviewer can see.
    for forge in (gitea, gitlab):
        ok, why = _base_exists(forge, base)
        if not ok:
            log(f"  {wid}: {why}")
            return 2
    subject, body = _commit_message(row)
    branch = f"fix/loop-{str(wid).replace(':', '-').lower()}-{row['uuid'][:8]}"

    base_ref = base if _git("rev-parse", "--verify", "--quiet",
                            f"refs/heads/{base}", check=False) else "HEAD"
    work = pathlib.Path(tempfile.mkdtemp(prefix="nos-loop-pr-"))
    tree = work / "t"
    try:
        # Detached, off BASE — never the operator's checkout, and never their
        # current HEAD (on a leading branch the MR would carry unrelated commits).
        # And it STAYS detached: the first version ran `git switch -c <branch>`
        # here, which mints a repo-wide local ref the worktree removal does not
        # delete — so the second run of the same proposal died on "a branch
        # named fix/loop-… already exists" (measured 2026-08-19, minutes after
        # the refresh path shipped). The branch exists on the FORGES, as the
        # push refspec below; this clone never needs the ref at all.
        _git("worktree", "add", "--detach", "-q", str(tree), base_ref)
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
        #
        # RE-RUNS REFRESH IN PLACE. One proposal is one branch is one MR for
        # its whole life: when the base moves and the driver runs again, it
        # overwrites its OWN previous tip with `--force-with-lease` pinned to
        # the sha it just verified, and the existing MR simply tracks the new
        # commit — no branch-per-base proliferation, no supersede chain to
        # garbage-collect, and nothing to close. Measured need: MR !1's commit
        # predated the forge webhook, so no pipeline could ever exist for it,
        # and a plain push was refused non-fast-forward. The overwrite is
        # gated on `_owns_remote_tip`: a tip the driver cannot PROVE it made
        # for this proposal is never forced, so a human's work under a
        # borrowed branch name survives every unattended run.
        refreshed = False
        for forge in (gitea, gitlab):
            url = (f"https://oauth2:{forge['token']}@{forge['domain']}"
                   f"/{forge['owner']}/{forge['repo']}.git")
            tip, tip_err = _remote_tip(forge, branch)
            if tip_err:
                log(f"  {wid}: {tip_err} — refusing to push blind")
                return 2
            push_argv = ["git", "push", url, f"HEAD:refs/heads/{branch}"]
            if tip and tip != sha:
                owned, why = _owns_remote_tip(tree, url, tip, row["uuid"], row["_diff"])
                if not owned:
                    log(f"  {wid}: {forge['name']} already carries {branch} and "
                        f"{why}. Not forcing; if that work is real it needs a "
                        f"reviewer, and if it is stale the operator deletes it")
                    return 2
                push_argv = ["git", "push",
                             f"--force-with-lease=refs/heads/{branch}:{tip}",
                             url, f"HEAD:refs/heads/{branch}"]
                refreshed = True
            done = subprocess.run(  # noqa: S603
                push_argv, cwd=str(tree),
                text=True, capture_output=True, check=False,
            )
            if done.returncode != 0:
                log(f"  {wid}: push to {forge['name']} failed — "
                    f"{_scrub(done.stderr.strip().splitlines()[-1] if done.stderr else '')}")
                return 1
            log(f"  {wid}: pushed {branch} → {forge['name']}"
                f"{' (refreshed the driver’s previous tip in place)' if refreshed else ''}")
        # NOT "Woodpecker runs against this sha" — that was the first version of
        # this line and it was a claim, in a tool written to replace claims with
        # measurements. Measured minutes later: the Gitea repo carried ZERO
        # webhooks (the agent-forge conversion recreates the repo and drops the
        # A16 autowire hook), so the push triggered nothing and the MR would have
        # been reviewed as though a pipeline were pending. Ask, then say.
        hooks = _ci_hook_count(gitea)
        if hooks is None:
            log(f"  {wid}: commit {sha[:8]} — could not ask Gitea whether a CI "
                f"hook exists, so whether Woodpecker saw this is UNKNOWN")
        elif hooks == 0:
            log(f"  {wid}: commit {sha[:8]} — WARNING: the Gitea repo has no "
                f"webhook, so Woodpecker did NOT see this push. The MR has no "
                f"pipeline behind it; activate the repo in Woodpecker first")
        else:
            log(f"  {wid}: commit {sha[:8]} — {hooks} Gitea webhook(s) fired; "
                f"read the verdict from Woodpecker, not from here")

        http, detail = _open_merge_request(gitlab, branch, base, subject, body)
        if http == 201:
            log(f"  {wid}: MR opened — {detail}")
            return 0
        if http == 409:
            if refreshed:
                log(f"  {wid}: the existing MR for {branch} → {base} now tracks "
                    f"{sha[:8]} — GitLab MRs follow their source branch, so the "
                    f"refresh IS the update; CI runs on the new sha")
            else:
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
            found = diffs.get(row["uuid"], {})
            row["_diff"] = found.get("diff", "")
            row["_gate_set"] = found.get("gate_set", "")
            if not row["_diff"]:
                log(f"  {row['weakness_id']}: the ledger row carries no patch")
                continue
            # One proposal's git failure must not abandon the others. A batch
            # that stops at the first bad patch processes the queue in an order
            # nobody chose, and the tail never gets looked at.
            try:
                outcome = land(
                    row, base=args.base, gate_set=row["_gate_set"],
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


def _diffs_for(loop, uuids: list[str]) -> dict[str, dict]:
    """Patch text AND declared gate set, straight from the ledger, by uuid.

    THE GATE SET IS THE PROPOSAL'S, NOT THE DRIVER'S. Measured on the first
    live run: the driver passed `--gate-set repo` and the engine refused —
    *"proposal … declared gate set 'fast'; judging it with 'repo' would seal a
    verdict the budget was never computed for"*. It is right. The budget, the
    oracle paths and the min_work ratchets were all computed for the declared
    set at propose time, so a driver that picks a different one is asking for a
    verdict about a different question. ENGINE.md says it generally: everything
    a client might decide, the engine already decided.
    """
    import sqlite3  # noqa: PLC0415 — only this function needs it

    if not uuids:
        return {}
    conn = sqlite3.connect(f"file:{loop.WING_DB}?mode=ro", uri=True)
    try:
        marks = ",".join("?" * len(uuids))
        return {
            row[0]: {"diff": row[1] or "", "gate_set": row[2] or ""}
            for row in conn.execute(
                f"SELECT uuid, diff_text, gate_set FROM loop_proposals "
                f"WHERE uuid IN ({marks})",
                uuids,
            )
        }
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
