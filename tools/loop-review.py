#!/usr/bin/env python3
"""The reviewer: the only thing in the loop permitted to merge.

WHAT IT IS FOR. `tools/loop-pr.py` opens a merge request and stops — deliberately,
because the component that authors a change must not be the one that blesses it.
Something still has to close the loop, and on this estate that something cannot
be a human standing by: the operator asked for a loop that keeps turning while
they sleep. This is that step, and it is built to be the most suspicious tool in
the repository.

THE THREE QUESTIONS, AND WHY ALL THREE

A merge request may be merged only when every one of these is answered YES.
Any NO refuses. Any *unanswerable* question is INDETERMINATE, which also
refuses — and is reported as its own outcome, never folded into either
neighbour (`docs/idea/11-agentic-loop-contract.md` §2.4).

  1. **Did CI pass on this exact commit?** Woodpecker, keyed on the head sha.
     Measured 2026-08-19, and the reason this question is first: the Gitea repo
     carried ZERO webhooks, so pushes started no pipelines at all — and an MR
     with no pipeline is indistinguishable from one whose pipeline is queued.
     "No pipeline" is INDETERMINATE. It is emphatically not "nothing failed".
  2. **Did the judges pass this proposal?** The ledger, read-only. A green CI on
     a patch no judge ruled on is a test suite agreeing with itself.
  3. **Is the diff in the MR the diff that was judged?** Byte-comparison against
     the proposal's recorded patch. Without this the first two answers are about
     a different change than the one that would land — the oldest trick there
     is, and the cheapest to close.

WHAT IT WILL NOT TOUCH

  * Any MR whose source branch it did not create. It merges `fix/loop-*` and
    nothing else, so a human's work in the same forge can never be swept up by
    an unattended run.
  * `master`. dev → master is the operator's PR and non-beta tags are theirs
    too; this ends at `dev` (CLAUDE.md § Git Workflow).
  * The ledger. It writes nothing there, for the same reason the driver does
    not: whether a patch landed is git's answer, read back afterwards by
    `tools/loop-status.py --awaiting`.

IDENTITY. The reviewer holds a forge credential and NO loop-propose scope. The
chain is now four identities — proposer, judge, driver, reviewer — and the rule
generalises the contract's §3.4: whoever writes a change may not bless it, and
no step records its own success.

DRY RUN BY DEFAULT:

    tools/loop-review.py                # report a verdict per MR, merge nothing
    tools/loop-review.py --merge        # act on every MR that answers YES×3
    tools/loop-review.py --mr 1         # look at exactly one

Exit 0 when every MR examined reached a decision, 1 when something was left
half-done, 2 on configuration it will not guess at.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sqlite3
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]

#: Only branches the driver cuts. A reviewer that could merge an arbitrary
#: branch is an unattended merge button on the operator's own work.
DRIVER_BRANCH_PREFIX = "fix/loop-"

MERGED, REFUSED, INDETERMINATE = "merged", "refused", "indeterminate"

#: Module-level so a gate can point it at a fixture. It was inlined until the
#: retro-verification of `test_the_reviewer_refuses_before_it_merges.py` found
#: that removing the diff comparison from `ledger_verdict` kept the suite green
#: — the tests exercised `_same_change` alone and never the function that calls
#: it, so the most important question of the three was unguarded.
LEDGER = pathlib.Path.home() / "wing" / "app" / "data" / "wing.db"


class Refused(Exception):
    """A condition the reviewer will not work around."""


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / filename)
    if spec is None or spec.loader is None:
        raise Refused(f"cannot load tools/{filename}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _api(url: str, headers: dict, *, method: str = "GET",
         payload: dict | None = None) -> tuple[int, object]:
    """One HTTP call. Returns (status, parsed-json-or-raw-text).

    A 200 whose body is not JSON is returned as text ON PURPOSE, so callers can
    tell an answer from a front-end. Woodpecker's SPA serves index.html as a
    catch-all and certified an entire activation path as healthy off 1679 bytes
    of HTML (roles/pazny.woodpecker/tasks/post-repo.yml, 2026-08-19).
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    if data is not None:
        headers = {**headers, "Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, method=method,  # noqa: S310
                                     headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            body = response.read().decode("utf-8", "replace")
            try:
                return response.status, json.loads(body)
            except ValueError:
                return response.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:300]
    except (urllib.error.URLError, OSError) as exc:
        return 0, f"{type(exc).__name__}: {exc}"


# ── question 1: did CI pass on this exact commit? ────────────────────────────

def ci_verdict(sha: str, driver) -> tuple[str, str]:
    """Woodpecker's answer for one commit: pass / fail / indeterminate.

    Keyed on the SHA and nothing else. Not "the latest pipeline on the branch"
    — that is a different commit's answer wearing this one's name.
    """
    token = driver._yaml_lookup(
        "woodpecker_api_token", REPO / "credentials.yml", REPO / "config.yml",
        pathlib.Path.home() / ".nos" / "secrets.yml")
    port = driver._yaml_lookup("woodpecker_port", REPO / "config.yml",
                               REPO / "default.config.yml") or "8060"
    if not token:
        return INDETERMINATE, "no woodpecker_api_token — CI state cannot be read"

    # `woodpecker_nos_repo_owner` defaults to a Jinja expression
    # (`{{ gitea_admin_user }}`), which the lookup skips by design — so fall
    # back to the GITEA forge coordinates rather than to a literal. Measured:
    # the literal fallback asked woodpecker about `nos/nOS`, a repo that does
    # not exist, and would have reported "no pipeline" for a healthy one.
    gitea = driver.FORGE_KEYS["gitea"]
    owner = (driver._yaml_lookup("woodpecker_nos_repo_owner", REPO / "config.yml")
             or driver._yaml_lookup(gitea["owner_key"], REPO / "config.yml",
                                    REPO / "default.config.yml",
                                    REPO / gitea["role_defaults"])
             or gitea["owner_default"])
    name = (driver._yaml_lookup("woodpecker_nos_repo_name", REPO / "config.yml")
            or driver._yaml_lookup(gitea["name_key"], REPO / "config.yml",
                                   REPO / "default.config.yml",
                                   REPO / gitea["role_defaults"])
            or gitea["name_default"])
    base = f"http://127.0.0.1:{port}"
    headers = {"Authorization": f"Bearer {token}"}

    status, body = _api(f"{base}/api/repos/lookup/{owner}/{name}", headers)
    if status != 200 or not isinstance(body, dict) or "id" not in body:
        return INDETERMINATE, (
            f"woodpecker did not answer for {owner}/{name} (HTTP {status}"
            f"{', HTML — the SPA catch-all' if isinstance(body, str) else ''})")

    status, pipelines = _api(f"{base}/api/repos/{body['id']}/pipelines", headers)
    if status != 200 or not isinstance(pipelines, list):
        return INDETERMINATE, f"woodpecker pipeline list unreadable (HTTP {status})"

    mine = [p for p in pipelines if str(p.get("commit", "")).startswith(sha[:8])]
    if not mine:
        # THE case this estate actually hit. Say it plainly.
        return INDETERMINATE, (
            f"no pipeline exists for {sha[:8]} — CI never ran on this commit. "
            f"That is not a pass; is the forge webhook wired?")
    latest = sorted(mine, key=lambda p: p.get("number", 0))[-1]
    state = str(latest.get("status", ""))
    if state == "success":
        return "pass", f"pipeline #{latest.get('number')} succeeded"
    if state in ("pending", "running", "blocked"):
        return INDETERMINATE, f"pipeline #{latest.get('number')} is {state}"
    return "fail", f"pipeline #{latest.get('number')} is {state}"


# ── question 2 + 3: did the judges pass THIS diff? ───────────────────────────

def ledger_verdict(proposal_uuid: str, mr_diff: str) -> tuple[str, str]:
    """The ledger's answer, and whether the MR carries the judged patch.

    Read-only, always. Two questions in one place because they share a row and
    separating them would invite answering the first without the second.
    """
    if not LEDGER.is_file():
        return INDETERMINATE, f"no ledger at {LEDGER}"
    conn = sqlite3.connect(f"file:{LEDGER}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT p.diff_text, v.result
              FROM loop_proposals p
              JOIN loop_verdicts v ON v.id = (
                       SELECT id FROM loop_verdicts
                        WHERE proposal_id = p.id ORDER BY id DESC LIMIT 1)
             WHERE p.uuid LIKE ?
            """, (f"{proposal_uuid}%",)).fetchone()
    finally:
        conn.close()

    if row is None:
        return INDETERMINATE, f"no judged proposal matches {proposal_uuid}"
    if row["result"] != "pass":
        return "fail", f"the judges returned {row['result']}"
    if not _same_change(row["diff_text"] or "", mr_diff):
        return "fail", (
            "the merge request does not carry the judged patch — the change "
            "that would land is not the change that was judged")
    return "pass", "judges passed this proposal, and the MR carries that patch"


def _same_change(judged: str, offered: str) -> bool:
    """Do these two diffs make the same edit?

    Compared on the +/- lines alone. Hunk headers carry offsets that shift with
    any unrelated edit above them, and file headers differ between `git diff`
    and a forge's rendering — comparing raw text would refuse every honest MR
    and teach whoever runs this to stop trusting the check.
    """
    def edits(text: str) -> list[str]:
        return [
            line.rstrip()
            for line in text.splitlines()
            if line[:1] in ("+", "-") and not line.startswith(("+++", "---"))
        ]
    return bool(edits(judged)) and edits(judged) == edits(offered)


# ── the forge ────────────────────────────────────────────────────────────────

def _gitlab(driver) -> tuple[dict, str]:
    forge = driver._forge("gitlab")
    port = driver._yaml_lookup("gitlab_http_port", REPO / "config.yml",
                               REPO / "default.config.yml",
                               REPO / "roles/pazny.gitlab/defaults/main.yml") or "8929"
    project = f"{forge['owner']}%2F{forge['repo']}"
    return forge, f"http://127.0.0.1:{port}/api/v4/projects/{project}"


def open_requests(driver, base: str) -> list[dict]:
    forge, api = _gitlab(driver)
    headers = {"PRIVATE-TOKEN": forge["token"]}
    status, body = _api(f"{api}/merge_requests?state=opened&target_branch={base}",
                        headers)
    if status != 200 or not isinstance(body, list):
        raise Refused(f"GitLab did not list merge requests (HTTP {status}): {body}")
    return body


def review(mr: dict, driver, *, act: bool, log) -> str:
    """Answer the three questions for one merge request, and act on the answer."""
    iid, branch = mr.get("iid"), str(mr.get("source_branch", ""))
    sha = str(mr.get("sha") or "")
    label = f"MR !{iid} ({branch})"

    if not branch.startswith(DRIVER_BRANCH_PREFIX):
        log(f"  {label}: not a driver branch — left alone")
        return REFUSED

    forge, api = _gitlab(driver)
    headers = {"PRIVATE-TOKEN": forge["token"]}

    status, diff_body = _api(f"{api}/merge_requests/{iid}/raw_diffs", headers)
    if status != 200 or not isinstance(diff_body, str):
        log(f"  {label}: INDETERMINATE — cannot read the MR diff (HTTP {status})")
        return INDETERMINATE

    # The proposal uuid is the branch's last segment, put there by the driver.
    proposal = branch.rsplit("-", 1)[-1]

    ci, ci_why = ci_verdict(sha, driver)
    led, led_why = ledger_verdict(proposal, diff_body)

    log(f"  {label} @ {sha[:8]}")
    log(f"      CI      {ci:<14} {ci_why}")
    log(f"      judges  {led:<14} {led_why}")

    if ci == "fail" or led == "fail":
        log("      → REFUSED")
        return REFUSED
    if ci != "pass" or led != "pass":
        log("      → INDETERMINATE, so not merged. An unanswered question is "
            "not a yes.")
        return INDETERMINATE
    if not act:
        log("      → WOULD MERGE (re-run with --merge)")
        return MERGED

    status, body = _api(f"{api}/merge_requests/{iid}/merge", headers,
                        method="PUT", payload={"should_remove_source_branch": True})
    if status == 200:
        log(f"      → MERGED into {mr.get('target_branch')}")
        return MERGED
    log(f"      → merge call returned {status}: {body}")
    return REFUSED


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--merge", action="store_true",
                    help="act; without it this reports and merges nothing")
    ap.add_argument("--mr", type=int, help="review exactly one merge request iid")
    ap.add_argument("--base", default="dev", help="target branch (default: dev)")
    args = ap.parse_args()

    def log(line: str) -> None:
        print(line, flush=True)

    try:
        driver = _load("_loop_pr", "loop-pr.py")
        driver._refuse_master(args.base)

        requests = open_requests(driver, args.base)
        if args.mr:
            requests = [m for m in requests if m.get("iid") == args.mr]
            if not requests:
                raise Refused(f"no open merge request !{args.mr} targeting {args.base}")
        if not requests:
            log(f"no open merge request targets {args.base}")
            return 0

        log(f"{len(requests)} open merge request(s) → {args.base}; "
            f"{'acting' if args.merge else 'DRY RUN — nothing will be merged'}")
        outcomes = [review(mr, driver, act=args.merge, log=log) for mr in requests]
        log(f"\n  {outcomes.count(MERGED)} merged · {outcomes.count(REFUSED)} refused "
            f"· {outcomes.count(INDETERMINATE)} indeterminate")
        return 0
    except Refused as exc:
        print(f"[loop-review] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
