"""The thalamus holds one Wing bearer, `thalamus`, scoped to starting a session for a person.

WHY (iris-agent-dendrogram, increment 2). start_agent opens a Wing session after the
person approves. The thalamus serves every login, so it must not hold an estate
token (test_end_user_services_hold_no_estate_token.py): it gets its own HKDF-derived
row, wing.write only (wing.operator stays face-bff's), and Wing believes a person on
it for the spawn alone (test_thalamus_speaks_for_a_person_only_to_start.py). Which
agents Iris may start is iris_startable_agents; the plist and the Linux env carry
the token, the URL and that list, and nothing renders without the token.
"""
from __future__ import annotations

import re

import jinja2
import yaml

from test_thalamus_role import REPO, ROLE, _default_config, _plist

POST_YML = REPO / "roles/pazny.wing/tasks/post.yml"


def test_the_token_is_derived_and_registered_once():
    creds = (REPO / "default.credentials.yml").read_text(encoding="utf-8")
    assert re.search(r'^thalamus_wing_api_token: "\{\{ nos_derived_secrets\.wing_thalamus \}\}"', creds, re.M), \
        "thalamus_wing_api_token derives from nos_derived_secrets.wing_thalamus"
    reg = yaml.safe_load((REPO / "files/anatomy/secrets/registry.yml").read_text(encoding="utf-8"))
    leaves = next(v for v in reg.values() if isinstance(v, dict) and "wing_face_bff" in v)
    assert leaves["wing_thalamus"] == {"service": "wing", "purpose": "bearer-thalamus"}


def test_wing_mints_it_write_only():
    tasks = yaml.safe_load(POST_YML.read_text(encoding="utf-8"))
    argv = [t["ansible.builtin.command"]["argv"] for t in tasks
            if isinstance(t, dict) and "--name=thalamus" in (t.get("ansible.builtin.command") or {}).get("argv", [])]
    assert len(argv) == 1, "one mint of the thalamus row"
    assert "--token={{ thalamus_wing_api_token }}" in argv[0]
    assert "--scopes=wing.write" in argv[0], "wing.write only: no operator verb, no read beyond its own spawn"


def test_the_allow_list_defaults_to_read_only_agents():
    agents = _default_config()["iris_startable_agents"]
    assert agents == ["conductor", "surveyor"], agents
    for a in agents:
        scopes = yaml.safe_load((REPO / f"files/anatomy/agents/{a}/agent.yml").read_text())["audit"]["capability_scopes"]
        # A report event (events.write, wing.write to /events) is the only write a default may hold.
        writes = {s for s in scopes if s.endswith((".write", ".operator", ".exec"))} - {"events.write", "wing.write"}
        assert not writes, (a, scopes)


def test_the_plist_carries_the_door_only_with_its_token():
    env = _plist(thalamus_wing_api_token="wt-1", wing_port=9000, iris_startable_agents=["conductor", "surveyor"])["EnvironmentVariables"]
    assert (env["NOS_SECRET_WING_TOKEN"], env["NOS_WING_URL"], env["NOS_IRIS_STARTABLE_AGENTS"]) == \
        ("wt-1", "http://127.0.0.1:9000", "conductor,surveyor")
    bare = _plist(thalamus_wing_api_token="")["EnvironmentVariables"]
    assert not {"NOS_SECRET_WING_TOKEN", "NOS_WING_URL"} & set(bare)


def test_the_linux_env_carries_the_same_door():
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["bool"] = bool
    ctx = {"ansible_managed": "managed", "ansible_facts": {"env": {"HOME": "/h"}}, "nos_tools_venv": "/v", "nos_main_checkout": "/repo",
           "keap_proxy_shared_secret": "s", "thalamus_shared_socket": "/run/nos/thalamus.sock", "thalamus_roadmap_table_id": "rt",
           "authentik_rbac_tiers": _default_config()["authentik_rbac_tiers"], "thalamus_binding_env": {},
           "thalamus_wing_api_token": "wt-1", "wing_port": 9000, "iris_startable_agents": ["conductor"]}
    text = env.from_string((ROLE / "templates" / "thalamus.env.j2").read_text()).render(**ctx)
    assert "NOS_SECRET_WING_TOKEN=wt-1\n" in text and "NOS_WING_URL=http://127.0.0.1:9000\n" in text
    assert "NOS_IRIS_STARTABLE_AGENTS=conductor\n" in text
