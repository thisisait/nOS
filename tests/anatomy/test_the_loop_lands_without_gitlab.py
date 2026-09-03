"""The loop lands while GitLab is declared off.

MEASURED 2026-09-03: install_gitlab flipped false on 09-01 (operator, memory
pressure) and the loop's landing half died — loop:drive judged REM-239 and
REM-244 and pushed toward a forge that no longer exists; loop:review first
went red on "Connection refused" two mornings running, then (after the
ruling-gate) SKIPped — a hole where a consequence should be. Nothing could
land, and no surface said the chain was severed.

The decision now has a consequence: Gitea — which carries the CI anyway —
becomes the review surface. Drive pushes there alone and opens a Gitea PR;
review lists, answers the same three questions, and merges with `Do: rebase`
(linear dev); forge-sync excuses the declared-off holder from election
instead of refusing the whole sync on it.

Retro-verified against the pre-fix files: `elect_leader` refused with
"unreadable holder(s): gitlab", `open_requests` had no gitea dialect, and
`land()` hardcoded `(gitea, gitlab)`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_a_declared_off_holder_is_excused_from_election():
    fs = _load("_fs_gate", "forge-sync.py")
    tips = {
        "local": {"sha": "a" * 40, "error": None},
        "github": {"sha": "a" * 40, "error": None},
        "gitea": {"sha": "a" * 40, "error": None},
        "gitlab": {"sha": None, "error": None, "declared_off": True},
    }
    leader, why = fs.elect_leader(tips)
    assert leader is not None, (
        f"a declared-off forge still blocks the election ({why}) — the trunk "
        "freezes on a holder the operator deliberately removed")
    assert fs.build_plan(tips, leader) == [], (
        "build_plan tries to sync a declared-off holder")


def test_an_unreadable_holder_still_refuses():
    """Excused ≠ ignored: unreachable-while-declared-on stays a refusal."""
    fs = _load("_fs_gate2", "forge-sync.py")
    tips = {
        "local": {"sha": "a" * 40, "error": None},
        "github": {"sha": "a" * 40, "error": None},
        "gitea": {"sha": "a" * 40, "error": None},
        "gitlab": {"sha": None, "error": "gitlab unreachable (URLError)"},
    }
    leader, why = fs.elect_leader(tips)
    assert leader is None and "unreadable" in why


def test_review_normalizes_gitea_pulls_to_the_mr_shape(monkeypatch):
    lr = _load("_lr_gate", "loop-review.py")
    monkeypatch.setattr(lr, "_gitea", lambda driver: (
        {"token": "t", "domain": "git.x", "owner": "o", "repo": "r"},
        "https://git.x/api/v1/repos/o/r"))
    monkeypatch.setattr(lr, "_api", lambda url, headers, **kw: (200, [
        {"number": 7,
         "head": {"ref": "fix/loop-rem-154-deadbeef", "sha": "c" * 40},
         "base": {"ref": "dev"}},
        {"number": 8,
         "head": {"ref": "fix/loop-x-cafebabe", "sha": "d" * 40},
         "base": {"ref": "master"}},   # wrong base — filtered out
    ]))
    rows = lr.open_requests(object(), "dev", gitea_mode=True)
    assert rows == [{
        "iid": 7, "source_branch": "fix/loop-rem-154-deadbeef",
        "sha": "c" * 40, "target_branch": "dev", "_gitea": True,
    }]


def test_review_merges_a_gitea_pr_with_rebase(monkeypatch):
    """dev carries required_linear_history; a merge commit from the reviewer
    would be the one non-ff write in the whole loop. `Do: rebase` is pinned."""
    lr = _load("_lr_gate2", "loop-review.py")
    calls = []
    monkeypatch.setattr(lr, "_gitea", lambda driver: (
        {"token": "t", "domain": "git.x", "owner": "o", "repo": "r"},
        "https://git.x/api/v1/repos/o/r"))

    def fake_api(url, headers, *, method="GET", payload=None):
        calls.append((url, method, payload))
        if url.endswith(".diff"):
            return 200, "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
        if url.endswith("/merge"):
            return 200, ""
        raise AssertionError(url)

    monkeypatch.setattr(lr, "_api", fake_api)
    monkeypatch.setattr(lr, "ci_verdict", lambda sha, driver: ("pass", "ok"))
    monkeypatch.setattr(lr, "ledger_verdict", lambda uuid, diff: ("pass", "ok"))
    verdict = lr.review(
        {"iid": 7, "source_branch": "fix/loop-rem-154-deadbeef",
         "sha": "c" * 40, "target_branch": "dev", "_gitea": True},
        object(), act=True, log=lambda line: None)
    assert verdict == lr.MERGED
    merge_calls = [c for c in calls if c[0].endswith("/merge")]
    assert merge_calls and merge_calls[0][1] == "POST"
    assert merge_calls[0][2]["Do"] == "rebase"


def test_the_driver_asks_the_flag_before_choosing_forges():
    """Shape gate on land(): the receiving-forge set is flag-conditional, and
    the PR opener has a Gitea dialect."""
    src = (REPO / "tools" / "loop-pr.py").read_text(encoding="utf-8")
    assert "_gitlab_declared_on" in src.split("def land")[1], (
        "land() no longer consults install_gitlab — a declared-off forge "
        "silently rejoins the push set")
    assert "def _open_gitea_pr" in src, (
        "the Gitea PR opener is gone; with GitLab off the loop cannot land")
