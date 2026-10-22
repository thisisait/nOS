"""Every agent Iris may start is open to the person who asks, and writes no KEAP.

WHY (iris-subagent-for-tier-two). start_agent is tier 2 (managers and above), but Wing
opens an agent below Tier 1 only when it declares metadata.end_user: true. Neither
conductor nor surveyor did, so a manager's approved start came back 403. The list
(iris_startable_agents) is pinned by its properties, not its names: an agent added
later that is not open to end users, or holds keap.write, fails here, not live.
"""
from __future__ import annotations

import json
import shutil

import yaml

from test_face_user_owns_its_sessions import AUTOLOAD, REPO, _php, needs_php, needs_vendor
from test_thalamus_role import _default_config
from test_thalamus_speaks_for_a_person_only_to_start import _harness, _start, _thal

AGENTS = REPO / "files/anatomy/agents"


def _startable() -> list[str]:
    return _default_config()["iris_startable_agents"]


def test_every_startable_agent_is_open_to_end_users_and_writes_no_keap():
    assert _startable(), "iris_startable_agents is empty: nothing to pin"
    for name in _startable():
        agent = yaml.safe_load((AGENTS / name / "agent.yml").read_text(encoding="utf-8"))
        assert (agent.get("metadata") or {}).get("end_user") is True, \
            f"{name}: Iris starts it for tier 2, so it declares metadata.end_user: true"
        assert "keap.write" not in (agent.get("audit") or {}).get("capability_scopes", []), \
            f"{name}: an agent a manager may start holds no keap.write"


@needs_php
@needs_vendor
def test_a_tier_two_start_through_the_thalamus_opens_only_end_user_agents(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_REPO_ROOT", str(REPO))  # the loader checks backends + gate sets against the repo's registries
    root = tmp_path / "agents"
    for name in ["ops-triage", *_startable()]:
        shutil.copytree(AGENTS / name, root / name)
    manager = _thal(uid="alice", groups="nos-users,nos-managers")
    got = _php(_harness(), str(AUTOLOAD), str(root),
               json.dumps([_start(name, **manager) for name in [*_startable(), "ops-triage"]]))
    *opened, closed = got
    for name, g in zip(_startable(), opened):
        assert g["code"] == 202 and g["body"]["actor_id"] == "user:alice", (name, g)
    assert closed["code"] == 403, f"an agent without metadata.end_user stays closed to tier 2: {closed}"
