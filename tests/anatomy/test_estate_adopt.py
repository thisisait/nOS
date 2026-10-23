"""tools/estate-adopt.sh builds an estate's own main clone, offline, on throwaway repos.

Why it exists: test_a_worktree_converge_matches_the_main_checkout.py (a client converged from a
worktree of a development clone 354 commits behind). The tool is the fix the refusal names.
"""

from __future__ import annotations

import os
import pathlib
import stat
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "estate-adopt.sh"


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _world(tmp: pathlib.Path):
    seed = tmp / "seed"
    seed.mkdir()
    _git(seed, "init", "-q", "-b", "dev")
    _git(seed, "-c", "user.email=a@example.test", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "one")
    up = tmp / "up.git"
    _git(tmp, "clone", "-q", "--bare", str(seed), str(up))
    old = tmp / "old"
    old.mkdir()
    # A galaxy role lives in roles/ but is gitignored, so a clone never carries it.
    (old / "roles" / "elliotweiser.osx-command-line-tools" / "tasks").mkdir(parents=True)
    (old / "roles" / "elliotweiser.osx-command-line-tools" / "tasks" / "main.yml").write_text("---\n")
    (old / "config.yml").write_text("install_keap: true\n")
    (old / "credentials.yml").write_text("k: v\n")
    (old / "config.bak.yml").write_text("x: 1\n")
    home = tmp / "home"
    (home / ".nos").mkdir(parents=True)
    (home / ".nos" / "nos-cli.env").write_text("NOS_SRC=/old\nNOS_PY=/py\n")
    return up, old, home


def _run(home, *args):
    return subprocess.run(["bash", str(TOOL), *args], capture_output=True, text=True, env={**os.environ, "HOME": str(home)})


def test_a_dry_run_changes_nothing(tmp_path):
    up, old, home = _world(tmp_path)
    r = _run(home, "--dir", str(tmp_path / "estate"), "--from", str(old), "--upstream", str(up))
    assert r.returncode == 0 and "dry run" in r.stdout, r.stderr
    assert not (tmp_path / "estate").exists()
    assert (home / ".nos" / "nos-cli.env").read_text() == "NOS_SRC=/old\nNOS_PY=/py\n"


def test_confirm_builds_the_layout_and_carries_the_config(tmp_path):
    up, old, home = _world(tmp_path)
    est = tmp_path / "estate"
    r = _run(home, "--dir", str(est), "--from", str(old), "--upstream", str(up), "--fork", "https://example.test/fork.git", "--confirm")
    assert r.returncode == 0, r.stderr
    assert _git(est, "rev-parse", "--git-common-dir") == ".git", "a main clone, not a worktree"
    assert _git(est, "branch", "--show-current") == "estate"
    assert _git(est, "rev-parse", "--abbrev-ref", "estate@{upstream}") == "origin/dev"
    assert _git(est, "remote", "get-url", "--push", "origin") == "DISABLED"
    assert _git(est, "remote", "get-url", "fork") == "https://example.test/fork.git"
    for f in ("config.yml", "credentials.yml", "config.bak.yml"):
        assert (est / f).read_text() == (old / f).read_text(), f
    assert stat.S_IMODE((est / "credentials.yml").stat().st_mode) == 0o600
    env = (home / ".nos" / "nos-cli.env").read_text().splitlines()
    assert f"NOS_SRC={est}" in env and "NOS_PY=/py" in env and "NOS_SRC=/old" not in env, env
    assert (home / ".nos" / "nos-cli.env.prev").read_text().startswith("NOS_SRC=/old")
    assert (old / "config.yml").exists(), "the old checkout is never touched"
    # Live 2026-10-14: the first converge from the adopted clone died "role elliotweiser.osx-command-line-tools
    # was not found" — galaxy roles are gitignored. --from carries the ones the old tree verified.
    assert (est / "roles" / "elliotweiser.osx-command-line-tools" / "tasks" / "main.yml").exists()


def test_confirm_carries_the_tofu_state(tmp_path):
    """Live 2026-10-23: the first converge from ~/.nos/estate planned to CREATE 13 Authentik
    proxy providers and nos_roles that already existed (400 "already exists" on each): the
    tofu state is gitignored in terraform/authentik/, so the clone had none. The state is
    carried with its backup, 0600 like credentials; a reconcile backup stays behind."""
    up, old, home = _world(tmp_path)
    tf = old / "terraform" / "authentik"
    tf.mkdir(parents=True)
    for name in ("terraform.tfstate", "terraform.tfstate.backup", "terraform.tfstate.reconcile-bak-20260615-084049"):
        (tf / name).write_text(f'{{"serial": 6, "name": "{name}"}}\n')
    est = tmp_path / "estate"
    r = _run(home, "--dir", str(est), "--from", str(old), "--upstream", str(up), "--confirm")
    assert r.returncode == 0, r.stderr
    for name in ("terraform.tfstate", "terraform.tfstate.backup"):
        got = est / "terraform" / "authentik" / name
        assert got.read_text() == (tf / name).read_text(), name
        assert stat.S_IMODE(got.stat().st_mode) == 0o600, name
    assert not (est / "terraform" / "authentik" / "terraform.tfstate.reconcile-bak-20260615-084049").exists()
    assert "terraform/authentik/terraform.tfstate" in r.stdout, "the plan names the state it carries"


def test_it_refuses_a_directory_in_use_and_a_source_without_config(tmp_path):
    up, old, home = _world(tmp_path)
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "x").write_text("x")
    r = _run(home, "--dir", str(busy), "--upstream", str(up), "--confirm")
    assert r.returncode == 1 and "not empty" in r.stderr
    r = _run(home, "--dir", str(tmp_path / "e2"), "--from", str(tmp_path), "--upstream", str(up), "--confirm")
    assert r.returncode == 1 and "no config.yml" in r.stderr
