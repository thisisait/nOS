"""The driver may open a door. It may not walk through it.

WHAT THE DRIVER IS. `tools/loop-pr.py` is the step that was missing between a
passed verdict and a tree that never changed (measured 2026-08-19; see
`tests/anatomy/test_a_passed_verdict_is_never_silent.py` for that measurement).
It takes a proposal the judges passed, commits it on a branch, pushes it to both
forges and opens a merge request. Then it stops.

WHY EVERY ASSERTION HERE IS ABOUT SOMETHING IT MUST **NOT** DO. A driver is the
first component in this loop that writes to shared state, and every previous
component was designed so that it could not. The engine has no route that accepts
a verdict; the ledger splits propose, judge and seal across capabilities; the
reporter opens SQLite read-only. All of that is undone by one driver that merges,
or stamps, or quietly reaches for a second token — so the boundaries are pinned
by execution here rather than by prose in a header nobody reads twice.

WHAT THIS FILE PINS

  1. **Dry run is the default.** No `--open-mr`, no git mutation, no network. A
     tool whose default acts is one wrong tab-completion from a push.
  2. **`master` is refused before anything happens.** dev → master is the
     operator's PR (CLAUDE.md § Git Workflow). Refused locally so the failure
     names the rule instead of arriving as a server-side rejection later.
  3. **The operator's checkout is never touched.** Its bash siblings `git switch`
     the live tree and stash around it, which stranded that tree on a `fix/*`
     branch more than once — and this host routinely runs a second interactive
     session in the same clone. Every mutation must happen inside a detached
     worktree.
  4. **Gitea is pushed BEFORE the merge request opens.** Gitea carries the CI
     (Woodpecker watches it, `.woodpecker/tests.yml` fires on any branch); GitLab
     has no runner and no `.gitlab-ci.yml`. An MR opened against a branch Gitea
     never saw is a review with no green light behind it — and it looks exactly
     like one that has it.
  5. **It never merges.** No API call, no `git merge`, no `git push` to a base
     branch. This is the whole boundary between a driver and an operator.
  6. **It never writes to the ledger.** Constraint B
     (`docs/idea/11-agentic-loop-contract.md` §3.5): a driver that stamped
     "landed" would be a step recording its own success, which is the defect
     class this estate has paid for four times.
  7. **A pushed branch with no MR exits non-zero.** Half-done work that reports
     success is how a commit sat stranded on a pushed branch once already.
  8. **A token never reaches the output.** git echoes the push URL on failure and
     that URL carries the credential.
  9. **The forge coordinates do not drift from the bash siblings.** The keys are
     duplicated deliberately; the gate is what makes that safe.

CI-safe: every git call and every HTTP call is a fake. Nothing here reaches a
forge, a daemon, a network or the real ledger.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DRIVER = REPO / "tools" / "loop-pr.py"
RECIPE_PR = REPO / "tools" / "recipe-pr.sh"


@pytest.fixture(scope="module")
def drv():
    spec = importlib.util.spec_from_file_location("_loop_pr_gate", DRIVER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Recorder:
    """Stands in for subprocess.run and remembers every argv it was handed."""

    def __init__(self, rc: int = 0, stdout: str = "deadbeefcafe", stderr: str = "",
                 fail_on: str | None = None):
        self.calls: list[dict] = []
        self.rc, self.stdout, self.stderr = rc, stdout, stderr
        #: When set, only the git subcommand named here fails. Failing EVERY
        #: call would abort at the worktree step and never reach the behaviour
        #: under test — which is how the first draft of this fixture passed for
        #: the wrong reason.
        self.fail_on = fail_on

    def __call__(self, argv, **kw):
        self.calls.append({"argv": list(argv), "cwd": kw.get("cwd"),
                           "input": kw.get("input")})
        argv = list(argv)
        failing = self.fail_on is None or (len(argv) > 1 and argv[1] == self.fail_on)

        class Done:
            returncode = self.rc if failing else 0
            stdout, stderr = self.stdout, (self.stderr if failing else "")
        return Done()

    def argvs(self) -> list[list[str]]:
        return [c["argv"] for c in self.calls]

    def pushes(self) -> list[list[str]]:
        return [a for a in self.argvs() if a[:2] == ["git", "push"]]


@pytest.fixture
def ready_row():
    return {
        "uuid": "6f139e22-6793-4a88-bfa2-fc136a91506a",
        "weakness_id": "rem:REM-204",
        "intent_class": "version-pin-bump",
        "proposer_id": "agent:claude-opus-5",
        "target_paths": ["default.config.yml"],
        "state": "ready",
        "_diff": "--- a/x\n+++ b/x\n",
    }


@pytest.fixture
def wired(drv, monkeypatch):
    """The driver with both forges faked and the MR call stubbed to 201."""
    monkeypatch.setattr(drv, "_forge", lambda name: {
        "name": name, "token": "FAKE_not_a_real_token", "domain": f"{name}.invalid",
        "owner": "o", "repo": "nOS",
    })
    monkeypatch.setattr(drv, "_base_exists", lambda forge, base: (True, ""))
    # The topology preflight has its own gate (test_the_driver_refuses_a_desynced_base);
    # here the four holders are stipulated to agree so the rest of the landing runs.
    monkeypatch.setattr(drv, "_base_alignment", lambda *a, **k: (True, ""))
    # No branch exists on either forge — the plain-push path. The refresh path
    # has its own section below; without this stub the tip lookup would reach
    # for a real network (the GitLab half asks 127.0.0.1, i.e. the LIVE forge).
    monkeypatch.setattr(drv, "_remote_tip", lambda forge, branch: (None, None))
    opened: list[dict] = []
    monkeypatch.setattr(drv, "_open_merge_request",
                        lambda forge, branch, base, title, desc:
                        (opened.append({"forge": forge["name"], "branch": branch,
                                        "base": base, "title": title}), (201, "http://mr/1"))[1])
    return opened


def test_the_driver_exists_and_lints_as_a_module(drv):
    """Positive control: everything below drives this module."""
    assert DRIVER.is_file() and hasattr(drv, "land") and hasattr(drv, "main")


# ── 1 + 2. defaults and refusals ─────────────────────────────────────────────

def test_dry_run_is_the_default(drv, monkeypatch, ready_row, wired):
    rec = Recorder()
    monkeypatch.setattr(drv.subprocess, "run", rec)
    rc = drv.land(ready_row, base="dev", gate_set="repo", rejudge=False,
                  timeout=1, act=False, log=lambda _: None)
    assert rc == 0
    assert rec.calls == [], (
        f"a dry run executed {rec.argvs()}; without --open-mr the driver must "
        f"touch nothing at all"
    )
    assert wired == [], "a dry run opened a merge request"


@pytest.mark.parametrize("base", ["master", "main"])
def test_master_is_refused_before_anything_happens(drv, base):
    with pytest.raises(drv.Refused) as exc:
        drv._refuse_master(base)
    assert "operator" in str(exc.value).lower()


def test_the_refusal_is_reached_from_the_command_line(drv, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["loop-pr.py", "--base", "master", "--open-mr"])
    rec = Recorder()
    monkeypatch.setattr(drv.subprocess, "run", rec)
    assert drv.main() == 2
    assert rec.calls == [], "the master refusal ran after git had already been called"


# ── 3 + 4 + 5. where it works, what it pushes, what it never does ────────────

def test_every_mutation_happens_in_a_detached_worktree(drv, monkeypatch,
                                                       ready_row, wired):
    rec = Recorder()
    monkeypatch.setattr(drv.subprocess, "run", rec)
    drv.land(ready_row, base="dev", gate_set="repo", rejudge=False,
             timeout=1, act=True, log=lambda _: None)

    argvs = rec.argvs()
    assert any(a[:3] == ["git", "worktree", "add"] and "--detach" in a for a in argvs), (
        "no detached worktree was created; the driver is working in the "
        "operator's checkout, where a second live session may be mid-edit"
    )
    # Nothing that mutates may run with cwd at the repo root.
    mutating = {"switch", "commit", "apply", "add", "push", "checkout", "stash", "merge"}
    offenders = [
        c for c in rec.calls
        if len(c["argv"]) > 1 and c["argv"][0] == "git" and c["argv"][1] in mutating
        and str(c["cwd"]) == str(drv.REPO)
    ]
    assert not offenders, (
        f"these ran against the operator's checkout: "
        f"{[c['argv'][:3] for c in offenders]}"
    )
    assert any(a[:3] == ["git", "worktree", "remove"] for a in argvs), (
        "the worktree is never removed — the driver leaks a checkout per run"
    )


def test_gitea_is_pushed_before_the_merge_request_opens(drv, monkeypatch,
                                                        ready_row, wired):
    """The CI half must exist before the review half is offered.

    Reversing these leaves a reviewer looking at an MR whose pipeline has not
    been triggered, which is indistinguishable from one whose pipeline passed.
    """
    rec = Recorder()
    monkeypatch.setattr(drv.subprocess, "run", rec)
    drv.land(ready_row, base="dev", gate_set="repo", rejudge=False,
             timeout=1, act=True, log=lambda _: None)

    pushed_to = [a[2] for a in rec.pushes()]
    assert len(pushed_to) == 2, f"expected a push to both forges, got {len(pushed_to)}"
    assert "gitea.invalid" in pushed_to[0], (
        f"the first push went to {pushed_to[0]!r}; Gitea carries the CI and must "
        f"be pushed first, so the MR never precedes its own pipeline"
    )
    assert "gitlab.invalid" in pushed_to[1]
    assert wired and wired[0]["forge"] == "gitlab", (
        "the merge request must be opened on GitLab — Gitea has no review "
        "surface the operator can reach (T32.2 SSO lockout)"
    )


@pytest.mark.parametrize(("hooks", "must_say"), [
    (0, "did NOT see"),
    (None, "UNKNOWN"),
    (2, "webhook(s) fired"),
])
def test_the_ci_claim_is_a_measurement(drv, monkeypatch, ready_row, wired,
                                       hooks, must_say):
    """The first version of this line asserted that Woodpecker ran. It did not.

    Measured 2026-08-19, minutes after the driver's first successful end-to-end
    run: the Gitea repo carried ZERO webhooks — the agent-forge conversion
    recreates the repo and drops the A16 autowire hook — so the push triggered
    nothing, and an MR with no pipeline behind it is indistinguishable from one
    whose pipeline is still queued. A tool written to replace claims with
    measurements had shipped a claim in its own success line.

    None (could not ask) must NOT read as zero, and zero must not read as fine.
    """
    monkeypatch.setattr(drv.subprocess, "run", Recorder())
    monkeypatch.setattr(drv, "_ci_hook_count", lambda forge: hooks)
    lines: list[str] = []
    drv.land(ready_row, base="dev", gate_set="fast", rejudge=False,
             timeout=1, act=True, log=lines.append)
    joined = " ".join(lines)
    assert must_say in joined, f"expected {must_say!r} in output, got: {lines}"


def test_an_unaskable_hook_count_is_none_not_zero(drv, monkeypatch):
    monkeypatch.setattr(drv.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert drv._ci_hook_count(
        {"name": "gitea", "token": "t", "domain": "d.invalid",
         "owner": "o", "repo": "n"}) is None


def test_it_never_merges_and_never_pushes_a_base_branch(drv, monkeypatch,
                                                        ready_row, wired):
    rec = Recorder()
    monkeypatch.setattr(drv.subprocess, "run", rec)
    drv.land(ready_row, base="dev", gate_set="repo", rejudge=False,
             timeout=1, act=True, log=lambda _: None)

    for argv in rec.argvs():
        assert "merge" not in argv, f"the driver ran a merge: {argv}"
    for push in rec.pushes():
        refspec = push[-1]
        dest = refspec.split(":", 1)[-1]
        assert dest.startswith(("fix/", "refs/heads/fix/")), (
            f"the driver pushed {refspec!r}; it may only ever push its own "
            f"fix/* branch, never a base branch"
        )


def test_the_driver_mints_no_local_branch_ref(drv, monkeypatch, ready_row, wired):
    """The branch lives on the FORGES; this clone never needs the ref.

    Measured 2026-08-19, minutes after the refresh path shipped: run one's
    `git switch -c fix/loop-…` left a repo-wide local ref the worktree removal
    does not delete, and run two died on 'a branch named … already exists' —
    a second wedge of exactly the shape the refresh existed to fix. Detached
    commit + `HEAD:refs/heads/<branch>` refspec removes the collision class.
    """
    rec = Recorder()
    monkeypatch.setattr(drv.subprocess, "run", rec)
    drv.land(ready_row, base="dev", gate_set="repo", rejudge=False,
             timeout=1, act=True, log=lambda _: None)
    for call in rec.argvs():
        assert not (call[:2] == ["git", "switch"] and
                    any(a in ("-c", "-C", "-qc", "-qC") for a in call)), (
            f"the driver created a local branch ref: {call}; the second run "
            f"of the same proposal dies on the leftover"
        )
        assert call[:2] != ["git", "branch"], f"local branch ref minted: {call}"
    for push in rec.pushes():
        assert push[-1].startswith("HEAD:refs/heads/fix/"), (
            f"push refspec {push[-1]!r} relies on a local ref existing"
        )


def test_the_branch_name_carries_the_weakness_and_the_proposal(drv, monkeypatch,
                                                               ready_row, wired):
    """A branch nobody can trace back is a patch of unknown provenance."""
    rec = Recorder()
    monkeypatch.setattr(drv.subprocess, "run", rec)
    drv.land(ready_row, base="dev", gate_set="repo", rejudge=False,
             timeout=1, act=True, log=lambda _: None)
    branch = rec.pushes()[0][-1]
    assert "rem-204" in branch.lower() and ready_row["uuid"][:8] in branch


def test_a_forge_that_cannot_receive_the_branch_is_refused_before_any_git(
        drv, monkeypatch, ready_row):
    """Measured live 2026-08-19, minutes after the driver first ran.

    GitLab's `root/nOS` was `empty_repo: true` with zero branches and Gitea's
    token answered 401. Pushing into an empty project makes the pushed branch
    the project's DEFAULT — so the driver's first act would have installed
    `fix/loop-rem-204-…` as the protected trunk of the review forge.
    """
    monkeypatch.setattr(drv, "_forge", lambda name: {
        "name": name, "token": "FAKE_not_a_real_token", "domain": f"{name}.invalid",
        "owner": "o", "repo": "nOS"})
    monkeypatch.setattr(drv, "_base_exists",
                        lambda forge, base: (False, "branch 'dev' not found"))
    rec = Recorder()
    monkeypatch.setattr(drv.subprocess, "run", rec)
    lines: list[str] = []
    rc = drv.land(ready_row, base="dev", gate_set="repo", rejudge=False,
                  timeout=1, act=True, log=lines.append)
    assert rc == 2, "an unreceivable forge did not stop the landing"
    assert rec.calls == [], (
        f"git ran anyway: {rec.argvs()}. The check is worthless unless it "
        f"precedes the first mutation"
    )
    assert any("not found" in ln for ln in lines)


def test_an_unreachable_forge_is_not_read_as_an_empty_one(drv, monkeypatch):
    """Fail closed. A timeout is not permission to push."""
    monkeypatch.setattr(drv.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    ok, why = drv._base_exists(
        {"name": "gitea", "token": "t", "domain": "d.invalid",
         "owner": "o", "repo": "n"}, "dev")
    assert ok is False and "unreachable" in why


# ── 6. the ledger stays untouched ────────────────────────────────────────────

def test_the_driver_opens_the_ledger_read_only_and_writes_no_sql():
    src = DRIVER.read_text(encoding="utf-8")
    assert "mode=ro" in src, "the driver no longer opens the ledger read-only"
    lowered = src.lower()
    for verb in ("insert into", "update loop_", "delete from"):
        assert verb not in lowered, (
            f"the driver contains {verb!r}; a driver that writes to the ledger "
            f"is a step recording its own success (contract §3.5)"
        )


def test_a_real_read_only_connection_refuses_a_write(tmp_path):
    """The `mode=ro` claim above, exercised rather than asserted about."""
    db = tmp_path / "l.db"
    with sqlite3.connect(db) as seed:
        seed.execute("CREATE TABLE loop_proposals (uuid TEXT, diff_text TEXT)")
        seed.execute("INSERT INTO loop_proposals VALUES ('u', 'd')")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("UPDATE loop_proposals SET diff_text='x'")
    finally:
        conn.close()


def test_the_driver_holds_no_propose_scope():
    """It is the evaluator (§3.4). A driver that could propose grades itself."""
    src = DRIVER.read_text(encoding="utf-8")
    assert "PROPOSE_TOKEN" not in src and "loop_propose_token" not in src, (
        "the driver reaches for the proposer's credential; the identity split "
        "is the only thing keeping the author and the blesser apart"
    )


# ── 7 + 8. half-done work, and secrets ───────────────────────────────────────

def test_a_pushed_branch_with_no_merge_request_exits_non_zero(drv, monkeypatch,
                                                              ready_row):
    monkeypatch.setattr(drv, "_forge", lambda name: {
        "name": name, "token": "t", "domain": f"{name}.invalid",
        "owner": "o", "repo": "nOS"})
    monkeypatch.setattr(drv, "_base_exists", lambda forge, base: (True, ""))
    # The topology preflight has its own gate (test_the_driver_refuses_a_desynced_base);
    # here the four holders are stipulated to agree so the rest of the landing runs.
    monkeypatch.setattr(drv, "_base_alignment", lambda *a, **k: (True, ""))
    monkeypatch.setattr(drv, "_remote_tip", lambda forge, branch: (None, None))
    monkeypatch.setattr(drv, "_open_merge_request",
                        lambda *a, **k: (500, "forge exploded"))
    monkeypatch.setattr(drv.subprocess, "run", Recorder())
    lines: list[str] = []
    rc = drv.land(ready_row, base="dev", gate_set="repo", rejudge=False,
                  timeout=1, act=True, log=lines.append)
    assert rc == 1, "a pushed branch with no MR reported success"
    assert any("IS pushed" in ln for ln in lines), (
        "the operator is not told the branch survived the failure, so the "
        "re-run dead-ends on 'nothing to do'"
    )


def test_a_token_never_reaches_the_output(drv, monkeypatch, ready_row):
    """git echoes the push URL on failure, and that URL embeds the credential."""
    monkeypatch.setattr(drv, "_forge", lambda name: {
        "name": name, "token": "FAKE_not_a_real_token", "domain": f"{name}.invalid",
        "owner": "o", "repo": "nOS"})
    monkeypatch.setattr(drv, "_base_exists", lambda forge, base: (True, ""))
    # The topology preflight has its own gate (test_the_driver_refuses_a_desynced_base);
    # here the four holders are stipulated to agree so the rest of the landing runs.
    monkeypatch.setattr(drv, "_base_alignment", lambda *a, **k: (True, ""))
    monkeypatch.setattr(drv, "_remote_tip", lambda forge, branch: (None, None))
    rec = Recorder(rc=1, fail_on="push",
                   stderr="fatal: could not read from "
                          "https://oauth2:FAKE_not_a_real_token@gitea.invalid/o/nOS.git")
    monkeypatch.setattr(drv.subprocess, "run", rec)
    lines: list[str] = []
    rc = drv.land(ready_row, base="dev", gate_set="repo", rejudge=False,
                  timeout=1, act=True, log=lines.append)
    assert rc == 1
    assert not any("FAKE_not_a_real_token" in ln for ln in lines), (
        f"the push credential leaked into the operator-facing output: {lines}"
    )


def test_the_scrubber_survives_a_realistic_git_error(drv):
    dirty = "remote: denied\nfatal: https://oauth2:abc123@gitlab.x/o/n.git/info"
    assert "abc123" not in drv._scrub(dirty)


# ── 9. and the duplication stays honest ──────────────────────────────────────

def test_the_forge_keys_do_not_drift_from_the_bash_siblings():
    """The driver re-declares the forge coordinates instead of sharing them.

    That was a deliberate trade — refactoring two proven bash tools mid-flight
    is a worse risk than a duplicate — and it is only safe while something
    compares them. This is that something.
    """
    bash = RECIPE_PR.read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_loop_pr_keys", DRIVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for forge, keys in mod.FORGE_KEYS.items():
        for field in ("token_env", "token_key", "domain_env", "domain_key",
                      "owner_key", "name_key"):
            assert keys[field] in bash, (
                f"{forge}.{field} = {keys[field]!r} appears in the driver but "
                f"not in tools/recipe-pr.sh — the two now read different "
                f"configuration and one of them is pointed at nothing"
            )


def test_the_gitlab_api_goes_over_the_loopback_port():
    """The Cloudflare edge normalizes %2F in /projects/OWNER%2FNAME → 400.

    Measured 2026-06-10, rediscovered since. The push keeps the public domain
    because a git URL contains no %2F.
    """
    src = DRIVER.read_text(encoding="utf-8")
    assert "127.0.0.1" in src and "%2F" in src, (
        "the GitLab API call no longer goes over the loopback port; the "
        "project path will be mangled by the edge and every MR create 400s"
    )


def test_an_unrecognised_verdict_is_never_treated_as_a_pass(drv, monkeypatch):
    """DECISION 6a, restated at the one place a new result string would enter."""
    class Done:
        returncode, stdout, stderr = 0, json.dumps({"result": "probably-fine"}), ""

    monkeypatch.setattr(drv.shutil, "which", lambda _: "/usr/bin/nos-loop")
    monkeypatch.setattr(drv.subprocess, "run", lambda *a, **k: Done())
    result, _ = drv._rejudge("uuid", "repo", 1)
    assert result == "indeterminate", (
        f"a verdict of {result!r} came back from an unrecognised result string; "
        f"a new value upstream would read as a green light"
    )


def test_a_missing_nos_loop_is_indeterminate_not_a_pass(drv, monkeypatch):
    monkeypatch.setattr(drv.shutil, "which", lambda _: None)
    result, detail = drv._rejudge("uuid", "repo", 1)
    assert result == "indeterminate" and "PATH" in detail


# ── 10. re-runs refresh the driver's own branch, and only its own ─────────────
#
# MEASURED 2026-08-19, the wedge this section exists for: MR !1's commit
# f09f5860 predated the forge webhook, so no pipeline existed for it and none
# ever would — and a re-run of the driver produced the same branch name with a
# different commit, which a plain push refused non-fast-forward. The design is
# refresh-in-place: one proposal = one branch = one MR for its whole life, and
# the driver may overwrite ONLY a tip it can prove it made for this proposal.

def _wire_refresh(drv, monkeypatch, *, tip, owned):
    monkeypatch.setattr(drv, "_forge", lambda name: {
        "name": name, "token": "FAKE_not_a_real_token",
        "domain": f"{name}.invalid", "owner": "o", "repo": "nOS"})
    monkeypatch.setattr(drv, "_base_exists", lambda forge, base: (True, ""))
    # The topology preflight has its own gate (test_the_driver_refuses_a_desynced_base);
    # here the four holders are stipulated to agree so the rest of the landing runs.
    monkeypatch.setattr(drv, "_base_alignment", lambda *a, **k: (True, ""))
    monkeypatch.setattr(drv, "_remote_tip", lambda forge, branch: (tip, None))
    monkeypatch.setattr(drv, "_owns_remote_tip",
                        lambda tree, url, sha, uuid, diff:
                        (owned, "" if owned else "tip is not the driver's"))
    opened: list[tuple] = []
    monkeypatch.setattr(drv, "_open_merge_request",
                        lambda *a, **k: (opened.append(a), (409, ""))[1])
    return opened


def test_an_owned_stale_tip_is_refreshed_with_a_lease(drv, monkeypatch, ready_row):
    rec = Recorder()
    monkeypatch.setattr(drv.subprocess, "run", rec)
    _wire_refresh(drv, monkeypatch, tip="0ld7ea5e" * 5, owned=True)
    lines: list[str] = []
    rc = drv.land(ready_row, base="dev", gate_set="repo", rejudge=False,
                  timeout=1, act=True, log=lines.append)
    assert rc == 0
    pushes = rec.pushes()
    assert len(pushes) == 2, f"expected both forges pushed, got {pushes}"
    for push in pushes:
        lease = [a for a in push if a.startswith("--force-with-lease=")]
        assert lease, (
            f"a stale owned tip was pushed without a lease: {push}; a plain "
            f"push is refused non-fast-forward and the MR stays wedged forever"
        )
        assert ("0ld7ea5e" * 5) in lease[0], (
            "the lease is not pinned to the verified remote sha — an unpinned "
            "lease trusts whatever the local remote-tracking ref happens to say"
        )
        assert "--force" not in push or all(
            a.startswith("--force-with-lease=") for a in push if a.startswith("--force")
        ), f"a bare --force appeared: {push}"
    assert any("MR" in ln and "tracks" in ln for ln in lines), (
        "the operator is not told the existing MR now tracks the new commit"
    )


def test_a_tip_the_driver_cannot_prove_it_owns_is_never_forced(drv, monkeypatch,
                                                               ready_row):
    rec = Recorder()
    monkeypatch.setattr(drv.subprocess, "run", rec)
    _wire_refresh(drv, monkeypatch, tip="5omebody" * 5, owned=False)
    lines: list[str] = []
    rc = drv.land(ready_row, base="dev", gate_set="repo", rejudge=False,
                  timeout=1, act=True, log=lines.append)
    assert rc == 2, "an unowned tip did not stop the landing"
    assert rec.pushes() == [], (
        f"the driver pushed over a tip it could not prove it made: {rec.pushes()}"
    )
    assert any("Not forcing" in ln for ln in lines)


def test_an_unaskable_tip_refuses_rather_than_pushing_blind(drv, monkeypatch,
                                                            ready_row):
    rec = Recorder()
    monkeypatch.setattr(drv.subprocess, "run", rec)
    monkeypatch.setattr(drv, "_forge", lambda name: {
        "name": name, "token": "t", "domain": f"{name}.invalid",
        "owner": "o", "repo": "nOS"})
    monkeypatch.setattr(drv, "_base_exists", lambda forge, base: (True, ""))
    # The topology preflight has its own gate (test_the_driver_refuses_a_desynced_base);
    # here the four holders are stipulated to agree so the rest of the landing runs.
    monkeypatch.setattr(drv, "_base_alignment", lambda *a, **k: (True, ""))
    monkeypatch.setattr(drv, "_remote_tip",
                        lambda forge, branch: (None, f"{forge['name']} unreachable"))
    rc = drv.land(ready_row, base="dev", gate_set="repo", rejudge=False,
                  timeout=1, act=True, log=lambda _: None)
    assert rc == 2 and rec.pushes() == [], (
        "an unanswerable 'does the branch exist' was read as 'it does not'"
    )


def test_the_tip_lookup_spells_the_branch_slash_per_forge(drv, monkeypatch):
    """Both readings were PAID FOR, one live run apart (2026-08-19): GitLab
    404s on the raw slash — and 404 means "absent" here, so an existing branch
    read as missing and the plain push was refused non-fast-forward; encoding
    both then had Gitea answer 400 to `%2F`. GitLab gets `%2F`, Gitea the raw
    slash; a tidy uniform rule is wrong in one direction or the other."""
    seen: dict[str, str] = {}

    def fake_urlopen(request, timeout=0):
        raise drv.urllib.error.HTTPError(request.full_url, 404, "nf", {}, None)

    monkeypatch.setattr(drv.urllib.request, "urlopen", fake_urlopen)

    real_request = drv.urllib.request.Request

    def spy_request(url, *a, **k):
        seen[("gitlab" if "127.0.0.1" in url else "gitea")] = url
        return real_request(url, *a, **k)

    monkeypatch.setattr(drv.urllib.request, "Request", spy_request)
    for forge in ({"name": "gitlab", "token": "t", "domain": "d.invalid",
                   "owner": "root", "repo": "nOS"},
                  {"name": "gitea", "token": "t", "domain": "d.invalid",
                   "owner": "o", "repo": "nOS"}):
        drv._remote_tip(forge, "fix/loop-rem-rem-204-6f139e22")
    assert "fix%2Floop-" in seen["gitlab"], (
        f"GitLab got a raw slash and will 404 an existing branch: {seen['gitlab']}"
    )
    assert "/branches/fix/loop-" in seen["gitea"], (
        f"Gitea got an encoded slash and will 400: {seen['gitea']}"
    )


def test_ownership_needs_both_the_uuid_and_the_judged_diff(drv, monkeypatch,
                                                           tmp_path):
    """One line of prose must not be enough to overwrite a commit.

    A human who cherry-picked the driver's commit message onto real work would
    match the uuid test; only the diff comparison protects their change.
    """
    answers = {"%B": "body naming 6f139e22-6793-4a88-bfa2-fc136a91506a",
               "": "--- a/x\n+++ b/x\n@@\n-old\n+DIFFERENT\n"}

    def fake_run(argv, **kw):
        class Done:
            returncode = 0
            stderr = ""
            stdout = ""
        argv = list(argv)
        if argv[:2] == ["git", "show"]:
            fmt = next((a.split("=", 1)[1] for a in argv if a.startswith("--format=")), None)
            Done.stdout = answers.get(fmt, "")
        return Done()

    monkeypatch.setattr(drv.subprocess, "run", fake_run)
    judged = "--- a/x\n+++ b/x\n@@\n-old\n+new\n"
    owned, why = drv._owns_remote_tip(
        tmp_path, "https://x.invalid/r.git", "a" * 40,
        "6f139e22-6793-4a88-bfa2-fc136a91506a", judged)
    assert owned is False and "different change" in why

    answers[""] = judged
    owned, _ = drv._owns_remote_tip(
        tmp_path, "https://x.invalid/r.git", "a" * 40,
        "6f139e22-6793-4a88-bfa2-fc136a91506a", judged)
    assert owned is True

    answers["%B"] = "an unrelated body"
    owned, why = drv._owns_remote_tip(
        tmp_path, "https://x.invalid/r.git", "a" * 40,
        "6f139e22-6793-4a88-bfa2-fc136a91506a", judged)
    assert owned is False and "does not name proposal" in why


# ── 10. the step that was missing ────────────────────────────────────────────

def test_an_unjudged_proposal_is_judged_not_skipped(drv, monkeypatch, ready_row, wired):
    """MEASURED 2026-08-21, the first unattended night.

    `loop:propose` filed a proposal at 01:38. `loop:drive` at 06:12 reported
    "no passed proposal is waiting to land" — true, and the reason nothing
    happened: a fresh proposal has no verdict, and this driver only ever acted
    on passed ones. There was no step between the one that makes a proposal and
    the one that lands it. It never showed while attended because a human
    judged each proposal within a minute of filing it, bridging the gap by hand.

    Judging belongs to the driver and to nothing else: §3.4 gives it the
    evaluator identity so the proposer can propose and stop.
    """
    ready_row["state"] = "unjudged"
    calls = []
    monkeypatch.setattr(drv, "_rejudge",
                        lambda uuid, gs, to: (calls.append((uuid, gs)), ("pass", ""))[1])
    monkeypatch.setattr(drv.subprocess, "run", Recorder())
    rc = drv.land(ready_row, base="dev", gate_set="fast", rejudge=False,
                  timeout=1, act=True, log=lambda _: None)
    assert calls, (
        "an unjudged proposal was not handed to a judge; it is then invisible "
        "to everything downstream for ever"
    )
    assert calls[0][1] == "fast", "the judge was not given the proposal's gate set"
    assert rc == 0


def test_an_unjudged_proposal_that_fails_lands_nothing(drv, monkeypatch,
                                                       ready_row, wired):
    """A first verdict of fail is a refusal, not a reason to push anyway."""
    ready_row["state"] = "unjudged"
    monkeypatch.setattr(drv, "_rejudge", lambda *a: ("fail", "18 failing test(s)"))
    rec = Recorder()
    monkeypatch.setattr(drv.subprocess, "run", rec)
    drv.land(ready_row, base="dev", gate_set="fast", rejudge=False,
             timeout=1, act=True, log=lambda _: None)
    assert rec.pushes() == [], "a failed first judgement still pushed a branch"
    assert wired == [], "a failed first judgement still opened a merge request"


def test_judging_an_unjudged_proposal_does_not_need_the_rejudge_flag(drv, monkeypatch,
                                                                     ready_row, wired):
    """`--rejudge` guards REFRESHING a decayed verdict — spending judge time on
    a question already answered. A proposal nobody has ruled on is not that: if
    the driver skipped it without the flag, the unattended cadence would file
    proposals for ever and rule on none."""
    ready_row["state"] = "unjudged"
    calls = []
    monkeypatch.setattr(drv, "_rejudge",
                        lambda uuid, gs, to: (calls.append(uuid), ("pass", ""))[1])
    monkeypatch.setattr(drv.subprocess, "run", Recorder())
    drv.land(ready_row, base="dev", gate_set="fast", rejudge=False,   # <- no flag
             timeout=1, act=True, log=lambda _: None)
    assert calls, "an unjudged proposal was skipped for want of --rejudge"

