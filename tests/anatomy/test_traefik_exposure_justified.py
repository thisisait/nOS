"""Anatomy gate — no routed service is anonymous at the edge without saying why.

REM-144 (CRITICAL, live-confirmed 2026-07-30). Three files each held one third of
the decision "is the Traefik dashboard exposed", and nothing compared them:

  * state/manifest.yml gave the `traefik` entry domain_var + port_var, so
    roles/pazny.traefik/templates/dynamic/services.yml.j2 auto-derived a websecure
    router for it;
  * roles/pazny.traefik/vars/main.yml set `traefik_auth_modes.traefik: none`, so no
    authentik@file middleware attached to that router;
  * the justification for that `none` was an inline comment — "own dashboard
    (LAN-only via 127.0.0.1 bind)" — which had been FALSE since batch-21, because
    the auto-derived router's upstream is the Docker host-gateway. Traefik proxied
    around the very loopback bind the comment cited.

Result: the entire Traefik API was anonymous over HTTPS:443, and
/api/http/middlewares serves rendered `headers.customRequestHeaders` verbatim —
handing any unauthenticated caller both SEC-6 edge-trust tokens, one of which
(X-Face-Edge-Token) was `{{ global_password_prefix }}_pw_face_edge` and therefore
disclosed the prefix every other credential in the estate derives from.

The invariant this pins: a comment is not a justification. If a routed service is
ungated, it says so in a FIELD that a test can read.

CI-safe: pure YAML source scan; no Docker, no live host.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = REPO / "state" / "manifest.yml"
TRAEFIK_VARS = REPO / "roles" / "pazny.traefik" / "vars" / "main.yml"

# services.yml.j2 renders a router only for entries carrying BOTH of these, and
# `traefik_auth_modes.get(s.id, 'proxy')` is what picks the middleware.
DEFAULT_MODE = "proxy"
UNGATED = "none"


def _load():
    manifest = yaml.safe_load(MANIFEST.read_text())
    services = manifest["services"] if isinstance(manifest, dict) else manifest
    tvars = yaml.safe_load(TRAEFIK_VARS.read_text())
    return services, tvars


def _routed_ids(services, skip_ids) -> list[str]:
    """Ids services.yml.j2 will actually emit a router for."""
    return [
        s["id"]
        for s in services
        if s.get("domain_var") and s.get("port_var") and s["id"] not in skip_ids
    ]


def test_sources_parse():
    services, tvars = _load()
    assert services, "state/manifest.yml has no services — path/shape drift?"
    assert "traefik_auth_modes" in tvars, "traefik_auth_modes vanished from vars/main.yml"
    assert "traefik_skip_ids" in tvars, "traefik_skip_ids vanished from vars/main.yml"


def test_default_auth_mode_is_gated():
    """The fall-through must stay `proxy`. A service nobody classified is gated."""
    tpl = (
        REPO / "roles" / "pazny.traefik" / "templates" / "dynamic" / "services.yml.j2"
    ).read_text()
    assert f"traefik_auth_modes.get(s.id, '{DEFAULT_MODE}')" in tpl, (
        "services.yml.j2 no longer defaults unclassified services to "
        f"'{DEFAULT_MODE}' — an unlisted service would render ungated"
    )


def test_every_ungated_route_carries_a_justification():
    services, tvars = _load()
    skip_ids = set(tvars.get("traefik_skip_ids") or [])
    modes = tvars.get("traefik_auth_modes") or {}
    reasons = tvars.get("traefik_auth_none_justification") or {}

    offenders = []
    for sid in _routed_ids(services, skip_ids):
        if modes.get(sid, DEFAULT_MODE) != UNGATED:
            continue
        reason = (reasons.get(sid) or "").strip()
        if len(reason) < 40:
            offenders.append(
                f"{sid}: routed (domain_var + port_var, not in traefik_skip_ids) "
                f"with auth_mode 'none' but no usable justification in "
                f"traefik_auth_none_justification"
            )

    assert not offenders, (
        "Anonymously reachable at the edge with nothing but a comment behind it "
        "(this is REM-144's exact shape):\n  " + "\n  ".join(offenders)
    )


def test_justifications_describe_live_routes_only():
    """Stale reasons rot into false comfort — the same failure one layer up."""
    services, tvars = _load()
    skip_ids = set(tvars.get("traefik_skip_ids") or [])
    modes = tvars.get("traefik_auth_modes") or {}
    reasons = tvars.get("traefik_auth_none_justification") or {}

    live_ungated = {
        sid
        for sid in _routed_ids(services, skip_ids)
        if modes.get(sid, DEFAULT_MODE) == UNGATED
    }
    stale = sorted(set(reasons) - live_ungated)
    assert not stale, (
        "traefik_auth_none_justification explains services that are no longer "
        f"routed-and-ungated: {stale}. Drop them, or the map starts vouching for "
        "decisions nobody is making any more."
    )


def test_traefik_dashboard_is_not_routed():
    """The REM-144 regression test, named so a bisect points straight at it."""
    services, tvars = _load()
    skip_ids = set(tvars.get("traefik_skip_ids") or [])
    assert "traefik" in skip_ids, (
        "`traefik` left traefik_skip_ids. state/manifest.yml still gives it "
        "domain_var + port_var, so services.yml.j2 will auto-derive an edge router "
        "whose upstream is the Docker host-gateway — which proxies around the "
        "127.0.0.1 dashboard bind and re-opens the whole API anonymously over 443. "
        "If this is deliberate, the dashboard needs a real gate first (and note "
        "that /api/http/middlewares serves the edge tokens verbatim)."
    )
