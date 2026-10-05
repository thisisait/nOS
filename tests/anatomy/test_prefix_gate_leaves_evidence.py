"""Gate: every run records what the prefix gate read, and never the value.

sec-prefix-gate-flaps (2026-08-31): `global_password_prefix not in ['changeme','']`
failed 3 of 5 identical runs and nothing said why. The record task's own Jinja
runs here through real Ansible against a temp playbook_dir.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
NAME = "[Security] Record what the prefix gate reads (never the value)"


def _task():
    def walk(node):
        if isinstance(node, list):
            for x in node:
                yield from walk(x)
        elif isinstance(node, dict):
            if node.get("name") == NAME:
                yield node
            for v in node.values():
                yield from walk(v)
    return next(walk(yaml.safe_load((REPO / "main.yml").read_text())))


def _run(tmp_path, prefix):
    (tmp_path / "credentials.yml").write_text('global_password_prefix: "x"\n')
    (tmp_path / "config.yml").write_text("install_wing: true\n")
    task = dict(_task())
    out = tmp_path / "prefix-gate.jsonl"
    task["ansible.builtin.lineinfile"] = {**task["ansible.builtin.lineinfile"], "path": str(out)}
    task["no_log"] = False
    play = [{"hosts": "localhost", "gather_facts": False, "connection": "local",
             "vars": {"global_password_prefix": prefix}, "tasks": [task]}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    r = subprocess.run(["ansible-playbook", "-i", "localhost,", str(tmp_path / "play.yml")],
                       capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stdout[-800:]
    return out.read_text(), json.loads(out.read_text().splitlines()[-1]), r.stdout


@pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="renders through real Ansible")
def test_a_strong_prefix_is_recorded_by_length_and_digest_only(tmp_path):
    raw, rec, stdout = _run(tmp_path, "SuperSecretPrefix42")
    assert "SuperSecretPrefix42" not in raw and "SuperSecretPrefix42" not in stdout
    assert rec["length"] == 19 and rec["weak"] is False and len(rec["digest"]) == 16
    assert rec["declared_in"] == ["credentials.yml"]
    assert isinstance(rec["converges_running"], int)


@pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="renders through real Ansible")
def test_a_weak_prefix_is_marked_weak(tmp_path):
    _, rec, _ = _run(tmp_path, "changeme")
    assert rec["weak"] is True and rec["length"] == 8


def test_the_record_runs_before_the_gate_always_and_quietly():
    plays = yaml.safe_load((REPO / "main.yml").read_text())
    names = [t.get("name") for p in plays for k in ("pre_tasks", "tasks") for t in (p.get(k) or [])]
    assert names.index(NAME) + 1 == names.index("[Security] Refuse a weak password prefix")
    t = _task()
    assert t["no_log"] is True and "always" in t["tags"] and t["failed_when"] is False
