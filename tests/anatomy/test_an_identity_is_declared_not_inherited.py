"""Accounts derive from the declared roster, never from the OS username.

WHY. Until 2026-08-19 no file said WHO exists on this estate:
`gitea_admin_user` derived from `ansible_facts['user_id']`, WOODPECKER_ADMIN
inherited that, and `akadmin` lived only inside an Authentik blueprint. The
operator signed into Woodpecker as `akadmin`, the allowlist said `pazny`,
and "The registration is closed" was the error message for an identity model
declared in four places and owned by none. `nos_identities` in
default.config.yml is now the roster; this gate pins that it stays one, that
its shape is checkable, and that the two consumers that caused the incident
DERIVE from it.

Doctrine: docs/doctrine/identity.md. Reader: tools/identity-status.py
(pinned separately by test_the_identity_reader_only_reads.py).

WHAT THIS GATE CANNOT DO: it cannot check the REALMS — a declared identity
may still be absent from live Authentik/Gitea/Woodpecker, and realm accounts
may exist that nobody declared (the reader found 65 orphaned
nos-tester-e2e-* Authentik accounts the day it first ran). Presence in the
declaration is not presence in the realm; ask tools/identity-status.py.
"""

from __future__ import annotations

import pathlib
import re

import jinja2
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CONFIG = REPO / "default.config.yml"

KINDS = {"operator", "user", "service", "agent"}
KNOWN_REALMS = {"authentik", "gitea", "gitlab", "woodpecker", "wing"}


def _config() -> dict:
    return yaml.safe_load(CONFIG.read_text())


def test_the_roster_exists_and_every_entry_is_well_formed():
    cfg = _config()
    roster = cfg.get("nos_identities")
    assert isinstance(roster, list) and roster, (
        "nos_identities is gone from default.config.yml — the estate is back "
        "to declaring identities nowhere"
    )
    for entry in roster:
        assert isinstance(entry, dict) and entry.get("name"), entry
        assert entry.get("kind") in KINDS, (
            f"{entry.get('name')}: kind must be one of {sorted(KINDS)}, "
            f"got {entry.get('kind')!r}"
        )
        assert entry.get("tier") in (1, 2, 3, 4), (
            f"{entry.get('name')}: tier must be RBAC 1-4 "
            "(the genome access-facet vocabulary)"
        )
        realms = entry.get("realms")
        assert isinstance(realms, list) and realms, (
            f"{entry.get('name')}: an identity with no realm exists nowhere "
            "— declare where the account must exist"
        )
        unknown = set(realms) - KNOWN_REALMS
        assert not unknown, (
            f"{entry.get('name')}: unknown realm(s) {sorted(unknown)} — "
            f"extend KNOWN_REALMS (and the reader) deliberately, in one commit"
        )


def test_akadmin_and_the_primary_admin_are_both_declared():
    """The two operators of the 2026-08-19 incident stay in the roster."""
    cfg = _config()
    names = [e.get("name") for e in cfg["nos_identities"]]
    assert "akadmin" in names, "the SSO root left the roster"
    assert any("nos_primary_admin" in str(n) for n in names), (
        "the local forge admin left the roster"
    )


def test_gitea_admin_derives_from_the_roster_not_the_os():
    text = CONFIG.read_text()
    m = re.search(r"^gitea_admin_user:\s*(.+)$", text, re.M)
    assert m, "gitea_admin_user is gone from default.config.yml"
    assert "nos_primary_admin" in m.group(1), (
        "gitea_admin_user no longer derives from the declared roster"
    )
    assert "user_id" not in m.group(1), (
        "gitea_admin_user reads the OS username again — the identity model "
        "regressed to 'whoever ran the playbook'"
    )


def test_woodpecker_admins_are_the_roster_filtered_by_realm():
    """The allowlist is DERIVED — and renders to include both operators.

    Rendering runs under plain Jinja core, the same engine the eager
    `{{ vars }}` resolver has when ansible filter plugins are not loaded
    (test_config_stock_jinja_only doctrine) — so this doubles as proof the
    derivation survives that environment.
    """
    cfg = _config()
    env = jinja2.Environment()
    ctx = {
        "ansible_facts": {"user_id": "opuser"},
        "tenant_domain": "dev.local",
        "nos_tester_username": cfg.get("nos_tester_username", "nos-tester"),
    }
    ctx["default_admin_email"] = env.from_string(
        cfg["default_admin_email"]
    ).render(**ctx)
    ctx["nos_primary_admin"] = env.from_string(
        cfg["nos_primary_admin"]
    ).render(**ctx)
    ctx["nos_identities"] = [
        {**e, "name": env.from_string(str(e["name"])).render(**ctx)}
        for e in cfg["nos_identities"]
    ]
    raw = cfg["woodpecker_admin"]
    assert "nos_identities" in str(raw), (
        "woodpecker_admin is a hand-typed list again — the incident class "
        "this registry closed is reopened"
    )
    rendered = env.from_string(str(raw)).render(**ctx)
    admins = set(rendered.split(","))
    assert "akadmin" in admins, (
        f"akadmin fell out of the derived Woodpecker allowlist ({rendered!r})"
        " — an SSO login as the root operator would be refused again"
    )
    assert "opuser" in admins, (
        f"the primary admin fell out of the derived allowlist ({rendered!r})"
    )
