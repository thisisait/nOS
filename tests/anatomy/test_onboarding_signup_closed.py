"""Anatomy gate — public self-signup is closed; onboarding is pure-SSO +
fully-provisioned (operator doctrine, 2026-05-28).

The operator hit: first-run admin-registration pages were publicly reachable
(Open-WebUI's /auth/signup made the FIRST visitor admin; Gitea's local register
form was open). Doctrine: no login without Authentik, AND a blank run / new HW
needs ZERO manual registration (full provisioned). So native-OIDC services must
disable public LOCAL signup while keeping OIDC auto-onboarding + an
auto-provisioned admin.

This gate pins the closures + guards the already-safe services from regressing.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_open_webui_local_signup_off_and_admin_db_seeded():
    """Open-WebUI: ENABLE_SIGNUP must default OFF (the public /auth/signup
    first-admin race), and post.yml must provision the admin by DB-seed — NOT
    by POSTing the public /auth/signup endpoint (which 404s with signup off).
    OIDC merge-by-email makes the seeded admin the SSO admin on first login."""
    compose = (REPO / "roles/pazny.open_webui/templates/compose.yml.j2").read_text()
    assert "openwebui_enable_signup | default(false)" in compose, "local signup must default OFF"
    assert "openwebui_enable_signup | default(true)" not in compose, "ENABLE_SIGNUP must not default true"
    post = (REPO / "roles/pazny.open_webui/tasks/post.yml").read_text()
    assert "auth/signup" not in post, "must not bootstrap via the public signup endpoint"
    assert "INSERT INTO user" in post and "INSERT INTO auth" in post, "admin must be DB-seeded"
    assert "OAUTH_MERGE_ACCOUNTS_BY_EMAIL" in (
        REPO / "files/anatomy/plugins/open-webui-base/templates/open-webui-base.compose.yml.j2"
    ).read_text(), "OIDC merge-by-email links the seeded admin to the Authentik login"


def test_gitea_external_only_registration():
    """Gitea: the local self-registration form must be off, but OIDC first-login
    auto-create must stay on (DISABLE_REGISTRATION=true would block OIDC too).
    ALLOW_ONLY_EXTERNAL_REGISTRATION=true is the external-only gate."""
    compose = (REPO / "roles/pazny.gitea/templates/compose.yml.j2").read_text()
    assert "ALLOW_ONLY_EXTERNAL_REGISTRATION" in compose
    assert "gitea_allow_only_external_registration: true" in (REPO / "default.config.yml").read_text()


def test_already_safe_services_stay_closed():
    """Regression guard for services the audit confirmed already-safe — keep
    public signup closed so a future edit can't silently reopen it."""
    hedgedoc = (REPO / "roles/pazny.hedgedoc/templates/compose.yml.j2").read_text()
    assert 'CMD_ALLOW_EMAIL_REGISTER: "false"' in hedgedoc, "HedgeDoc email register must stay off"
    vaultwarden = (REPO / "roles/pazny.vaultwarden/templates/compose.yml.j2").read_text()
    assert "vaultwarden_signups_allowed | default(false)" in vaultwarden, "Vaultwarden signups default off"
    miniflux = (REPO / "roles/pazny.miniflux/templates/compose.yml.j2").read_text()
    assert 'CREATE_ADMIN: "1"' in miniflux, "Miniflux admin must be auto-provisioned (no manual signup)"
