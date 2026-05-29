"""Anatomy gate — app-to-app auto-wiring (Phase 2/4, 2026-05-29).

Declarative service↔service integrations that build on the Auth/SSO/RBAC base.
"""
from __future__ import annotations
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_nextcloud_onlyoffice_wiring():
    """P2a: Nextcloud auto-connects to the OnlyOffice document server with the
    shared JWT secret — no manual 'connect to document server' step. Gated on
    both services installed."""
    post = (REPO / "roles/pazny.nextcloud/tasks/post.yml").read_text()
    assert "app:install onlyoffice" in post, "must enable the OnlyOffice connector app"
    assert "onlyoffice DocumentServerUrl" in post, "must point at the document server"
    assert "onlyoffice jwt_secret" in post and "onlyoffice_jwt_secret" in post, \
        "must set the shared JWT secret (same as OnlyOffice JWT_SECRET env)"
    assert "install_onlyoffice" in post, "wiring must be gated on install_onlyoffice"
