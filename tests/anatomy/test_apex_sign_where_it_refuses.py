"""`nos update` offers the apex signature on the commit it refuses; apex-sign --show is read-only.

2026-10-29: signing a ruling on a branch took a worktree, two apex-sign calls and a push, and
`apex-sign.py && apex-sign.py --confirm` never reached --confirm (the read exits 1), so the
unsigned ruling reached dev. Now the refusal itself offers the signature behind one explicit yes.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NOS = REPO / "tools" / "nos"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


upd = _load("nos_update_world", REPO / "tests/anatomy/test_nos_update_moves_the_estate.py")
sign = _load("apex_sign", REPO / "tools/apex-sign.py")


def _refused_world(tmp_path):
    origin, dev, home, sha = upd._world(tmp_path)
    est = upd._estate(home)
    for k, v in (("user.name", "t"), ("user.email", "t@t"), ("commit.gpgsign", "false")):
        upd._git(est, "config", k, v)
    upd._git(est, "remote", "set-url", "--push", "origin", "DISABLED")  # as estate-adopt.sh leaves it
    assert upd._update(home, dev).returncode == 0
    unsigned = upd._commit(dev, "unsigned", signed=False)
    upd._git(dev, "push", "-q", "origin", "HEAD:refs/heads/dev")
    return origin, dev, home, sha, unsigned


def _answer(home, dev, text):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT", "NOS_"))}
    env.update(HOME=str(home), NOS_SRC=str(dev))
    return subprocess.run(["bash", str(NOS), "update"], env=env, input=text, capture_output=True, text=True, timeout=60)


def test_no_refuses_and_signs_nothing(tmp_path):
    origin, dev, home, sha, unsigned = _refused_world(tmp_path)
    got = _answer(home, dev, "n\n")
    assert got.returncode == 4, got.stdout + got.stderr
    assert "[y/N]" in got.stderr and "signed_digest" in got.stderr, "the offer shows the diff"
    assert upd._git(origin, "rev-parse", "dev") == unsigned
    assert upd._git(upd._estate(home), "rev-parse", "HEAD") == sha


def test_yes_signs_pushes_and_moves(tmp_path):
    origin, dev, home, _, unsigned = _refused_world(tmp_path)
    got = _answer(home, dev, "y\n")
    assert got.returncode == 0, got.stdout + got.stderr
    head = upd._git(origin, "rev-parse", "dev")
    assert head != unsigned and upd._git(origin, "rev-parse", f"{head}^") == unsigned
    text = upd._git(origin, "show", f"{head}:{upd.RULING}") + "\n"
    assert sign.recorded(text) == sign.digest(text)
    assert upd._git(upd._estate(home), "rev-parse", "HEAD") == head
    assert upd._git(upd._estate(home), "worktree", "list").count("\n") == 0, "the signing worktree is gone"


def test_show_is_read_only_and_exits_0(tmp_path, monkeypatch):
    ruling = tmp_path / upd.RULING
    ruling.parent.mkdir(parents=True)
    ruling.write_text("note: changed\nsigned_digest: 0000\n")
    monkeypatch.setattr(sys, "argv", ["apex-sign.py", "--repo", str(tmp_path), "--show"])
    assert sign.main() == 0
    assert ruling.read_text() == "note: changed\nsigned_digest: 0000\n"
