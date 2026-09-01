"""Anatomy gate — the five declarations of "how is this reached" must agree.

"How is service X reached, and what gates it" is declared in five places that
nothing compares:

  1. `state/manifest.yml`            — domain_var + port_var ⇒ a router exists
  2. `traefik_auth_modes`            — which middleware attaches
  3. `traefik_skip_ids`              — whether to route at all
  4. the plugin's `authentik:` block — whether a provider exists to attach
  5. `authentik_app_tiers`           — who may pass

REM-144 was what happens when 1 and 2 disagree and the tiebreaker is a comment.
This file is the reconciliation, and writing it immediately surfaced a second,
independent live failure in the OTHER direction — see INV-1 below.

These are the genome's `access` facet expressed against today's storage. When
entities migrate onto `state/genome/entity.schema.json`, this becomes a
regenerate-and-diff instead of a cross-check; until then it is the thing that
makes the split auditable.

CI-safe: pure source scan. No Docker, no network, no live host.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TRAEFIK_VARS = REPO / "roles" / "pazny.traefik" / "vars" / "main.yml"
MANIFEST = REPO / "state" / "manifest.yml"
PLUGINS = REPO / "files" / "anatomy" / "plugins"

# `services.yml.j2` renders `traefik_auth_modes.get(s.id, 'proxy')` — an id with
# no entry is GATED, not ungated. Anything reasoning about this map has to know
# that or it reads absence as "none".
DEFAULT_MODE = "proxy"

# Provider kinds that can satisfy an `authentik@file` middleware.
PROXY_CAPABLE = {"forward_auth", "header_oidc", "proxy"}

# ── KNOWN GAP — these three are DOWN right now ────────────────────────────
#
# Each has `authentik@file` attached at the edge and NO Authentik proxy provider
# for its Host header, so the outpost answers 404 to everyone, authenticated or
# not. Proven live 2026-07-31 by comparison, not inference: uptime.pazny.eu and
# books.pazny.eu (which have providers) return 302 to the Authentik login;
# gis.pazny.eu, mcp-gateway.pazny.eu and smtp-stalwart.pazny.eu return 404 with
# no redirect.
#
# `roles/pazny.traefik/vars/main.yml` warns about exactly this in prose:
#   "auth: proxy here would require the operator to register a matching Authentik
#    proxy provider for the Host header, otherwise the outpost returns 404."
#
# The fix is a per-service DECISION, not a mechanical edit, which is why they are
# pinned rather than patched:
#   * smtp_stalwart — the web admin must be gated: give it an authentik block.
#   * mcp_gateway   — called server-side by Open WebUI; a browser gate cannot
#                     work. Either skip the route (loopback only, like bone and
#                     cortex) or gate=none WITH a justification.
#   * qgis_server   — CLAUDE.md lists QGIS under "No SSO", so `proxy` was never
#                     the intent; gate=none + justification, or no route.
# Publishing a service to the open edge is precisely the decision REM-144 taught
# us not to make in passing, so it stays with the operator.
KNOWN_PROVIDER_GAP = {"qgis_server", "mcp_gateway", "smtp_stalwart"}

# ── ACCEPTED ASYMMETRY — provider exists, edge deliberately does not use it ──
# `authentik.provider_type` says WHAT Authentik object to create; the edge mode
# says WHAT ATTACHES. They are different facts, and these two differ on purpose.
PROVIDER_NOT_EDGE_ATTACHED = {
    "woodpecker": "app-auth via Gitea OAuth; a forward-auth gate would be the documented double-login anti-pattern",
    "onlyoffice": "DocServer is called server-side by Nextcloud/BookStack/Outline under a shared JWT; a browser gate would break the editor iframe",
    # ntfy, 2026-08-08 — and this one is a DEBT, not a design, so it is worded
    # to stay uncomfortable. The edge gate was removed because a push client
    # cannot complete an Authentik browser flow, so no phone could ever
    # subscribe; ntfy now authenticates subscribers itself. The Authentik proxy
    # provider that used to back that gate is therefore unattached.
    #
    # It is not deleted here on purpose: providers are owned by OpenTofu
    # (ADR-0001), so dropping the plugin's authentik block makes `tofu plan`
    # report a DESTROY, and the destroy-guard refuses that outside a supervised
    # apply. Retiring it is a deliberate operator step, not a side effect of a
    # routing change. Until then Authentik holds one provider nothing uses —
    # harmless, untidy, and exactly the kind of thing that becomes permanent if
    # nobody writes down that it is temporary.
    "ntfy": "edge gate removed so a phone can subscribe; ntfy authenticates its own users. "
            "Provider retirement is a supervised tofu apply (destroy-guard), tracked separately",
}


def _vars() -> dict:
    return yaml.safe_load(TRAEFIK_VARS.read_text())


def _routed_ids() -> list[str]:
    manifest = yaml.safe_load(MANIFEST.read_text())
    services = manifest["services"] if isinstance(manifest, dict) else manifest
    skip = set(_vars().get("traefik_skip_ids") or [])
    return [
        s["id"]
        for s in services
        if s.get("domain_var") and s.get("port_var") and s["id"] not in skip
    ]


def _providers() -> dict[str, dict]:
    """slug → the plugin's authentik declaration."""
    out: dict[str, dict] = {}
    for p in sorted(PLUGINS.rglob("plugin.yml")):
        m = yaml.safe_load(p.read_text()) or {}
        a = m.get("authentik") or {}
        if not a:
            continue
        slug = a.get("slug") or m["name"].replace("-base", "")
        out[slug] = {"kind": a.get("provider_type") or a.get("mode"), "plugin": m["name"]}
    return out


def _norm(service_id: str) -> str:
    """manifest/vars use snake_case ids; plugin slugs use kebab. Same service."""
    return service_id.replace("_", "-")


def _gate(service_id: str) -> str:
    return (_vars().get("traefik_auth_modes") or {}).get(service_id, DEFAULT_MODE)


# ── INV-1: a gate with nothing behind it ──────────────────────────────────


def test_every_gated_route_has_a_provider_to_gate_it():
    providers = _providers()
    broken = []
    for sid in _routed_ids():
        if _gate(sid) != "proxy":
            continue
        d = providers.get(_norm(sid))
        if d is None or d["kind"] not in PROXY_CAPABLE:
            broken.append(sid)

    unexpected = sorted(set(broken) - KNOWN_PROVIDER_GAP)
    assert not unexpected, (
        "routed with authentik@file attached but NO Authentik proxy provider for "
        "the Host header. The outpost answers 404 to everyone — the service is "
        f"DOWN, not merely ungated: {unexpected}"
    )

    fixed = sorted(KNOWN_PROVIDER_GAP - set(broken))
    assert not fixed, (
        f"good news, and the list needs editing: {fixed} now has a provider. "
        "Remove it from KNOWN_PROVIDER_GAP so a regression is caught again."
    )


# ── INV-2: a provider nothing attaches ────────────────────────────────────


def test_orphan_providers_are_declared_deliberate():
    """An Authentik provider whose route never attaches it is dead weight, and
    provider churn is a known source of tofu state pain. Deliberate cases are
    fine; undeclared ones are how the estate accumulates them."""
    providers = _providers()
    orphans = []
    for sid in _routed_ids():
        d = providers.get(_norm(sid))
        if d and d["kind"] in PROXY_CAPABLE and _gate(sid) != "proxy":
            orphans.append(sid)

    undeclared = sorted(set(orphans) - set(PROVIDER_NOT_EDGE_ATTACHED))
    assert not undeclared, (
        "these declare a proxy-capable Authentik provider that their edge route "
        f"never attaches: {undeclared}. Either fix the mode or record why in "
        "PROVIDER_NOT_EDGE_ATTACHED."
    )


# ── INV-3: one service, one key ───────────────────────────────────────────


def test_no_service_is_keyed_two_ways():
    """`traefik_auth_modes` uses snake_case; plugin slugs use kebab-case. Four
    services are spelled both ways, and the workaround shipped was to add a
    DUPLICATE alias key (`openwebui` beside `open_webui`, commented "alias
    spelling guard") rather than reconcile them. That is the same disease as the
    RBAC map: a second copy standing in for agreement.

    The grandfathered alias is GONE (2026-09-01): the renderer keys on the
    manifest id, so `openwebui` was never read. No duplicates remain.
    """
    modes = _vars().get("traefik_auth_modes") or {}

    def squash(k: str) -> str:
        # Separator-insensitive on purpose: `open_webui` and `openwebui` differ
        # by a separator that is not there at all, so _norm() (which only swaps
        # `_` for `-`) does not collide them. Squashing is what catches the
        # actual alias hack.
        return k.replace("_", "").replace("-", "")

    by_norm: dict[str, list[str]] = {}
    for k in modes:
        by_norm.setdefault(squash(k), []).append(k)
    dupes = {n: ks for n, ks in by_norm.items() if len(ks) > 1}
    assert not dupes, (
        f"duplicate alias keys are back in traefik_auth_modes: {dupes}. One "
        "service, one key — the renderer reads the manifest id and nothing else."
    )


def test_the_reconciliation_actually_sees_the_estate():
    """A cross-check that resolves nothing passes forever."""
    routed = _routed_ids()
    providers = _providers()
    assert len(routed) >= 40, f"only {len(routed)} routed services — manifest/skip drift?"
    assert len(providers) >= 35, f"only {len(providers)} authentik blocks — glob drift?"
    matched = sum(1 for sid in routed if _norm(sid) in providers)
    assert matched >= 25, (
        f"only {matched} routed services resolve to a plugin declaration — the "
        "normalisation is probably broken, which would make every assertion vacuous"
    )
