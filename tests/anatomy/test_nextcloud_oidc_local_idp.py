"""Anatomy gate — Nextcloud OIDC reaches the LOCAL IdP (allow_local_remote_servers).

Nextcloud's user_oidc fetches the discovery doc with NC's own IClientService, which
enforces the `allow_local_remote_servers` SSRF guard. The Authentik discovery host
(auth.<tld>) resolves — via the container's extra_hosts:host-gateway — to the
PRIVATE host-gateway IP, so with the default (false) NC BLOCKS the fetch and the
browser login dies with "Could not reach the OpenID Connect provider" (live
root-cause 2026-06-15). A raw curl from the container succeeds and MASKS it — only
NC's own client enforces the guard, which is why earlier probes missed it.

Both OIDC-setup paths must enable allow_local_remote_servers BEFORE registering the
provider, on every tenant (the private-gateway resolution happens on public LE
tenants too — it is the extra_hosts routing, not the cert).
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
POST = (REPO / "tasks/stacks/authentik_service_post.yml").read_text(encoding="utf-8")
HOOK = (REPO / "files/anatomy/plugins/nextcloud-base/hooks/post_compose.yml").read_text(encoding="utf-8")


def test_live_path_sets_allow_local_remote_servers():
    assert "allow_local_remote_servers --value=true" in POST, \
        "authentik_service_post.yml must enable allow_local_remote_servers for NC OIDC discovery"
    # ...before registering the provider (so the discovery fetch during setup works).
    set_at = POST.find("allow_local_remote_servers")
    reg_at = POST.find("Register OIDC provider")
    assert set_at != -1 and reg_at != -1 and set_at < reg_at, \
        "allow_local_remote_servers must be set BEFORE the OIDC provider registration"


def test_plugin_hook_mirrors_the_setting():
    # The declarative plugin-loader path must carry the same step (it is a real
    # OIDC-setup path, replayed via replay_api_calls).
    assert "allow_local_remote_servers --value=true" in HOOK, \
        "nextcloud-base hook must mirror allow_local_remote_servers"
    set_at = HOOK.find("allow_local_remote_servers")
    reg_at = HOOK.find("register_authentik_provider")
    assert set_at != -1 and reg_at != -1 and set_at < reg_at, \
        "the hook must set allow_local_remote_servers before register_authentik_provider"


def test_not_gated_on_local_tenant_only():
    # The private-gateway resolution happens on PUBLIC tenants too (extra_hosts),
    # so the setting must NOT be guarded behind tenant_domain_is_local.
    seg = POST[POST.find("Allow server-side requests to the local IdP"):POST.find("Register OIDC provider")]
    assert "tenant_domain_is_local" not in seg, \
        "allow_local_remote_servers is needed on public tenants too — do not gate it on local-only"
