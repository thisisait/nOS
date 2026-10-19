"""The `unix` realm: host logins come from the roster and nothing else.

roles/pazny.linux.users replaced bootstrap/minimal-linux-dgx's useradd lines
and its Authentik→Linux sync daemon (2026-10-19, DGX cut-over to the playbook).
What it must keep true, so a shared Linux host separates people's data:

- the people are read from nos_identities / nos_synthetic_identities /
  nos_extra_identities where realms name `unix` — never the converging user;
- a login is never DELETED (a home is data); a switched-off synthetic is LOCKED;
- every home is 0700 and owned by its person;
- the password hash is salted from the name, so re-hashing does not churn;
- the role runs on Linux only, after the identity passwords are derived.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLE = REPO / "roles" / "pazny.linux.users"


def _tasks() -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())


def test_people_come_from_the_roster_only():
    who = next(t for t in _tasks() if "_unix_people" in (t.get("ansible.builtin.set_fact") or {}))
    expr = who["ansible.builtin.set_fact"]["_unix_people"]
    for roster in ("nos_identities", "nos_synthetic_identities", "nos_extra_identities"):
        assert roster in expr, f"{roster} is not read — its unix-realm people get no login"
    assert expr.count("'unix' in") == 3, "every roster is filtered by the unix realm"
    for t in _tasks():                       # task bodies, not comments
        body = yaml.safe_dump(t)
        for inherited in ("ansible_user_id", "ansible_facts['user_id']", "ansible_env.USER"):
            assert inherited not in body, f"{t.get('name')}: a login derived from who runs the converge"


def test_no_login_is_ever_removed():
    for t in _tasks():
        mod = t.get("ansible.builtin.user") or {}
        assert mod.get("state", "present") != "absent", "a person's home is data — lock, never delete"
        assert "remove" not in mod
    users = [t["ansible.builtin.user"] for t in _tasks() if "ansible.builtin.user" in t]
    assert users and "password_lock" in users[0], "a switched-off synthetic must be locked"


def test_homes_are_private_and_hashes_stable():
    d = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
    assert d["linux_users_home_mode"] == "0700"
    users = [t["ansible.builtin.user"] for t in _tasks() if "ansible.builtin.user" in t]
    assert "password_hash('sha512', (item.name | hash('sha256'))" in users[0]["password"]


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_the_role_runs_on_linux_after_the_passwords():
    play = yaml.safe_load((REPO / "main.yml").read_text())
    tasks = [n for n in _walk(play) if "name" in n]
    names = [n["name"] for n in tasks]
    at = next(i for i, n in enumerate(tasks)
              if (n.get("ansible.builtin.include_role") or {}).get("name") == "pazny.linux.users")
    exposed = names.index("[Identities] Expose the extra people's passwords")
    assert exposed < at, "the role runs before the passwords exist"
    assert "ansible_os_family in ['Debian']" in tasks[at]["when"]
