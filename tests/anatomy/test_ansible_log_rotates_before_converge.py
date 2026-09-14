"""S7 — nos rotates a bloated ansible.log before ansible opens it.

p=54800 left ~/.nos/ansible.log ~250 MB. ansible.cfg log_path appends for
the whole play; truncating mid-run would eat the recap. Rotate the previous
file, then let ansible create a new one (the playbook pins 0600).
"""
from __future__ import annotations

import os
import stat as statmod
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NOS = REPO / "tools" / "nos"


def test_nos_rotates_ansible_log_before_exec_not_on_print_cmd():
    text = NOS.read_text(encoding="utf-8")
    print_at = text.index('if [ "$PRINT_CMD" -eq 1 ]')
    # First "ansible.log" can live in the header comment and would lie about
    # order. Pin the rotate assignment, which is the actual mv source.
    rotate_at = text.index('_NOS_LOG="${HOME}/.nos/ansible.log"')
    exec_at = text.index('exec "${ARGS[@]}"')
    assert print_at < rotate_at < exec_at, (
        "rotation must run after --print-cmd exits and before ansible-playbook exec"
    )
    after_print = text[print_at:rotate_at]
    assert "exit 0" in after_print
    assert "52428800" in text or "NOS_ANSIBLE_LOG_MAX" in text
    assert 'mv "$_NOS_LOG"' in text
    assert "truncate" not in text.lower()


def test_print_cmd_does_not_rotate_log(tmp_path):
    nos_home = tmp_path / "home"
    logdir = nos_home / ".nos"
    logdir.mkdir(parents=True)
    log = logdir / "ansible.log"
    log.write_text("keep-me\n")
    env = dict(
        os.environ,
        HOME=str(nos_home),
        NOS_SRC=str(REPO),
        NOS_ANSIBLE_LOG_MAX="1",
    )
    r = subprocess.run(
        [str(NOS), "--print-cmd"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert r.returncode == 0, r.stderr
    assert log.read_text() == "keep-me\n"
    assert not (logdir / "ansible.log.1").exists()


def test_converge_rotates_bloated_log_before_ansible(tmp_path):
    stub = tmp_path / "ansible-playbook"
    stub.write_text("#!/bin/sh\necho STUB\nexit 0\n")
    stub.chmod(stub.stat().st_mode | statmod.S_IEXEC)
    nos_home = tmp_path / "home"
    logdir = nos_home / ".nos"
    logdir.mkdir(parents=True)
    log = logdir / "ansible.log"
    log.write_text("old-run\n")
    env = dict(
        os.environ,
        PATH=f"{tmp_path}:{os.environ['PATH']}",
        HOME=str(nos_home),
        NOS_SRC=str(REPO),
        NOS_ANSIBLE_LOG_MAX="1",
    )
    r = subprocess.run(
        [str(NOS), "-y"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert r.returncode == 0, r.stderr
    rotated = logdir / "ansible.log.1"
    assert rotated.exists() and rotated.read_text() == "old-run\n"
    assert not log.exists()
