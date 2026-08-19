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
        assert refspec.startswith("fix/"), (
            f"the driver pushed {refspec!r}; it may only ever push its own "
            f"fix/* branch, never a base branch"
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
