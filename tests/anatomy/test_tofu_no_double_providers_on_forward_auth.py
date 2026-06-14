"""ADR-0001 Phase 1 — data-layer gate against the OAuth2/Proxy MTI cascade.

The Terraform module already makes a double-provider impossible by construction
(`count = is_oidc ? 1 : 0` XOR `count = is_proxy ? 1 : 0`, pinned by
test_tofu_authentik_conformance.test_module_never_creates_oauth2_for_forward_auth).

This gate pins the layer ABOVE it: the generated service registry
(state/tofu-authentik-services.yml) and the generator that writes it. A
forward_auth / header_oidc service is a PROXY-provider service — it must carry
NO oauth2 client fields (client_secret / redirect_uris) in its registry row.

Why it matters: the infisical incident (2026-06-02, plugin.yml:38 forward_auth)
was an orphan OAuth2Provider sharing the ProxyProvider's base Provider row via
Authentik's multi-table inheritance — deleting one cascaded the other. Keeping
oauth2 client fields off non-native_oidc rows makes the data layer explicit:
"forward_auth services have no oauth2 client fields by design, not by accident
of the module's count gates."
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
REGISTRY = REPO / "state" / "tofu-authentik-services.yml"
GENERATOR = REPO / "tools" / "tofu-authentik-gen-registry.py"

OAUTH2_CLIENT_FIELDS = ("client_secret", "redirect_uris")


def _services() -> list[dict]:
    data = yaml.safe_load(REGISTRY.read_text()) or {}
    return data.get("tofu_authentik_services", [])


def test_infisical_is_forward_auth_with_no_oauth2_fields():
    """The triggering service: infisical is forward_auth and must carry no
    oauth2 client fields in the registry (else the MTI orphan recurs)."""
    svcs = _services()
    inf = next((s for s in svcs if s.get("slug") == "infisical"), None)
    assert inf is not None, "infisical missing from the tofu registry"
    assert inf.get("mode") == "forward_auth", \
        f"infisical mode drifted to {inf.get('mode')!r} — expected forward_auth"
    for f in OAUTH2_CLIENT_FIELDS:
        assert f not in inf, \
            f"infisical (forward_auth) carries oauth2 field {f!r} — MTI cascade risk"


def test_no_proxy_service_carries_oauth2_client_fields():
    """Registry-wide invariant: ONLY native_oidc rows may carry oauth2 client
    fields. Any forward_auth / header_oidc row with one is a double-provider
    seed (the data-layer half of the MTI cascade)."""
    offenders = []
    for s in _services():
        if s.get("mode") == "native_oidc":
            continue
        for f in OAUTH2_CLIENT_FIELDS:
            if f in s:
                offenders.append((s.get("slug"), f))
    assert not offenders, \
        f"non-native_oidc rows carrying oauth2 client fields: {offenders}"


def test_generator_suppresses_oauth2_fields_for_non_native_oidc():
    """Structural pin on the generator: the oauth2 client fields are emitted
    strictly inside the `mode == "native_oidc"` branch. A regeneration after a
    hand-edit that unconditionally adds them would re-seed the cascade — this
    keeps the suppression load-bearing, not incidental."""
    src = GENERATOR.read_text()
    assert 'if mode == "native_oidc":' in src, \
        "the native_oidc guard around oauth2 client fields vanished"
    for f in OAUTH2_CLIENT_FIELDS:
        # the only place each oauth2 client field is ASSIGNED into the entry
        assigns = [ln for ln in src.splitlines()
                   if f'entry["{f}"]' in ln]
        assert assigns, f"generator no longer emits {f} at all"
        # and they must sit under the native_oidc guard (same indent block):
        guard_idx = src.index('if mode == "native_oidc":')
        for ln in assigns:
            assert src.index(ln) > guard_idx, \
                f'entry["{f}"] assigned outside the native_oidc guard'
