"""Session fixtures for the config-generated estate journeys.

One ephemeral tester per RBAC tier (A13.6 identities: provisioned through the
Authentik admin API, torn down in `finally`), each logged in once through the
flow executor. The plan comes from tools/e2e-plan.py — the manifests rendered
against the resolved config — so the parametrised journeys are exactly the
services this estate runs.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tests/e2e"))

TIERS = {1: "provider", 2: "manager", 3: "user", 4: "guest"}


def load_plan() -> list[dict]:
    spec = importlib.util.spec_from_file_location("e2e_plan", REPO / "tools/e2e-plan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.plan()


@pytest.fixture(scope="session")
def auth_host() -> str:
    spec = importlib.util.spec_from_file_location("nos_smoke", REPO / "tools/nos-smoke.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    v = smoke.load_vars()
    os.environ.setdefault("TENANT_DOMAIN", str(v.get("tenant_domain", "dev.local")))
    return os.environ.get("AUTHENTIK_DOMAIN") or f"auth.{v.get('tenant_domain', 'dev.local')}"


@pytest.fixture(scope="session")
def verify_tls(auth_host) -> bool:
    return not auth_host.endswith((".local", ".lan", ".test"))


@pytest.fixture(scope="session")
def testers(auth_host, verify_tls):
    """tier number → logged-in requests.Session, provisioned lazily."""
    from lib.tester_identity import provision_tester, teardown_tester
    from lib.authentik_login import login_session

    made: dict[int, object] = {}
    sessions: dict[int, object] = {}
    failed: dict[int, str] = {}      # one attempt per tier, never one per test

    def get(tier: int):
        if tier in failed:
            pytest.skip(failed[tier])
        if tier not in sessions:
            try:
                made[tier] = provision_tester(TIERS[tier])
            except Exception as exc:  # noqa: BLE001 — no Authentik admin path = cannot run
                failed[tier] = f"cannot provision a tier-{tier} tester: {exc}"
                pytest.skip(failed[tier])
            ident = made[tier]
            sessions[tier] = login_session(ident.username, ident.password,
                                           authentik_domain=auth_host, ignore_tls=not verify_tls)
        return sessions[tier]

    try:
        yield get
    finally:
        for ident in made.values():
            teardown_tester(ident)
