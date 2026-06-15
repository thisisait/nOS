"""Anatomy gate — Portainer OAuth2 verify is LOUD and PASSWORD-INDEPENDENT.

History: the verify first used ``/api/system/status`` (a liveness probe) with
``failed_when: false`` — a dead SSO exited 0 (silent-failure class, 2026-06-13).
That was replaced by a JWT verify (POST /api/auth → GET /api/settings). But once
OAuth2 is active the internal admin login can 422, so the JWT was unobtainable and
the verify FALSE-FAILED the converge even though SSO was active (live 2026-06-15:
/api/auth=422 yet /api/settings/public AuthenticationMethod=3). Coupling SSO
verification to the admin password is the wrong invariant.

Robust shape pinned here: the verify reads the UNAUTHENTICATED
``/api/settings/public`` (which carries AuthenticationMethod) and fails LOUD only
when it is not 3 — never on a password it cannot use, and never a silent
liveness probe.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
POST = REPO / "tasks/stacks/authentik_service_post.yml"


def _tasks() -> list[dict]:
    docs = yaml.safe_load(POST.read_text())
    assert isinstance(docs, list), "authentik_service_post.yml must be a task list"
    return [t for t in docs if isinstance(t, dict)]


def _portainer_read_task() -> dict:
    """The AuthenticationMethod read: a Portainer GET of /api/settings/public."""
    for t in _tasks():
        uri = t.get("ansible.builtin.uri", {})
        if "Portainer" in t.get("name", "") and uri.get("method") == "GET" \
                and "/api/settings/public" in uri.get("url", ""):
            return t
    raise AssertionError("no Portainer /api/settings/public read task found")


def test_verify_reads_public_settings():
    # The check must read the public (unauthenticated) settings endpoint, which is
    # the password-independent source of AuthenticationMethod.
    _portainer_read_task()  # raises if absent


def test_verify_is_password_independent():
    # The read task must NOT carry an Authorization/Bearer header and must not be a
    # POST /api/auth password login — that coupling is exactly what false-failed it.
    read = _portainer_read_task()
    uri = read.get("ansible.builtin.uri", {})
    headers = uri.get("headers") or {}
    assert "Authorization" not in headers, \
        "the public-settings read must not send an Authorization header (password-independent)"
    # No Portainer verify task may obtain a JWT via the admin password anymore.
    for t in _tasks():
        uri = t.get("ansible.builtin.uri", {})
        if "Portainer" in t.get("name", "") and "/api/auth" in uri.get("url", ""):
            raise AssertionError(
                f"task {t.get('name')!r} still logs in with the admin password to verify SSO — "
                "the verify must be password-independent (/api/settings/public)"
            )


def test_fails_loud_when_sso_not_active():
    # A dedicated fail task must trip when AuthenticationMethod != 3 (genuine dead
    # SSO), so the silent-failure class can't return.
    fails = [t for t in _tasks()
             if "Portainer" in t.get("name", "") and "ansible.builtin.fail" in t]
    assert fails, "must have a Portainer fail task for the not-active SSO case"
    cond = fails[0].get("when")
    cond_text = " ".join(cond) if isinstance(cond, list) else str(cond)
    assert "AuthenticationMethod" in cond_text and "!= 3" in cond_text, \
        f"the fail guard must trip on AuthenticationMethod != 3, got when={cond_text!r}"


def test_no_soft_system_status_verify_remains():
    for t in _tasks():
        uri = t.get("ansible.builtin.uri", {})
        if "Portainer" in t.get("name", ""):
            assert "/api/system/status" not in uri.get("url", ""), \
                f"task {t.get('name')!r} still uses the soft /api/system/status verify"
