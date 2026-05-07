"""E2E journey: rbac_admin — RBAC matrix on /admin (A13.6).

Parametrized over all four RBAC tiers. ``/admin`` requires ``nos-providers``
membership (per ``AdminPresenter::REQUIRED_GROUP``); every other tier should
land 403 in Wing's RBAC guard.

This is the first **abstract** RBAC test — the same shape generalizes to any
future presenter that calls ``requireSuperAdmin()`` or ``requireGroup(X)``.

Forward-auth simulation note
============================

Wing's RBAC guard reads ``X-Authentik-Username`` + ``X-Authentik-Groups`` from
the incoming request. In production those are stamped by the Traefik
``forwardAuth`` middleware after Authentik validates the session cookie.

For this journey we pass the headers DIRECTLY to Wing on loopback (port 9000).
That tests the **RBAC guard logic** without requiring Traefik to be online.
The headers we send carry only the tester's actual group (``nos-<tier>s``),
faithfully simulating what the outpost would forward for that user.

A separate journey (``test_operator_login``) exercises the FULL SSO chain
including Traefik forward-auth — together they cover both halves.
"""

from __future__ import annotations

import os

import pytest
import requests


WING_URL = os.environ.get("WING_API_URL", "http://127.0.0.1:9000").rstrip("/")

# tier → (group sent in header, expected status on /admin)
_RBAC_MATRIX = [
    ("provider", "nos-providers", 200),
    ("manager",  "nos-managers",  403),
    ("user",     "nos-users",     403),
    ("guest",    "nos-guests",    403),
]


@pytest.mark.parametrize(
    "tester_identity,group_name,expected_status",
    [(tier, group, status) for tier, group, status in _RBAC_MATRIX],
    indirect=["tester_identity"],
    ids=[t[0] for t in _RBAC_MATRIX],
)
def test_admin_rbac(journey, tester_identity, group_name, expected_status):
    """For each RBAC tier: provision an ephemeral user in that group, hit
    /admin with the simulated forward-auth headers, assert the expected
    allow/deny status.
    """
    with journey(f"rbac_admin/{tester_identity.tier}") as j:

        with j.step("identity_in_correct_group") as s:
            assert tester_identity.group_name == group_name, (
                f"identity provisioned with wrong group: "
                f"got {tester_identity.group_name}, expected {group_name}"
            )
            s.note = f"username={tester_identity.username} group={group_name}"

        with j.step("hit_admin_with_forward_auth_headers") as s:
            # Simulate exactly what the Authentik proxy outpost forwards.
            headers = {
                "X-Authentik-Username": tester_identity.username,
                "X-Authentik-Email": tester_identity.email,
                "X-Authentik-Groups": group_name,
                "X-Authentik-Uid": str(tester_identity.user_pk),
                "X-Authentik-Name": f"E2E Tester ({tester_identity.tier})",
            }
            r = requests.get(
                f"{WING_URL}/admin",
                headers=headers,
                timeout=5,
                allow_redirects=False,
            )
            s.note = f"status={r.status_code} expected={expected_status}"
            assert r.status_code == expected_status, (
                f"tier={tester_identity.tier} group={group_name}: "
                f"got {r.status_code}, expected {expected_status}"
            )

        with j.step("non_provider_cannot_halt") as s:
            # Bonus assertion: non-providers must also be denied on the halt
            # action (which is the actual super-admin operation, not just the
            # /admin landing page). Provider gets a redirect after the action;
            # everyone else gets 403 in startup() before the action runs.
            #
            # We don't actually want to halt the platform during a test, so
            # this step asserts the GUARD works even if the body is mid-issue.
            # For provider tier we just hit the page (not the verb) and check
            # super-admin rendering.
            if tester_identity.tier == "provider":
                # Skip the halt verb itself — we don't want to halt during CI;
                # the 200 on /admin already proved the guard accepts us.
                s.note = "skipped halt verb for provider tier (would halt platform)"
                return
            headers = {
                "X-Authentik-Username": tester_identity.username,
                "X-Authentik-Groups": group_name,
            }
            r = requests.get(
                f"{WING_URL}/admin/halt",
                headers=headers,
                timeout=5,
                allow_redirects=False,
            )
            s.note = f"halt_status={r.status_code}"
            assert r.status_code == 403, (
                f"non-provider tier {tester_identity.tier} should get 403 on "
                f"/admin/halt; got {r.status_code}"
            )
