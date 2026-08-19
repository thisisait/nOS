"""The one component allowed to merge, and every reason it must not.

`tools/loop-review.py` closes the loop: it reads an open merge request the
driver opened, asks three questions, and merges only on three yeses. It is the
first thing in this estate that changes a shared branch with no human in the
call, so this file is written as a list of refusals rather than a list of
features.

THE THREE QUESTIONS

  1. Did CI pass on THIS commit?      (Woodpecker, keyed on the head sha)
  2. Did the judges pass it?          (the ledger, read-only)
  3. Is the MR's diff the judged one? (byte comparison of the +/- lines)

WHY "NO PIPELINE" IS THE CENTRAL CASE. Measured 2026-08-19, the day the reviewer
was written: the Gitea repo carried ZERO webhooks, so no push had started a
pipeline for an unknown period, while Woodpecker's own row said the repo was
active and a converge reported success. An MR with no pipeline looks exactly
like one whose pipeline is queued, and both look nothing like a failure. If
absence resolves to "nothing failed", this tool merges untested code at 3am —
which is the hour it exists to work in.

So absence is INDETERMINATE, INDETERMINATE refuses, and it is reported as its
own outcome (`docs/idea/11-agentic-loop-contract.md` §2.4 forbids mapping it
onto either neighbour).

AND WHY QUESTION 3 EXISTS. One and two are about a proposal; the merge is about
a branch. Without comparing them, a green CI and a passed verdict can both be
true of a change other than the one that would land.

CI-safe: every HTTP call and every ledger read is a fake. Nothing here reaches a
forge, Woodpecker, a network or the real ledger.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
REVIEWER = REPO / "tools" / "loop-review.py"


@pytest.fixture(scope="module")
def rev():
    spec = importlib.util.spec_from_file_location("_loop_review_gate", REVIEWER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


JUDGED = "--- a/c.yml\n+++ b/c.yml\n@@ -1,3 +1,3 @@\n alpha\n-v: 1\n+v: 2\n omega\n"
#: Same edit, different hunk offsets and file headers — what a forge renders.
SAME_EDIT = "diff --git a/c.yml b/c.yml\n--- a/c.yml\n+++ b/c.yml\n@@ -40,3 +40,3 @@\n alpha\n-v: 1\n+v: 2\n omega\n"
OTHER_EDIT = JUDGED.replace("+v: 2", "+v: 999")


@pytest.fixture
def mr():
    return {"iid": 1, "source_branch": "fix/loop-rem-rem-204-6f139e22",
            "sha": "f09f5860aaaabbbbccccddddeeeeffff00001111",
            "target_branch": "dev"}


@pytest.fixture
def wired(rev, monkeypatch):
    """A reviewer whose forge answers, with recorded calls."""
    calls: list[dict] = []

    def api(url, headers, *, method="GET", payload=None):
        calls.append({"url": url, "method": method, "payload": payload})
        if "raw_diffs" in url:
            return 200, SAME_EDIT
        if url.endswith("/merge"):
            return 200, {"state": "merged"}
        return 200, []

    monkeypatch.setattr(rev, "_api", api)
    monkeypatch.setattr(rev, "_gitlab", lambda driver: (
        {"name": "gitlab", "token": "FAKE_not_a_real_token", "owner": "o",
         "repo": "nOS", "domain": "gitlab.invalid"},
        "http://127.0.0.1:8929/api/v4/projects/o%2FnOS"))
    return calls


def _merges(calls) -> list[dict]:
    return [c for c in calls if c["url"].endswith("/merge")]


def test_the_reviewer_exists(rev):
    """Positive control."""
    assert REVIEWER.is_file() and hasattr(rev, "review")


# ── the central case: an unanswered question is not a yes ────────────────────

@pytest.mark.parametrize("ci_state", ["indeterminate", "fail"])
def test_it_never_merges_without_a_green_pipeline(rev, monkeypatch, mr, wired,
                                                  ci_state):
    monkeypatch.setattr(rev, "ci_verdict", lambda sha, d: (ci_state, "because"))
    monkeypatch.setattr(rev, "ledger_verdict", lambda u, diff: ("pass", "ok"))
    outcome = rev.review(mr, None, act=True, log=lambda _: None)
    assert outcome != rev.MERGED, f"merged with CI={ci_state}"
    assert _merges(wired) == [], "a merge call was made anyway"


def test_a_missing_pipeline_is_indeterminate_not_a_pass(rev, monkeypatch):
    """The state the estate was actually in: zero webhooks, so zero pipelines."""
    monkeypatch.setattr(rev, "_api", lambda url, h, **k: (
        (200, {"id": 7}) if "lookup" in url else (200, [])))
    monkeypatch.setattr(rev, "_load", lambda *a: None)
    driver = type("D", (), {
        "_yaml_lookup": staticmethod(lambda k, *f: {"woodpecker_api_token": "t"}.get(k, "")),
        "FORGE_KEYS": {"gitea": {"owner_key": "o", "name_key": "n",
                                 "owner_default": "pazny", "name_default": "nOS",
                                 "role_defaults": "roles/pazny.gitea/defaults/main.yml"}},
    })()
    state, why = rev.ci_verdict("f09f5860", driver)
    assert state == rev.INDETERMINATE, f"no pipeline reported as {state!r}"
    assert "never ran" in why


def test_html_from_the_spa_is_not_a_pipeline_answer(rev, monkeypatch):
    """A 200 whose body is the front-end certified a whole role once already."""
    monkeypatch.setattr(rev, "_api", lambda url, h, **k: (200, "<!doctype html>"))
    driver = type("D", (), {
        "_yaml_lookup": staticmethod(lambda k, *f: {"woodpecker_api_token": "t"}.get(k, "")),
        "FORGE_KEYS": {"gitea": {"owner_key": "o", "name_key": "n",
                                 "owner_default": "pazny", "name_default": "nOS",
                                 "role_defaults": "roles/pazny.gitea/defaults/main.yml"}},
    })()
    state, why = rev.ci_verdict("f09f5860", driver)
    assert state == rev.INDETERMINATE and "SPA" in why


def test_a_running_pipeline_is_indeterminate(rev, monkeypatch):
    monkeypatch.setattr(rev, "_api", lambda url, h, **k: (
        (200, {"id": 7}) if "lookup" in url
        else (200, [{"number": 3, "commit": "f09f5860x", "status": "running"}])))
    driver = type("D", (), {
        "_yaml_lookup": staticmethod(lambda k, *f: {"woodpecker_api_token": "t"}.get(k, "")),
        "FORGE_KEYS": {"gitea": {"owner_key": "o", "name_key": "n",
                                 "owner_default": "pazny", "name_default": "nOS",
                                 "role_defaults": "roles/pazny.gitea/defaults/main.yml"}},
    })()
    assert rev.ci_verdict("f09f5860", driver)[0] == rev.INDETERMINATE


# ── question 2 + 3 ───────────────────────────────────────────────────────────

def test_it_never_merges_without_a_passed_verdict(rev, monkeypatch, mr, wired):
    monkeypatch.setattr(rev, "ci_verdict", lambda sha, d: ("pass", "green"))
    monkeypatch.setattr(rev, "ledger_verdict", lambda u, diff: ("fail", "no"))
    assert rev.review(mr, None, act=True, log=lambda _: None) != rev.MERGED
    assert _merges(wired) == []


@pytest.fixture
def fixture_ledger(rev, tmp_path, monkeypatch):
    """A real SQLite ledger holding one passed proposal with a known patch."""
    import sqlite3 as _sq

    db = tmp_path / "wing.db"
    with _sq.connect(db) as seed:
        seed.execute("CREATE TABLE loop_proposals (id INTEGER PRIMARY KEY, "
                     "uuid TEXT, diff_text TEXT)")
        seed.execute("CREATE TABLE loop_verdicts (id INTEGER PRIMARY KEY, "
                     "proposal_id INTEGER, result TEXT)")
        seed.execute("INSERT INTO loop_proposals VALUES (1, '6f139e22-aaaa', ?)",
                     (JUDGED,))
        seed.execute("INSERT INTO loop_verdicts VALUES (1, 1, 'pass')")
    monkeypatch.setattr(rev, "LEDGER", db)
    return db


def test_a_diff_that_is_not_the_judged_one_is_refused(rev, fixture_ledger):
    """Green CI and a passed verdict, about a DIFFERENT change.

    Driven through `ledger_verdict` rather than through `_same_change` alone.
    The first draft of this file tested the comparison in isolation, and the
    retro-verification proved the consequence: deleting the comparison from the
    function that calls it left the whole suite green. A helper covered by tests
    is not the same as a decision covered by tests.
    """
    state, why = rev.ledger_verdict("6f139e22", OTHER_EDIT)
    assert state == "fail", f"a substituted diff was accepted ({state}: {why})"
    assert "judged patch" in why


def test_the_judged_diff_passes_through_the_same_path(rev, fixture_ledger):
    """Positive control for the test above — otherwise 'always fail' passes it."""
    state, _ = rev.ledger_verdict("6f139e22", SAME_EDIT)
    assert state == "pass"


def test_an_unjudged_proposal_is_indeterminate(rev, fixture_ledger):
    state, why = rev.ledger_verdict("nosuchuuid", SAME_EDIT)
    assert state == rev.INDETERMINATE and "no judged proposal" in why


def test_a_missing_ledger_is_indeterminate_not_a_pass(rev, monkeypatch, tmp_path):
    monkeypatch.setattr(rev, "LEDGER", tmp_path / "absent.db")
    assert rev.ledger_verdict("6f139e22", SAME_EDIT)[0] == rev.INDETERMINATE


def test_the_same_edit_at_a_different_offset_still_matches(rev):
    """Otherwise every honest MR is refused and the check gets switched off.

    Hunk headers carry offsets that shift with any unrelated edit above them,
    and a forge renders file headers differently from `git diff`.
    """
    assert rev._same_change(JUDGED, SAME_EDIT) is True


def test_an_empty_judged_patch_never_matches(rev):
    """A ledger row with no patch must not compare equal to an empty MR."""
    assert rev._same_change("", "") is False


# ── what it will not touch ───────────────────────────────────────────────────

def test_it_leaves_branches_it_did_not_create_alone(rev, mr, wired):
    """An unattended merge button on the operator's own work is the nightmare."""
    mr["source_branch"] = "feat/operator-is-mid-thought"
    assert rev.review(mr, None, act=True, log=lambda _: None) != rev.MERGED
    assert _merges(wired) == []


@pytest.mark.parametrize("base", ["master", "main"])
def test_it_refuses_to_target_master(rev, base):
    driver = importlib.util.module_from_spec(
        importlib.util.spec_from_file_location("_d", REPO / "tools" / "loop-pr.py"))
    importlib.util.spec_from_file_location("_d", REPO / "tools" / "loop-pr.py").loader.exec_module(driver)
    with pytest.raises(driver.Refused):
        driver._refuse_master(base)


def test_the_reviewer_writes_nothing_to_the_ledger():
    src = REVIEWER.read_text(encoding="utf-8")
    assert "mode=ro" in src, "the ledger is no longer opened read-only"
    lowered = src.lower()
    for verb in ("insert into", "update loop_", "delete from"):
        assert verb not in lowered, f"the reviewer contains {verb!r}"


def test_the_reviewer_holds_no_propose_scope():
    src = REVIEWER.read_text(encoding="utf-8")
    assert "PROPOSE_TOKEN" not in src and "loop_propose_token" not in src


# ── and the happy path, so the refusals mean something ───────────────────────

def test_three_yeses_merge(rev, monkeypatch, mr, wired):
    """The positive control for every refusal above.

    Without this, deleting the merge call entirely would make this file pass.
    """
    monkeypatch.setattr(rev, "ci_verdict", lambda sha, d: ("pass", "green"))
    monkeypatch.setattr(rev, "ledger_verdict", lambda u, diff: ("pass", "judged"))
    outcome = rev.review(mr, None, act=True, log=lambda _: None)
    assert outcome == rev.MERGED
    merges = _merges(wired)
    assert len(merges) == 1 and merges[0]["method"] == "PUT"


def test_a_dry_run_answers_without_merging(rev, monkeypatch, mr, wired):
    monkeypatch.setattr(rev, "ci_verdict", lambda sha, d: ("pass", "green"))
    monkeypatch.setattr(rev, "ledger_verdict", lambda u, diff: ("pass", "judged"))
    rev.review(mr, None, act=False, log=lambda _: None)
    assert _merges(wired) == [], "a dry run merged"
