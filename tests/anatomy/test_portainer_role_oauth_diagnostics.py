"""Anatomy gate — role-side Portainer OAuth2 post.yml is diagnosable headless.

The service-side verify (tasks/stacks/authentik_service_post.yml) already fails
LOUD on an unverifiable Portainer SSO (pinned by test_portainer_sso_verify_loud.py).
This gate covers the *role-side* dual-safe replay in roles/pazny.portainer/tasks/
post.yml, which performs the actual PUT /api/settings but only emits debug
summaries. The finding (portainer-sso-unverified): on a JWT-obtain failure the
operator got no root cause, and the verify GET only ran when the PUT returned 200
— so the live AuthenticationMethod was never read back on the failure path.

Pins, source-scan only (no Docker / Authentik / live Portainer):
  - the JWT-status debug surfaces the HTTP status of the auth POST (root-cause:
    401/422 = wrong password, -1 = network, 5xx = Portainer error);
  - the verify GET /api/settings runs whenever a JWT is held — gated on the JWT,
    NOT on the PUT having returned 200 — so AuthMethod is always read back.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
POST = REPO / "roles/pazny.portainer/tasks/post.yml"


def _tasks() -> list[dict]:
    docs = yaml.safe_load(POST.read_text())
    assert isinstance(docs, list), "portainer/tasks/post.yml must be a task list"
    return [t for t in docs if isinstance(t, dict)]


def _task_by_name_contains(needle: str) -> dict:
    for t in _tasks():
        if needle in t.get("name", ""):
            return t
    raise AssertionError(f"no task whose name contains {needle!r} in post.yml")


def test_jwt_status_debug_surfaces_http_status():
    """The auth-token status debug must log the HTTP status code, not just 'FAILED'."""
    task = _task_by_name_contains("OAuth2 auth token status")
    msg = task.get("ansible.builtin.debug", {}).get("msg", "")
    assert "_portainer_auth.status" in msg, (
        "OAuth2 auth-token-status debug must surface _portainer_auth.status so the "
        "operator can root-cause a JWT-obtain failure (401/422/-1/5xx), got:\n" + msg
    )
    # Mention the diagnostic decode so the message is actionable, not a bare code.
    assert "401" in msg or "422" in msg, (
        "the JWT-failure message must decode the status (e.g. 401/422 = wrong "
        "password) so it is actionable headless"
    )


def test_verify_get_runs_on_jwt_not_on_put_success():
    """The /api/settings verify GET must be gated on holding a JWT, not on PUT==200.

    Gating it on _portainer_oauth_put.status==200 left a blind spot: when the PUT
    failed or was skipped we never read the LIVE AuthenticationMethod.
    """
    verify = None
    for t in _tasks():
        uri = t.get("ansible.builtin.uri", {})
        if (
            "Verify OAuth2" in t.get("name", "")
            and uri.get("method") == "GET"
            and "/api/settings" in uri.get("url", "")
        ):
            verify = t
            break
    assert verify is not None, "no Portainer /api/settings verify GET task found"

    cond = verify.get("when")
    cond_text = " ".join(cond) if isinstance(cond, list) else str(cond)
    assert "_portainer_auth.json.jwt" in cond_text and "length" in cond_text, (
        "verify GET must be gated on the admin JWT being present, got "
        f"when={cond_text!r}"
    )
    assert "_portainer_oauth_put.status" not in cond_text, (
        "verify GET must NOT be gated on the PUT returning 200 — that blind-spots "
        "the live AuthMethod when the PUT fails/skips, got "
        f"when={cond_text!r}"
    )
