"""`nos update [ref]` moves the estate checkout, and only forward, only to signed code.

WHY (row estate-dev-split, 2026-10-23). The estate converged from the operator's
development tree: preflight pinned nos_main_checkout to ~/projects/nOS, so a
feature-branch checkout changed what Pulse, the agents and the launchd plists
ran, and agent worktrees held branches the operator could not check out. Now the
estate is its own clone (~/.nos/estate, NOS_ESTATE_DIR overrides) at an explicit
ref. tools/estate-adopt.sh builds it once (it carries config.yml, credentials.yml
and the galaxy roles git does not track); `nos update` only moves it: it fetches,
refuses a dirty clone, refuses a move that is not a fast-forward, refuses a ref
whose apex ruling is unsigned (the signature that gates what ships), checks the
ref out as branch `estate` (estate-adopt's) and points the CLI's NOS_SRC at it.

End to end against a bare origin in tmp; HOME is tmp, so nothing of the host is touched.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NOS = REPO / "tools" / "nos"
RULING = "files/anatomy/apex/ruling.yml"


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _ruling(signed: bool, note: str) -> str:
    body = f"version: 1\nnote: {note}\n"
    digest = hashlib.sha256(body.encode()).hexdigest() if signed else "0" * 64
    return body + f"signed_digest: {digest}\n"


def _commit(clone: Path, note: str, signed: bool = True) -> str:
    p = clone / RULING
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_ruling(signed, note))
    _git(clone, "add", "-A")
    _git(clone, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-qm", note)
    return _git(clone, "rev-parse", "HEAD")


def _world(tmp: Path):
    origin = tmp / "origin.git"
    _git(tmp, "init", "-q", "--bare", str(origin))
    dev = tmp / "dev"
    _git(tmp, "clone", "-q", str(origin), str(dev))
    sha = _commit(dev, "one")
    _git(dev, "push", "-q", "origin", "HEAD:refs/heads/dev")
    home = tmp / "home"
    (home / ".nos").mkdir(parents=True)
    (home / ".nos" / "nos-cli.env").write_text(f"NOS_SRC={dev}\nNOS_SEED_DIR=/seed\n")
    # What tools/estate-adopt.sh builds: a clone on branch `estate` tracking origin/dev.
    est = home / ".nos" / "estate"
    _git(tmp, "clone", "-q", "--origin", "origin", str(origin), str(est))
    _git(est, "switch", "-q", "-c", "estate", "--track", "origin/dev")
    return origin, dev, home, sha


def _update(home: Path, dev: Path, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT", "NOS_"))}
    env.update(HOME=str(home), NOS_SRC=str(dev))
    return subprocess.run(["bash", str(NOS), "update", *args], env=env, capture_output=True, text=True, timeout=60)


def _estate(home: Path) -> Path:
    return home / ".nos" / "estate"


def test_without_an_estate_it_names_estate_adopt_and_touches_nothing(tmp_path):
    _, dev, home, _ = _world(tmp_path)
    subprocess.run(["rm", "-rf", str(_estate(home))], check=True)
    before = (home / ".nos" / "nos-cli.env").read_text()
    got = _update(home, dev)
    assert got.returncode == 2 and "estate-adopt.sh" in got.stderr, got.stdout + got.stderr
    assert not _estate(home).exists() and (home / ".nos" / "nos-cli.env").read_text() == before


def test_an_update_points_the_cli_at_the_estate(tmp_path):
    _, dev, home, sha = _world(tmp_path)
    got = _update(home, dev)
    assert got.returncode == 0, got.stdout + got.stderr
    est = _estate(home)
    assert _git(est, "rev-parse", "HEAD") == sha
    assert _git(est, "symbolic-ref", "--short", "HEAD") == "estate"
    assert _git(est, "rev-parse", "--abbrev-ref", "estate@{upstream}") == "origin/dev"
    env = (home / ".nos" / "nos-cli.env").read_text()
    assert f"NOS_SRC={est}\n" in env and "NOS_SEED_DIR=/seed\n" in env, env


def test_an_update_moves_forward_to_the_new_signed_commit(tmp_path):
    _, dev, home, _ = _world(tmp_path)
    assert _update(home, dev).returncode == 0
    two = _commit(dev, "two")
    _git(dev, "push", "-q", "origin", "HEAD:refs/heads/dev")
    got = _update(home, dev)
    assert got.returncode == 0, got.stdout + got.stderr
    assert _git(_estate(home), "rev-parse", "HEAD") == two
    assert two[:9] in got.stdout


def test_a_dirty_estate_is_refused_and_not_moved(tmp_path):
    _, dev, home, sha = _world(tmp_path)
    assert _update(home, dev).returncode == 0
    (_estate(home) / "hand-edit.txt").write_text("x")
    _commit(dev, "two")
    _git(dev, "push", "-q", "origin", "HEAD:refs/heads/dev")
    got = _update(home, dev)
    assert got.returncode == 3, got.stdout + got.stderr
    assert "hand-edit.txt" in got.stderr
    assert _git(_estate(home), "rev-parse", "HEAD") == sha


def test_an_unsigned_ruling_is_refused_and_not_moved(tmp_path):
    _, dev, home, sha = _world(tmp_path)
    assert _update(home, dev).returncode == 0
    _commit(dev, "unsigned", signed=False)
    _git(dev, "push", "-q", "origin", "HEAD:refs/heads/dev")
    got = _update(home, dev)
    assert got.returncode == 4, got.stdout + got.stderr
    assert "apex" in got.stderr.lower()
    assert _git(_estate(home), "rev-parse", "HEAD") == sha


def test_a_move_that_is_not_a_fast_forward_is_refused(tmp_path):
    _, dev, home, sha = _world(tmp_path)
    assert _update(home, dev).returncode == 0
    _git(dev, "reset", "-q", "--hard", "HEAD")
    _git(dev, "checkout", "-q", "--orphan", "rewrite")
    _commit(dev, "rewritten")
    _git(dev, "push", "-q", "--force", "origin", "HEAD:refs/heads/dev")
    got = _update(home, dev)
    assert got.returncode == 5, got.stdout + got.stderr
    assert _git(_estate(home), "rev-parse", "HEAD") == sha


def test_a_tag_is_a_ref_too(tmp_path):
    _, dev, home, sha = _world(tmp_path)
    _git(dev, "tag", "v0.18.0")
    _git(dev, "push", "-q", "origin", "v0.18.0")
    got = _update(home, dev, "v0.18.0")
    assert got.returncode == 0, got.stdout + got.stderr
    assert _git(_estate(home), "rev-parse", "HEAD") == sha
    assert "v0.18.0" in got.stdout


def test_update_runs_before_the_converge_exec():
    src = NOS.read_text(encoding="utf-8")
    assert 0 < src.find('= "update" ]') < src.find('"${ARGS[@]}" </dev/null'), (
        "`nos update` must exit before the ansible-playbook exec: an update never converges")


def test_every_converge_installs_the_cli():
    """`nos update` moves the clone, a converge moves it into runtime — the CLI too.
    Tagged nos-cli only, `nos --tags wing,pulse` left the installed CLI two days old."""
    import yaml
    plays = yaml.safe_load((REPO / "main.yml").read_text())
    tasks = [t for play in plays for key in ("pre_tasks", "tasks") for t in play.get(key) or []]
    cli = next(t for t in tasks if t.get("ansible.builtin.import_tasks") == "tasks/nos-cli.yml")
    assert "always" in cli["tags"], cli["tags"]
