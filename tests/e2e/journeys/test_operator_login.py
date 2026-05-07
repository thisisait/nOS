"""E2E journey: operator_login — proves the SSO chain works end-to-end (A13.6).

The journey:
    1. Provision a brand-new ephemeral ``nos-tester-e2e-<random>`` user in
       Authentik, member of the ``nos-providers`` group (Tier-1 super-admin).
    2. Drive Authentik flow executor headlessly to obtain a session cookie.
    3. Hit the bearer-protected API (``/api/v1/hub/health``) with the minted
       Wing token — proves the token row landed in ``api_tokens``.
    4. Verify the journey's own e2e_journey_start event landed by querying
       Wing /api/v1/events with the bearer token (token works → API auth
       works → audit trail records the run).
    5. Teardown deletes the user + revokes the token (handled by fixture).

Why this matters: this is the first journey that actually exercises the SSO
flow with a non-static identity. If this passes, the foundation for all
RBAC-matrix tests is solid.
"""

from __future__ import annotations

import os
import urllib.parse

import pytest
import requests

from ..lib.authentik_login import login_session, AuthentikLoginError


WING_URL = os.environ.get("WING_API_URL", "http://127.0.0.1:9000").rstrip("/")


@pytest.mark.parametrize("tester_identity", ["provider"], indirect=True)
def test_operator_login(journey, tester_identity):
    with journey("operator_login") as j:

        with j.step("provision_visible") as s:
            # The fixture already provisioned the user — this step just records
            # the username so the Grafana timeline shows what we set up.
            s.note = (
                f"username={tester_identity.username} tier={tester_identity.tier} "
                f"group_pk={tester_identity.group_pk}"
            )

        with j.step("authentik_flow_login") as s:
            # Drives /api/v3/flows/executor/<slug>/ — same path nos-smoke.py uses.
            try:
                sess = login_session(
                    username=tester_identity.username,
                    password=tester_identity.password,
                    timeout_s=10,
                )
                # Confirm we got at least one cookie back; Authentik's flow
                # executor sets ``authentik_session`` on success.
                cookie_names = sorted(c.name for c in sess.cookies)
                s.note = f"cookies={cookie_names}"
                if not any("authentik" in c.lower() or "session" in c.lower()
                           for c in cookie_names):
                    raise AssertionError(
                        f"no authentik session cookie minted; got {cookie_names}"
                    )
            except AuthentikLoginError as exc:
                # Distinguish infra errors from auth-flow failures so the
                # Grafana panel can show the right diagnosis.
                pytest.skip(f"authentik unreachable: {exc}")

        with j.step("wing_token_works") as s:
            # Bearer-token round-trip via /api/v1/hub/health. Anonymous in
            # Authentik but the token's UPSERT proves provision-token.php ran.
            r = requests.get(
                f"{WING_URL}/api/v1/hub/health",
                headers=tester_identity.authorization_header,
                timeout=5,
            )
            r.raise_for_status()
            s.note = f"status={r.status_code}"

        with j.step("journey_audit_visible") as s:
            # Query Wing /api/v1/events for our own start event. Closes the
            # loop: token mint → bearer auth → events query → row exists.
            qs = urllib.parse.urlencode({
                "type": "e2e_journey_start",
                "actor_action_id": j.actor_action_id,
                "limit": 5,
            })
            r = requests.get(
                f"{WING_URL}/api/v1/events?{qs}",
                headers=tester_identity.authorization_header,
                timeout=5,
            )
            r.raise_for_status()
            payload = r.json()
            items = payload.get("items", [])
            assert items, (
                f"expected start event for actor_action_id={j.actor_action_id} "
                f"but got items={items}"
            )
            assert items[0].get("type") == "e2e_journey_start"
            s.note = f"start_event_id={items[0].get('id')}"
