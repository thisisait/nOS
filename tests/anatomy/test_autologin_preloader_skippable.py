"""Anatomy gate — the custom preloader is skippable and never loops.

sso-autologin-plan.md §"Custom preloader" + §"Testy / gates":

  > `test_autologin_preloader_skippable` — `sso_enable_custom_preloader:true`
  > → warmer JS má `?skip_splash=1` check + `prompt=none`-failure NEcyklí.

BATCH 5 surface (Wing files only):
  - app/Presenters/HubPresenter.php       (renderSplash + ?skip_splash bypass)
  - app/Templates/Hub/splash.latte         (branded splash, skip links)
  - www/assets/hub-session-warmer.js       (prompt=none warmer, no-loop)
  - www/assets/style.css                   (.hub-splash)

This is a STATIC gate (no running daemon): it pins the mechanism's
skip + no-loop contract in the source so a refactor can't silently
reintroduce a redirect loop or remove the bypass.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
PRESENTER = WING / "app" / "Presenters" / "HubPresenter.php"
SPLASH = WING / "app" / "Templates" / "Hub" / "splash.latte"
WARMER = WING / "www" / "assets" / "hub-session-warmer.js"
STYLE = WING / "www" / "assets" / "style.css"


def test_batch5_files_exist():
    for p in (PRESENTER, SPLASH, WARMER, STYLE):
        assert p.is_file(), f"missing BATCH 5 file: {p.relative_to(REPO)}"


def test_presenter_has_render_splash_with_skip_bypass():
    """HubPresenter exposes renderSplash() and honours ?skip_splash=1 as an
    unconditional bypass to the normal dashboard."""
    src = PRESENTER.read_text()
    assert "function renderSplash" in src, \
        "HubPresenter::renderSplash() missing"
    assert "skip_splash" in src, \
        "renderSplash does not read the ?skip_splash bypass query param"
    # The bypass must redirect to the normal dashboard, not stay on the splash.
    assert "Hub:default" in src, \
        "skip/dormant bypass must redirect to Hub:default (the normal flow)"


def test_preloader_dormant_by_default():
    """The splash only renders when the preloader flag is ON. With the flag
    off (default false in default.config.yml) the presenter must bypass to the
    normal dashboard — the whole mechanism stays dormant."""
    src = PRESENTER.read_text()
    assert "SSO_ENABLE_CUSTOM_PRELOADER" in src, \
        "renderSplash does not gate on the SSO_ENABLE_CUSTOM_PRELOADER flag"
    # The dormant default config var must exist (false).
    cfg = (REPO / "default.config.yml").read_text()
    assert "sso_enable_custom_preloader: false" in cfg, \
        "sso_enable_custom_preloader default is not false (dormant)"


def test_warmer_uses_prompt_none_authorize():
    """The warmer fires a silent OIDC authorize with prompt=none against
    Authentik's /application/o/authorize/ for the wing client."""
    js = WARMER.read_text()
    assert "prompt=none" in js, "warmer must use prompt=none for the silent dance"
    assert "/application/o/authorize/" in js, \
        "warmer must hit the Authentik /application/o/authorize/ endpoint"
    assert "client_id=wing" in js, "warmer must authorize as the wing client"


def test_warmer_is_skippable():
    """The warmer's fallback path routes through a ?skip_splash=1 URL so a
    user is never trapped on the splash — the skip link/URL is present in both
    the JS fallback and the splash template."""
    js = WARMER.read_text()
    assert "skip_splash=1" in js, \
        "warmer fallback URL does not carry ?skip_splash=1"
    splash = SPLASH.read_text()
    assert "skip_splash=1" in splash, \
        "splash template has no skip_splash bypass link"


def test_warmer_does_not_loop_on_prompt_none_failure():
    """HARD no-loop contract: on prompt=none FAILURE (login_required / no
    session) the warmer must fall back to the normal flow, NOT re-fire the
    silent attempt. Pinned structurally via:
      - a one-shot attempt guard (sessionStorage), and
      - an explicit comment-documented failure→normal-flow branch.
    """
    js = WARMER.read_text()
    # One-shot guard against re-entry (the loop class).
    assert "sessionStorage" in js, \
        "warmer has no sessionStorage one-shot guard against looping"
    assert "alreadyAttempted" in js or "Attempted" in js, \
        "warmer has no 'already attempted' re-entry guard"
    # A dedicated normal-flow fallback function exists and is reachable.
    assert "goToNormalFlow" in js, \
        "warmer has no goToNormalFlow() fallback for prompt=none failure"
    # The word 'loop' should appear in a NO-loop assertion comment, proving the
    # contract is documented at the failure branch (defends against a later
    # edit that adds a retry-on-failure).
    lower = js.lower()
    assert "loop" in lower, \
        "warmer does not document the no-loop contract at the failure branch"
    # Defensive: the silent attempt must NOT re-issue authorize from inside the
    # failure handler (no nested warm() inside the cross-origin/failure branch).
    # We approximate by asserting the only unconditional warm() entry is the
    # bottom-of-file kickoff + the explicit Retry button handler.
    assert js.count("warm()") <= 3, \
        "warm() invoked too many times — possible re-fire loop on failure"


def test_warmer_has_timeout_fallback_with_retry():
    """A hard timeout (>=10s per the plan's preloader ceiling) drops to a
    Retry + skip fallback rather than hanging."""
    js = WARMER.read_text()
    assert "setTimeout" in js, "warmer has no hard timeout"
    assert "showFallback" in js, "warmer has no fallback reveal on timeout"
    splash = SPLASH.read_text()
    assert "hub-splash-retry" in splash, "splash has no Retry control"
    assert "hub-splash-retry" in js, "warmer does not wire the Retry control"
