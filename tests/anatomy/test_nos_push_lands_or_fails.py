"""tools/nos-push either lands the ref or exits non-zero — never a silent 0.

2026-10-20: `tools/nos-push origin HEAD:dev` from a detached worktree printed
only the mirror lines and exited 0; origin/dev did not move. The wrapper ran
`git -C <its own repo> push`, so a copy invoked from another checkout pushed
THAT checkout's HEAD ("up to date"). End-to-end against a bare remote in tmp;
the mirror sync is a stub tool that drops a marker file.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    _git(repo, "add", name)
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
         "commit", "-qm", name)
    return _git(repo, "rev-parse", "HEAD")


def _estate(tmp: Path) -> tuple[Path, Path, Path]:
    """(bare remote, tools checkout holding nos-push + a stub forge sync, work clone)."""
    bare = tmp / "remote.git"
    _git(tmp, "init", "-q", "--bare", str(bare))
    tools = tmp / "tools-repo"
    _git(tmp, "clone", "-q", str(bare), str(tools))
    _commit(tools, "seed")
    _git(tools, "push", "-q", "origin", "HEAD:refs/heads/dev")
    (tools / "tools").mkdir()
    shutil.copy(REPO / "tools/nos-push", tools / "tools/nos-push")
    sync = tools / "tools/sync-trunk-to-gitea.sh"
    sync.write_text(f"#!/bin/sh\ntouch '{tmp}/synced'\n")
    sync.chmod(0o755)
    (tools / "config.yml").write_text(
        "gitea_agent_forge: true\ngitea_api_token: t\ngitea_domain: git.example\n")
    work = tmp / "work"
    _git(tmp, "clone", "-q", "-b", "dev", str(bare), str(work))
    return bare, tools, work


def _push(tools: Path, work: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT")}
    env["HOME"] = str(work.parent)  # no ~/.nos/secrets.yml, no real forge
    return subprocess.run(["bash", str(tools / "tools/nos-push"), *args], cwd=work,
                          env=env, capture_output=True, text=True, timeout=60)


def _remote_dev(bare: Path) -> str:
    return _git(bare, "rev-parse", "refs/heads/dev")


def test_detached_head_refspec_lands_from_another_checkout(tmp_path):
    bare, tools, work = _estate(tmp_path)
    _git(work, "checkout", "-q", "--detach")
    sha = _commit(work, "change")
    got = _push(tools, work, str(bare), "HEAD:dev")
    remote = _remote_dev(bare)
    assert got.returncode != 0 or remote == sha, (
        f"nos-push exited 0 but dev={remote[:9]}, meant {sha[:9]}:\n{got.stdout}{got.stderr}")
    assert remote == sha, f"HEAD:dev did not land:\n{got.stdout}{got.stderr}"
    assert (tmp_path / "synced").exists(), "a verified push must run the mirror sync"


def test_a_push_that_does_not_land_fails_and_skips_the_sync(tmp_path):
    bare, tools, work = _estate(tmp_path)
    _commit(tools, "ahead")  # remote dev moves past work
    _git(tools, "push", "-q", "origin", "HEAD:dev")
    _git(work, "checkout", "-q", "--detach")
    _commit(work, "diverged")
    got = _push(tools, work, str(bare), "HEAD:dev")  # non-fast-forward
    assert got.returncode != 0, f"a rejected push exited 0:\n{got.stdout}"
    assert not (tmp_path / "synced").exists(), "mirror sync ran after a push that did not land"


def test_detached_head_without_refspec_is_refused_by_name(tmp_path):
    bare, tools, work = _estate(tmp_path)
    _git(work, "checkout", "-q", "--detach")
    _commit(work, "change")
    got = _push(tools, work, str(bare))
    assert got.returncode != 0
    assert "detached" in (got.stdout + got.stderr).lower()


def test_a_checkout_of_another_repo_is_refused(tmp_path):
    """2026-10-22: run from a worktree of the PRIVATE seed repo (nested under an nOS worktree),
    nos-push pushed to the nOS origin: a stray branch on the public repo, and the next time it
    could have been the seed's history. nos-push pushes checkouts of ITS repo only: the push
    target must be the origin the script's own checkout pushes to."""
    bare, tools, work = _estate(tmp_path)
    other_bare = tmp_path / "other.git"
    _git(tmp_path, "init", "-q", "--bare", str(other_bare))
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(other_bare), str(other))
    _commit(other, "private")
    _git(other, "push", "-q", "origin", "HEAD:refs/heads/main")
    before = _git(bare, "rev-parse", "refs/heads/dev")
    got = _push(tools, other, "origin", "HEAD:main")
    assert got.returncode != 0, f"a foreign checkout was pushed:\n{got.stdout}{got.stderr}"
    assert "this repo only" in (got.stdout + got.stderr).lower(), got.stdout + got.stderr
    assert _git(bare, "rev-parse", "refs/heads/dev") == before
    assert not (tmp_path / "synced").exists()


def test_another_remote_of_this_repo_is_allowed(tmp_path):
    """The guard above refused `tools/nos-push gitea pzny` (review 2026-10-22, defect 5): it compared
    with origin's URL alone. Any remote the script's own checkout holds is this repo."""
    bare, tools, work = _estate(tmp_path)
    mirror = tmp_path / "mirror.git"
    _git(tmp_path, "init", "-q", "--bare", str(mirror))
    _git(tools, "remote", "add", "mirror", str(mirror))
    _git(tools, "push", "-q", "mirror", "HEAD:refs/heads/dev")
    _git(work, "checkout", "-q", "--detach")
    sha = _commit(work, "change")
    got = _push(tools, work, str(mirror), "HEAD:dev")
    assert got.returncode == 0, f"a remote of this repo was refused:\n{got.stdout}{got.stderr}"
    assert _git(mirror, "rev-parse", "refs/heads/dev") == sha
