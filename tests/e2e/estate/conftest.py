"""Session fixtures for the config-generated estate journeys.

One ephemeral tester per RBAC tier (A13.6 identities: provisioned through the
Authentik admin API, torn down in `finally`), each logged in once through the
flow executor. The plan comes from tools/e2e-plan.py — the manifests rendered
against the resolved config — so the parametrised journeys are exactly the
services this estate runs.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tests/e2e"))
sys.path.insert(0, str(REPO / "tools"))
from nos_identity import is_local_domain  # noqa: E402  the one local-TLD list

TIERS = {1: "provider", 2: "manager", 3: "user", 4: "guest"}

# ── verdicts are written down, a reader reads them back ─────────────────────
# One JSON line per probe, the shape tools/nos-smoke.py uses for ~/.nos/events;
# tools/e2e-status.py reads the last run back. NOS_E2E_RESULTS="" turns it off.
RUN_ID = "e2e_" + datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
_RBAC_ID = re.compile(r"^[^:]+-t\d+:(.+?)-t\d+$")   # alice-t1:nextcloud-t3


def _results_path() -> Path | None:
    p = os.environ.get("NOS_E2E_RESULTS")
    if p == "":
        return None
    return Path(p) if p else Path.home() / ".nos" / "e2e" / "results.jsonl"


def _service(nodeid: str) -> str | None:
    """jellyfin | grafana:probe | alice-t1:nextcloud-t3 → the service slug."""
    m = re.search(r"\[(.+)\]$", nodeid)
    if not m:
        return None
    pid = m.group(1)
    if (r := _RBAC_ID.match(pid)):
        return r.group(1)
    return pid.split(":")[0]


def pytest_runtest_logreport(report) -> None:
    if report.when != "call" and report.outcome == "passed":
        return                      # a green setup/teardown is not a verdict
    path = _results_path()
    if path is None:
        return
    row = {
        "ts": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": RUN_ID, "type": "e2e_result",
        "nodeid": report.nodeid, "outcome": report.outcome,
        "duration_ms": int(report.duration * 1000),
        "service": _service(report.nodeid),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _plan_module():
    spec = importlib.util.spec_from_file_location("e2e_plan", REPO / "tools/e2e-plan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_plan() -> list[dict]:
    return _plan_module().plan()


def load_identities() -> list[dict]:
    """nos_identities resolved, plus the synthetic ones while nos_test_users_enabled."""
    return _plan_module().identities()


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
    return not is_local_domain(auth_host)


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
                made[tier] = provision_tester(TIERS[tier], persistent=True)
            except Exception as exc:  # noqa: BLE001 — no Authentik admin path = cannot run
                failed[tier] = f"cannot provision a tier-{tier} tester: {exc}"
                pytest.skip(failed[tier])
            ident = made[tier]
            sessions[tier] = login_session(ident.username, ident.password,
                                           authentik_domain=auth_host, ignore_tls=not verify_tls)
        return sessions[tier]

    get.username = lambda tier: getattr(made.get(tier), "username", None)
    try:
        yield get
    finally:
        for ident in made.values():
            teardown_tester(ident)
