"""Anatomy CI gate for the ephemeral tester identity library (A13.6).

This is a STATIC contract test — it does NOT hit Authentik. It validates:
  1. The library imports cleanly (catches syntax errors + missing deps).
  2. The TIER_TO_GROUP mapping covers all four canonical RBAC tiers and
     uses exactly the ``nos-<tier>s`` group names declared in
     ``default.config.yml::authentik_default_groups``.
  3. The username + token-name prefixes are stable contracts (the
     orphan-sweep CI gate + Wing audit-trail filters depend on them).
  4. The fixture in ``tests/e2e/conftest.py`` registers an atexit hook so
     crashed pytest processes can't strand identities.

Why this gate exists: prevents silent regressions when refactoring the lib.
A typo in ``USERNAME_PREFIX`` would break the orphan-sweep without any test
visibly failing — until weeks later when the cron sweep runs and finds 100
orphans.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
E2E_LIB = REPO_ROOT / "tests" / "e2e" / "lib"
CONFTEST = REPO_ROOT / "tests" / "e2e" / "conftest.py"


@pytest.fixture(scope="module")
def lib_module():
    """Import the lib once — fails the whole module fast if it doesn't import."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from tests.e2e.lib import tester_identity as ti
        return ti
    finally:
        # Don't pollute sys.path for sibling tests.
        try:
            sys.path.remove(str(REPO_ROOT))
        except ValueError:
            pass


def test_lib_imports_cleanly(lib_module):
    """tester_identity.py + its 3 dependent modules must all import."""
    assert hasattr(lib_module, "provision_tester")
    assert hasattr(lib_module, "teardown_tester")
    assert hasattr(lib_module, "sweep_orphans")
    assert hasattr(lib_module, "TesterIdentity")


def test_tier_mapping_canonical(lib_module):
    """All four canonical RBAC tiers must be present and map to the right
    Authentik group names. If a tier is added/renamed in default.config.yml,
    this test pins the contract."""
    expected = {
        "provider": "nos-providers",
        "manager":  "nos-managers",
        "user":     "nos-users",
        "guest":    "nos-guests",
    }
    assert lib_module.TIER_TO_GROUP == expected, (
        "TIER_TO_GROUP drifted from default.config.yml::authentik_default_groups; "
        "update both or fix one"
    )


def test_username_prefix_stable(lib_module):
    """Orphan sweeps + audit-trail filters depend on this exact prefix."""
    assert lib_module.USERNAME_PREFIX == "nos-tester-e2e-"


def test_wing_token_name_prefix_stable(lib_module):
    """Wing api_tokens table audit-trail filter (``WHERE name LIKE
    'tester:e2e:%'``) requires this prefix to stay put."""
    assert lib_module.WING_TOKEN_NAME_PREFIX == "tester:e2e:"


def test_default_config_groups_match():
    """The four group names in TIER_TO_GROUP must be subsets of the names in
    ``default.config.yml::authentik_default_groups``. Catches the case where
    someone renames a group in config without bumping the lib (or vice versa)."""
    cfg = (REPO_ROOT / "default.config.yml").read_text()
    # Extract group names declared in authentik_default_groups[*].name
    # We don't pull a YAML parser in here — keep this anatomy gate lock-stack-light.
    # Names are quoted in default.config.yml: ``- name: "nos-providers"``.
    # Tolerate both quoted + unquoted forms so the gate doesn't break if the
    # operator strips quotes during a future cleanup pass.
    declared = set(re.findall(
        r"-\s+name:\s+\"?(nos-[a-z]+)\"?\s*$",
        cfg, re.MULTILINE,
    ))
    required = {"nos-providers", "nos-managers", "nos-users", "nos-guests"}
    missing = required - declared
    assert not missing, (
        f"default.config.yml is missing canonical RBAC groups: {missing}. "
        f"Declared groups detected: {sorted(declared)}"
    )


def test_atexit_hook_registered():
    """conftest.py must register an atexit sweeper so a crashed pytest
    process can't strand TRACKED identities. We don't import conftest
    (pytest manages that lifecycle); regex-grep is enough as a contract test."""
    src = CONFTEST.read_text()
    assert "atexit.register" in src, "atexit.register() missing from conftest.py"
    assert "_atexit_sweep_provisioned" in src, (
        "conftest.py atexit handler renamed; update this test or restore name"
    )
    # _PROVISIONED tracking is the only safe atexit cleanup — see A13.6 incident
    # comment in conftest. We assert the tracking variable still exists.
    assert "_PROVISIONED" in src, (
        "conftest.py no longer tracks _PROVISIONED — atexit cleanup loses scope"
    )


def test_atexit_does_not_call_orphan_sweep():
    """A13.6 incident gate: conftest atexit handler MUST NOT call
    ``sweep_orphans`` automatically. The only path that may invoke it is
    the operator-driven CLI ``files/anatomy/scripts/sweep-orphan-testers.py``.

    Reason: a bug in ``list_users_by_prefix`` once caused atexit to delete
    8 unrelated Authentik users (2026-05-07). The lib has multiple safety
    layers now, but we still don't auto-sweep on process exit — explicit
    operator action is the only acceptable trigger for a destructive scan.
    """
    src = CONFTEST.read_text()
    # Find the atexit function body
    import re
    m = re.search(
        r"def _atexit_sweep_provisioned\(\)[^\n]*:\n(.+?)\natexit\.register",
        src, re.DOTALL,
    )
    assert m, "could not locate _atexit_sweep_provisioned body in conftest"
    body = m.group(1)
    # Strip docstring (triple-quoted block starting at top of body) so the
    # historical-context mention of sweep_orphans() inside the docstring
    # doesn't false-positive. Only actual code calls must trigger the gate.
    code = re.sub(r'(?s)"""[^"]+"""', "", body)
    assert "sweep_orphans(" not in code, (
        "conftest atexit handler calls sweep_orphans() — re-introduces "
        "A13.6 incident class. Move that call to the operator-invoked CLI "
        "(files/anatomy/scripts/sweep-orphan-testers.py) only."
    )


def test_sweep_orphans_has_safety_guards(lib_module):
    """``sweep_orphans`` must client-side prefix-check and refuse superusers.
    Both guards are independent of the underlying ``list_users_by_prefix``
    filter so a regression in one is caught by the other."""
    import inspect
    src = inspect.getsource(lib_module.sweep_orphans)
    assert "USERNAME_PREFIX" in src and "startswith" in src, (
        "sweep_orphans() lost its client-side prefix check — A13.6 risk"
    )
    assert "is_superuser" in src, (
        "sweep_orphans() lost its is_superuser bypass guard — A13.6 risk"
    )


def test_list_users_by_prefix_refuses_empty(lib_module):
    """An empty prefix would enumerate every user. Calling code must hit the
    explicit empty-prefix guard, not silently return an unfiltered list."""
    from tests.e2e.lib.authentik_admin import AuthentikAdmin, AuthentikAdminError

    # Build a client with a fake URL/token — we never reach the network because
    # the empty-prefix guard fires before any HTTP call.
    admin = AuthentikAdmin(
        base_url="http://127.0.0.1:9999/api/v3",
        token="fake-token-no-network",
    )
    raised = False
    try:
        admin.list_users_by_prefix("")
    except AuthentikAdminError as exc:
        raised = True
        assert "empty prefix" in str(exc).lower()
    assert raised, "list_users_by_prefix accepted empty prefix — A13.6 risk"


def test_static_blueprint_user_distinct():
    """The static blueprint user (``nos-tester``) must NOT match the ephemeral
    prefix. If it did, orphan-sweep would delete the static account on every
    run — disaster."""
    blueprint = REPO_ROOT / "roles" / "pazny.authentik" / "templates" / "blueprints" / "00-admin-groups.yaml.j2"
    src = blueprint.read_text()
    # Static username comes from default.config.yml::nos_tester_username, default 'nos-tester'.
    # Confirm the default is NOT a member of the ephemeral prefix space.
    assert "nos-tester-e2e-" not in src, (
        "static blueprint user collides with ephemeral prefix — orphan-sweep "
        "would delete it on every run"
    )
