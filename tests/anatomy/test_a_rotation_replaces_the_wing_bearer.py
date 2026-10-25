"""`-e secrets_rotate=wing_api_token` replaces the Wing bearer; any other name is refused.

WHY (row pulse-redact-gaps, 2026-10-25): the audit ledger and its backups held the Wing
bearer 98 times. Deleting rows does not kill a copy in a backup; only a replaced value
does, and a blank does not replace this one (it regenerates 7 other keys). The backup
passphrase is NOT rotatable here yet: its outgoing value must come from a source the
rotation does not touch (test_key_ring_captures_the_retired_key), a separate change.

Rendered, not grepped: the tasks are read from main.yml and evaluated in order, as
Ansible would (set_fact by set_fact, the assert before the mint), with plain Jinja.
"""
from __future__ import annotations

from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
ORDER = ["[Secrets] Resolve what this run rotates",
         "[Secrets] Refuse a name with no rotation path",
         "Lazy-regenerate placeholder APP_KEYs / tokens (first non-blank enable)"]
MINTED = "9" * 64
OLD = {"wing_api_token": "a" * 64, "backup_encryption_passphrase": "b" * 64}


def _tasks() -> dict[str, dict]:
    plays = yaml.safe_load((REPO / "main.yml").read_text(encoding="utf-8"))
    flat = [t for play in plays for k in ("pre_tasks", "tasks") for t in play.get(k) or []]
    seen = [t["name"] for t in flat if t.get("name") in ORDER]
    assert seen == ORDER, f"the resolve and the refusal must precede the mint: {seen}"
    return {t["name"]: t for t in flat if t.get("name") in ORDER}


def _converge(facts: dict) -> dict:
    env, tasks, facts = jinja2.Environment(), _tasks(), dict(facts)
    env.globals["lookup"] = lambda kind, cmd: MINTED  # openssl rand -hex 32
    for name in ORDER:
        t = tasks[name]
        if "ansible.builtin.assert" in t:
            a = t["ansible.builtin.assert"]
            if not env.compile_expression(a["that"])(**facts):
                raise AssertionError(env.from_string(a["fail_msg"]).render(**facts))
            continue
        for k, v in t["ansible.builtin.set_fact"].items():
            if name != ORDER[2] or k in OLD:
                out = env.from_string(str(v)).render(**facts)
                facts[k] = yaml.safe_load(out) if out.startswith("[") else out
    return facts


def test_without_the_flag_nothing_moves():
    f = _converge(OLD)
    assert f["wing_api_token"] == "a" * 64 and f["backup_encryption_passphrase"] == "b" * 64


def test_the_flag_replaces_the_wing_bearer_only():
    f = _converge(dict(OLD, secrets_rotate=" wing_api_token "))
    assert f["wing_api_token"] == MINTED
    assert f["backup_encryption_passphrase"] == "b" * 64, "the archive key moved without its ring"


@pytest.mark.parametrize("name", ["backup_encryption_passphrase", "bone_secret", "wing_api_token,nope"])
def test_a_name_with_no_rotation_path_is_refused(name):
    _tasks()  # outside the raises: "tasks missing" names a task "…no rotation path" and would pass it
    with pytest.raises(AssertionError, match="no rotation path here"):
        _converge(dict(OLD, secrets_rotate=name))
