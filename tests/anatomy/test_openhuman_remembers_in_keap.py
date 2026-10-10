"""OpenHuman remembers in KEAP: the hippocampus (KEAP v2.1.0) serves the CortexDB wire.

OpenHuman v0.64.15 has no local memory store; its engine binds tinyhumans (cloud),
cortexdb (any endpoint) or none. nOS points cortexdb at KEAP's /hippocampus on
loopback, with a per-agent key, and the rows land in the `engram` DataTable.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

needs_ansible = pytest.mark.skipif(shutil.which("ansible-playbook") is None
                                   and not os.path.exists(os.path.join(os.path.dirname(sys.executable), "ansible-playbook")),
                                   reason="ansible not installed")

# What KEAP's hippocampus writes (server/hippocampus.ts, keap v2.1.0).
ENGRAM_COLUMNS = {"agent", "scope", "modality", "role", "text", "labels", "observed_at", "idempotency_key"}


def test_engram_is_created_by_a_converge():
    d = yaml.safe_load((REPO / "state/keap-tables/engram.table.yml").read_text())
    assert {c["key"] for c in d["schema"]["columns"]} == ENGRAM_COLUMNS
    core = yaml.safe_load((REPO / "roles/pazny.keap/tasks/seed-core-tables.yml").read_text())
    assert "engram" in [i["slug"] for i in core[0]["loop"]]


def test_the_key_is_a_derived_secret():
    reg = yaml.safe_load((REPO / "files/anatomy/secrets/registry.yml").read_text())["credentials"]
    assert reg["keap_hippocampus_openhuman"] == {"service": "keap", "purpose": "hippocampus-openhuman"}
    creds = yaml.safe_load((REPO / "default.credentials.yml").read_text())
    assert creds["keap_hippocampus_key_openhuman"] == "{{ nos_derived_secrets.keap_hippocampus_openhuman }}"


def _keap_env(tmp: Path, install_openhuman: bool) -> dict:
    out = tmp / "compose.yml"
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
             "vars_files": [*map(str, ni.default_layers()), str(REPO / "roles/pazny.keap/defaults/main.yml")],
             "vars": {"ansible_facts": {"env": {"HOME": "/h"}}, "keap_image_tag": "t",
                      "nos_derived_secrets": {"keap_agent_ro": "a", "keap_agent_rw": "b", "keap_agent_capture": "c",
                                              "keap_proxy_shared": "d", "keap_hippocampus_openhuman": "K"}},
             "tasks": [{"copy": {"dest": str(out), "content":
                                 "{{ lookup('template', '%s') }}" % (REPO / "roles/pazny.keap/templates/compose.yml.j2")}}]}]
    (tmp / "play.yml").write_text(yaml.safe_dump(play))
    r = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", str(tmp / "play.yml"),
                        "-e", f"@{REPO / 'default.credentials.yml'}", "-e", f"install_openhuman={install_openhuman}"],
                       capture_output=True, text=True, timeout=300,
                       env={**os.environ, "ANSIBLE_LOCAL_TEMP": str(tmp / ".a")})
    assert r.returncode == 0, r.stdout[-2000:]
    return yaml.safe_load(out.read_text())["services"]["keap"]["environment"]


@needs_ansible
@pytest.mark.parametrize("install_openhuman", [True, False])
def test_keap_holds_the_openhuman_key_only_with_openhuman(tmp_path, install_openhuman):
    env = _keap_env(tmp_path, install_openhuman)
    if install_openhuman:
        assert env.get("KEAP_HIPPOCAMPUS_KEYS") == "openhuman:K", env.get("KEAP_HIPPOCAMPUS_KEYS")
    else:
        assert "KEAP_HIPPOCAMPUS_KEYS" not in env   # unset → every /hippocampus route is 503


def test_keap_is_pinned_to_the_hippocampus_release():
    cfg = ni.default_config()
    role = yaml.safe_load((REPO / "roles/pazny.keap/defaults/main.yml").read_text())
    assert tuple(map(int, cfg["keap_version"].split("."))) >= (2, 1, 0)
    assert tuple(map(int, role["keap_repo_ref"].lstrip("v").split("."))) >= (2, 1, 0)


def _reader():
    spec = importlib.util.spec_from_file_location("ohs", REPO / "tools/openhuman-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("status, state", [(401, "OK"), (503, "RED"), (404, "RED"), (None, "UNKNOWN")])
def test_the_reader_says_whether_the_hippocampus_answers(status, state):
    """No key needed: an unauthenticated health call is 401 when the route is live,
    503 when KEAP holds no key, 404 on a KEAP older than v2.1.0."""
    mod = _reader()
    assert mod.judge_hippocampus(status, "http://127.0.0.1:8091/hippocampus")["state"] == getattr(mod, state)


def test_keap_post_start_verifies_the_hippocampus_answers():
    """The effect is KEAP's to verify, after its rebuild: with OpenHuman on, a keyless
    health call must be 401 (live, key required) — 503 means KEAP got no key, 404 an old KEAP."""
    tasks = yaml.safe_load((REPO / "roles/pazny.keap/tasks/post.yml").read_text())
    probes = [t for t in tasks if "/hippocampus/v1/admin/health" in str((t.get("ansible.builtin.uri") or {}).get("url", ""))]
    assert probes, "no post-start probe of /hippocampus"
    t = probes[0]
    assert t["ansible.builtin.uri"]["status_code"] == [401], t
    assert "install_openhuman" in str(t.get("when")), t
