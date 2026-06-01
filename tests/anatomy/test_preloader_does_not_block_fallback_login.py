"""Anatomy gate — the preloader never blocks the fallback / normal login.

sso-autologin-plan.md §"Custom preloader" + §"Testy / gates":

  > `test_preloader_does_not_block_fallback_login` — i s preloaderem on je
  > local-login fallback dosažitelný.

The preloader is a UX polish layer for REPEAT logins (masks ~100-200ms). It
must NEVER trap a user or remove a path to the normal flow:

  - `?skip_splash=1` always bypasses (presenter + splash links).
  - The presenter renders the splash ONLY when the flag is on; otherwise it
    bounces to the normal /hub. No hard block.
  - On prompt=none failure / timeout the warmer routes to the NORMAL flow
    (the fallback URL), not a dead end.
  - The redirect-host whitelist is per-service ONLY (`<svc>.<tld>` +
    `auth.<tld>`) — open-redirect defence, but it never disables the local
    dashboard fallback (same-origin /hub is always reachable).

STATIC gate over the Wing BATCH 5 source.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
PRESENTER = WING / "app" / "Presenters" / "HubPresenter.php"
SPLASH = WING / "app" / "Templates" / "Hub" / "splash.latte"
WARMER = WING / "www" / "assets" / "hub-session-warmer.js"


def test_splash_offers_manual_escape_to_dashboard():
    """The splash template always carries a manual 'skip to dashboard' link so
    a stuck user reaches the normal flow without JS."""
    splash = SPLASH.read_text()
    assert "/hub?skip_splash=1" in splash, \
        "splash has no manual skip-to-dashboard link (would trap the user)"


def test_warmer_failure_routes_to_normal_flow_not_dead_end():
    """On prompt=none failure the warmer must navigate to the fallback URL
    (the normal flow), never abandon the navigation."""
    js = WARMER.read_text()
    assert "goToNormalFlow" in js, "no normal-flow fallback function"
    # The fallback function performs a real navigation (not a no-op).
    assert "window.location.replace(fallbackUrl)" in js, \
        "goToNormalFlow does not navigate to the fallback URL"
    # The fallback URL must carry ?skip_splash=1 so the splash doesn't re-arm
    # (which would otherwise loop the user back into the warmer).
    assert "skip_splash=1" in js, "fallback URL does not skip the splash"


def test_preloader_never_disables_local_form():
    """The preloader is request-time only — it must NOT mutate / disable any
    service's local login form. The Wing splash files contain no env / config
    write that would hide a local form (that's a different batch's concern).
    Guard: no DISABLE_LOGIN / SSO_ONLY / ALLOW_LOCAL_LOGIN env mutation lives in
    the preloader surface (it's a pure client-side redirect helper)."""
    for p in (PRESENTER, SPLASH, WARMER):
        src = p.read_text()
        for forbidden in ("DISABLE_LOGIN_FORM", "SSO_ONLY", "ENABLE_PASSWORD_SIGNIN_FORM"):
            assert forbidden not in src, (
                f"{p.name} mutates a service login-form toggle ({forbidden}) — "
                "the preloader must stay a pure client-side redirect helper "
                "and never disable a local fallback form")


def test_redirect_host_whitelist_is_per_service_only():
    """Open-redirect defence: the warmer's ALLOWED_REDIRECT_HOSTS is built from
    ONLY `<svc>.<tld>` + `auth.<tld>` — never an arbitrary attacker host."""
    js = WARMER.read_text()
    assert "ALLOWED_REDIRECT_HOSTS" in js, "no redirect-host whitelist"
    assert "hostAllowed" in js, "warmer does not check the host whitelist"
    # Whitelist seeds: auth.<tld> and <slug>.<tld>.
    assert "'auth.' + tenantDomain" in js, \
        "whitelist missing auth.<tld>"
    assert "+ tenantDomain" in js, \
        "whitelist not derived from the tenant domain"
    # A bad ?service= host must fall back to the same-origin /hub, never an
    # off-whitelist destination.
    assert "return '/hub'" in js, \
        "warmer does not fall back to same-origin /hub for off-whitelist hosts"


def test_bypass_preserves_service_deeplink():
    """The skip/dormant bypass forwards a ?service= deep-link to /hub so a
    launcher target survives the bypass (no value loss when skipping)."""
    presenter = PRESENTER.read_text()
    assert "'service'" in presenter or '"service"' in presenter, \
        "renderSplash bypass drops the ?service= deep-link"
