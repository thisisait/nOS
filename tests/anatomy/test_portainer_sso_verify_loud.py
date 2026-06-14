"""Anatomy gate — Portainer OAuth2 verify in authentik_service_post.yml is LOUD.

The service-side SSO post-setup used to "verify" Portainer OAuth2 by GETting
``/api/system/status`` (a liveness probe) with ``failed_when: false`` and emitting
only a debug message — so a real OAuth2 misconfig exited 0 while Portainer's local
login form still worked, hiding a dead SSO (the Nextcloud user_oidc silent-failure
class, root-caused 2026-06-13).

This gate pins the loud verify shape in tasks/stacks/authentik_service_post.yml:
  - the verify task GETs ``/api/settings`` (carries AuthenticationMethod), not
    ``/api/system/status``;
  - it authenticates with a Bearer JWT;
  - its ``failed_when`` references ``AuthenticationMethod`` and is NOT a bare
    ``false`` (i.e. the playbook actually fails when SSO is not method 3).

Source-scan only — no Docker / Authentik / live Portainer.
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


def _portainer_verify_task() -> dict:
    """The AuthenticationMethod assertion task: a Portainer GET of /api/settings."""
    for t in _tasks():
        name = t.get("name", "")
        uri = t.get("ansible.builtin.uri", {})
        if "Portainer" in name and uri.get("method") == "GET" and "/api/settings" in uri.get("url", ""):
            return t
    raise AssertionError("no Portainer /api/settings verify task found in authentik_service_post.yml")


def test_verify_hits_settings_not_status():
    uri = _portainer_verify_task().get("ansible.builtin.uri", {})
    url = uri.get("url", "")
    assert "/api/settings" in url, f"Portainer verify must GET /api/settings, got {url!r}"
    assert "/api/system/status" not in url, (
        "Portainer verify must NOT use the /api/system/status liveness probe — "
        "it never carries AuthenticationMethod"
    )


def test_verify_is_jwt_authenticated():
    uri = _portainer_verify_task().get("ansible.builtin.uri", {})
    auth = (uri.get("headers") or {}).get("Authorization", "")
    assert "Bearer" in auth and "jwt" in auth, (
        f"Portainer verify must send a Bearer JWT header, got {auth!r}"
    )


def test_verify_fails_loud_on_wrong_auth_method():
    task = _portainer_verify_task()
    fw = task.get("failed_when")
    assert fw is not None, "Portainer verify must declare failed_when (not soft)"
    fw_text = " ".join(fw) if isinstance(fw, list) else str(fw)
    norm = fw_text.replace(" ", "").lower()
    assert norm not in ("false", "no"), (
        "Portainer verify failed_when must not be a bare false — that is the soft bug"
    )
    assert "AuthenticationMethod" in fw_text and "3" in fw_text, (
        "Portainer verify failed_when must assert AuthenticationMethod == 3, "
        f"got {fw_text!r}"
    )


def test_jwt_acquisition_failure_fails_loud():
    """A failed admin JWT means SSO is UNCONFIRMED — must fail, not silently skip."""
    fail_tasks = [
        t for t in _tasks()
        if "Portainer" in t.get("name", "") and "ansible.builtin.fail" in t
    ]
    assert fail_tasks, (
        "must have a Portainer fail task guarding the empty-JWT (unverifiable) path"
    )
    cond = fail_tasks[0].get("when")
    cond_text = " ".join(cond) if isinstance(cond, list) else str(cond)
    assert "jwt" in cond_text and "length" in cond_text and "0" in cond_text, (
        "the Portainer fail guard must trip when the admin JWT is empty, "
        f"got when={cond_text!r}"
    )


def test_no_soft_system_status_verify_remains():
    # No uri task may use the /api/system/status liveness probe as a Portainer
    # SSO verify (a comment mentioning it for context is fine; a live url is not).
    for t in _tasks():
        uri = t.get("ansible.builtin.uri", {})
        url = uri.get("url", "")
        if "Portainer" in t.get("name", ""):
            assert "/api/system/status" not in url, (
                f"task {t.get('name')!r} still uses the soft /api/system/status verify"
            )
