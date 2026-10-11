"""Paperclip must SERVE its hostname after a converge, not only have it on file.

Measured 2026-10-11 on a second Mac: config.json carried
`allowedHostnames: ["paperclip.<tld>"]`, the container had started two days
earlier, and every request answered 403 "This hostname is not allowed". The
registration said "already allowed", so changed=false and the restart handler
never fired; the run that HAD written the hostname died before handlers
flushed. A restart keyed on `changed` is lost with its play.

Pinned: after registration the role asks the server itself (Host header,
body read), restarts when the server still refuses, and fails if it refuses
after the restart.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
POST = REPO / "roles/pazny.paperclip/tasks/post.yml"
REFUSAL = "not allowed"


def _tasks() -> list[dict]:
    return yaml.safe_load(POST.read_text())


def _index(pred) -> int:
    return next((i for i, t in enumerate(_tasks()) if pred(t)), -1)


def _register_i() -> int:
    return _index(lambda t: t.get("name", "").endswith("Register primary allowed hostname"))


def test_the_server_is_asked_after_registration():
    probe = _index(lambda t: "ansible.builtin.uri" in t
                   and t["ansible.builtin.uri"].get("return_content")
                   and "Host" in (t["ansible.builtin.uri"].get("headers") or {}))
    assert probe > _register_i() >= 0, (
        "no Host-header probe that reads the body after the hostname is "
        "registered; the file can say allowed while the server refuses")


def test_a_refusal_restarts_now_not_via_a_handler():
    tasks = _tasks()
    restart = next((t for t in tasks[_register_i() + 1:]
                    if "restart" in str(t.get("ansible.builtin.shell", ""))
                    and REFUSAL in str(t.get("when", ""))), None)
    assert restart is not None, (
        f"no restart conditioned on the server's '{REFUSAL}' answer; a "
        "handler keyed on `changed` is lost when the play fails later")
    assert "notify" not in tasks[_register_i()], (
        "registration still notifies a handler; the probe owns the restart now, "
        "so the notify would restart twice")


def test_a_refusal_after_restart_fails_the_run():
    tasks = _tasks()[_register_i() + 1:]
    assert any("fail" in " ".join(t) and REFUSAL in str(t.get("when", "")) + str(t.get("failed_when", ""))
               for t in tasks), (
        "nothing fails the run when Paperclip still refuses its hostname after "
        "the restart; the 403 would surface only in smoke")
