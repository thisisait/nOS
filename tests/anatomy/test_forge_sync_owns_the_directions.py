"""One tool moves trunk refs between the four holders, and it moves them one way.

WHAT THIS PINS. `tools/forge-sync.py` replaced a promotion that was hand-typed
from memory with a token on the command line (2026-08-19). Its contract, each
part paid for that day:

  1. **Fast-forward only, toward a unique leader.** The leader is the tip that
     contains every other readable tip; divergence and unreadability both
     refuse. No merge, no rebase, no force exists in the file.
  2. **A token never reaches argv, a URL, or output.** The sibling sync
     scripts embed `oauth2:<token>@` in the push URL; this tool must not —
     credentials ride a GIT_ASKPASS helper's environment.
  3. **Dry run is the default; `--apply` accepts only `dev`;** the GitHub push
     needs `--push-github` on top, because the public trunk is an operator act.
  4. **The reviewer promotes through this tool** — promotion is a step of the
     merge, not a thing a human remembers — and never passes `--push-github`.

CI-safe: leader election runs against throwaway git repos in tmp; everything
else is pure-function or source-shape. Nothing reaches a forge or a network.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SYNC = REPO / "tools" / "forge-sync.py"
REVIEWER = REPO / "tools" / "loop-review.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def sync():
    return _load(SYNC, "_forge_sync_gate")


@pytest.fixture()
def history(tmp_path):
    """A real repo with three commits A → B → C, plus a divergent D off A.

    Leader election is ancestry arithmetic and the only honest oracle for
    ancestry is git itself — a mocked merge-base is the gate grading its own
    homework.
    """
    repo = tmp_path / "r"
    repo.mkdir()

    def git(*argv):
        done = subprocess.run(["git", *argv], cwd=repo, text=True,
                              capture_output=True, check=True)
        return done.stdout.strip()

    git("init", "-q", "-b", "dev")
    git("config", "user.email", "gate@test")
    git("config", "user.name", "gate")
    shas = {}
    for label in ("A", "B", "C"):
        (repo / "f").write_text(label)
        git("add", "f")
        git("commit", "-q", "-m", label)
        shas[label] = git("rev-parse", "HEAD")
    git("checkout", "-q", shas["A"])
    (repo / "g").write_text("D")
    git("add", "g")
    git("commit", "-q", "-m", "D")
    shas["D"] = git("rev-parse", "HEAD")
    git("checkout", "-q", "dev")
    return repo, shas


def _tips(shas, **assign):
    return {name: {"sha": shas[label], "error": None}
            for name, label in assign.items()}


def test_leader_is_the_tip_that_contains_every_other(sync, history):
    repo, shas = history
    sync.REPO = repo  # `_git` reads the module global at call time
    leader, why = sync.elect_leader(
        _tips(shas, local="B", github="B", gitea="B", gitlab="C"))
    assert leader == "gitlab", why  # the un-promoted agent merge — Model A


def test_identical_tips_need_no_leader_argument(sync, history):
    repo, shas = history
    sync.REPO = repo
    leader, _ = sync.elect_leader(
        _tips(shas, local="C", github="C", gitea="C", gitlab="C"))
    assert leader is not None
    assert sync.build_plan(
        _tips(shas, local="C", github="C", gitea="C", gitlab="C"), leader) == []


def test_divergence_elects_nobody(sync, history):
    repo, shas = history
    sync.REPO = repo
    leader, why = sync.elect_leader(
        _tips(shas, local="C", github="C", gitea="C", gitlab="D"))
    assert leader is None
    assert "DIVERGED" in why


def test_an_unreadable_holder_elects_nobody(sync, history):
    """A leader elected over a partial view converges the estate toward a
    guess. Unreadable is UNKNOWN, and UNKNOWN plans nothing."""
    repo, shas = history
    sync.REPO = repo
    tips = _tips(shas, local="C", github="C", gitea="C")
    tips["gitlab"] = {"sha": None, "error": "gitlab unreachable"}
    leader, why = sync.elect_leader(tips)
    assert leader is None
    assert "unreadable" in why


def test_the_plan_moves_only_the_followers(sync, history):
    repo, shas = history
    sync.REPO = repo
    tips = _tips(shas, local="B", github="A", gitea="B", gitlab="C")
    plan = sync.build_plan(tips, "gitlab")
    assert {s["holder"] for s in plan} == {"local", "github", "gitea"}
    assert all(s["to_sha"] == shas["C"] for s in plan)


def test_apply_refuses_any_branch_but_dev(sync, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["forge-sync.py", "--apply", "--branch", "master"])
    assert sync.main() == 2
    assert "operator" in capsys.readouterr().err


def test_no_token_ever_reaches_a_url_or_argv():
    """The credential rides GIT_ASKPASS's environment; the URL carries only a
    username. `oauth2:` followed by an interpolation is the exact shape the
    hand-typed promotion leaked."""
    src = SYNC.read_text(encoding="utf-8")
    assert "GIT_ASKPASS" in src, "the askpass bridge is gone — where does the token go?"
    # The module docstring may QUOTE the leaked shape it retired; the code may
    # not CONTAIN it. Scan everything after the docstring closes.
    src = src.split('"""', 2)[2]
    for line in src.splitlines():
        code = line.split("#", 1)[0]
        assert "oauth2:" not in code, (
            f"token-in-URL shape found: {line.strip()!r} — credentials must "
            f"never be part of a URL or argv here")


def test_the_github_push_is_gated_behind_its_own_flag():
    src = SYNC.read_text(encoding="utf-8")
    assert "--push-github" in src
    assert "if not push_github:" in src, (
        "the GitHub branch of _apply_step must refuse without the explicit flag")


def test_the_reviewer_promotes_and_never_pushes_github():
    """Promotion is a step of the merge (the 2026-08-19 hand-typed sequence,
    retired), and the reviewer's argv to forge-sync is pinned as data."""
    reviewer = _load(REVIEWER, "_loop_review_promote_gate")
    assert reviewer.PROMOTE_ARGV == ["--apply"], (
        "the reviewer may converge the local holders after a merge, and "
        "nothing more — the public trunk is the operator's")
    src = REVIEWER.read_text(encoding="utf-8")
    assert "forge-sync.py" in src
