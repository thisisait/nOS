"""Trunk sync excuses only a rejected fast-forward; an auth or network failure is red.

Exit 10 means "the forge's trunk is ahead, promote it" and Pulse excuses it. Until 2026-10-27 any
failed `git push` set it, so an expired token or a dead forge read as "ahead" forever. Same class
as contradiction-scan's crash-as-finding (test_a_findings_code_is_not_a_crash_code.py).

Executed: each script from a scratch tree with a fake git whose push fails the way git does.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
REJECTED = " ! [rejected]        dev -> dev (non-fast-forward)\nerror: failed to push some refs"
AUTH = "remote: HTTP Basic: Access denied\nfatal: Authentication failed for 'https://oauth2:FAKE_TOKEN@x/o/n.git/'"


def _run(tmp_path, forge, push_err):
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    shutil.copy(REPO / f"tools/sync-trunk-to-{forge}.sh", root / "tools")
    (root / "config.yml").write_text(f"install_{forge}: true\n{forge}_agent_forge: true\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    git = bin_ / "git"
    git.write_text('#!/bin/bash\ncase "$1" in\n  remote) echo https://github.com/o/n.git;;\n'
                   '  push) printf "%s\\n" "$FAKE_PUSH_ERR" >&2; exit 1;;\nesac\nexit 0\n')
    git.chmod(git.stat().st_mode | stat.S_IXUSR)
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", HOME=str(tmp_path),
               FAKE_PUSH_ERR=push_err, **{f"{forge.upper()}_TOKEN": "FAKE_TOKEN",
                                          f"{forge.upper()}_DOMAIN": "x"})
    return subprocess.run(["bash", str(root / f"tools/sync-trunk-to-{forge}.sh"), "dev"],
                          capture_output=True, text=True, env=env, timeout=30)


@pytest.mark.parametrize("forge", ["gitea", "gitlab"])
def test_a_rejected_fast_forward_is_the_finding(tmp_path, forge):
    r = _run(tmp_path, forge, REJECTED)
    assert r.returncode == 10, r.stdout + r.stderr


@pytest.mark.parametrize("forge", ["gitea", "gitlab"])
def test_a_failed_login_is_a_crash_and_hides_the_token(tmp_path, forge):
    r = _run(tmp_path, forge, AUTH)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Authentication failed" in r.stderr and "FAKE_TOKEN" not in r.stdout + r.stderr
