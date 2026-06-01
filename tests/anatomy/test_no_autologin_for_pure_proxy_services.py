"""Anatomy gate — pure-proxy services declare NO autologin block.

sso-autologin-plan.md §"forward_auth (17 služeb)" + §"Testy / gates":

  > Žádný autologin flag se forward_auth službám nedává
  > (gate `test_no_autologin_for_pure_proxy_services`).
  > code-server/calibre-web/influxdb/… (forward_auth) NEMAJÍ autologin pole.

forward_auth gates ACCESS to the route (WHO), not the service identity
(WHAT) — the shared `.<tld>` session cookie + embedded outpost already
makes the Authentik session the auth. header_oidc (firefly) auto-logs-in
at the proxy layer via injected REMOTE_USER headers, not a service-side
env var. Stacking an autologin force-OIDC block on either would be
double-protection (double-login UX, zero security gain). The 17
forward_auth plugins + the single header_oidc (firefly) must carry no
autologin field.

This is the complement of test_autologin_only_for_native_oidc_services:
that one says "autologin ⇒ native_oidc"; this one says "non-native_oidc
⇒ no autologin" from the proxy side. The mode set is derived live so it
tracks the real plugin tree (today: 17 forward_auth + firefly header_oidc).

Batch 0: no autologin blocks anywhere → vacuous pass.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS = REPO / "files" / "anatomy" / "plugins"

PURE_PROXY_MODES = {"forward_auth", "header_oidc"}


def _authentik_block(yaml_path: pathlib.Path) -> dict | None:
    data = yaml.safe_load(yaml_path.read_text())
    a = (data or {}).get("authentik")
    return a if isinstance(a, dict) else None


def test_no_autologin_for_pure_proxy_services():
    offenders: list[tuple[str, str]] = []
    proxy_count = 0
    for p in sorted(PLUGINS.glob("*/plugin.yml")):
        a = _authentik_block(p)
        if not a:
            continue
        mode = a.get("mode") or a.get("provider_type")
        if mode not in PURE_PROXY_MODES:
            continue
        proxy_count += 1
        if "autologin" in a:
            offenders.append((p.parent.name, str(mode)))
    assert not offenders, (
        "pure-proxy (forward_auth / header_oidc) plugins must NOT declare an "
        f"autologin block (anti-pattern double-protection): {offenders}"
    )
    # Sanity: the proxy set is non-empty (guards against the glob silently
    # matching nothing and the gate passing for the wrong reason).
    assert proxy_count >= 1, (
        "expected at least one forward_auth/header_oidc plugin; the glob "
        "matched none — harness is mis-pointed"
    )
