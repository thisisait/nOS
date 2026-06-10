"""Browser /hub page render smoke — catches HubPresenter render 500s without
SSO creds (closes the test gap that missed ea7c1fa's ArgumentCountError).

The existing smoke/hub.spec.ts (Playwright) tests `/hub` via gotoWithAuth and
skips without AUTHENTIK_PASSWORD. This pytest variant uses the edge-token +
forged forward-auth headers (same pattern as the `wing-live-verify-recipe`
memory) so it runs in CI without an SSO password.

Run after a playbook to validate the auto-wiring's render path:

    python3 -m pytest tests/anatomy/test_hub_render_smoke.py -v
"""

from __future__ import annotations

import os
import plistlib
import subprocess

import pytest


def _edge_token() -> str | None:
    """The deployed daemon's WING_EDGE_TOKEN (env or operator plist fallback)."""
    if (t := os.environ.get("WING_EDGE_TOKEN")):
        return t
    plist_path = os.path.expanduser(
        "~/Library/LaunchAgents/eu.thisisait.nos.wing.plist"
    )
    if not os.path.isfile(plist_path):
        return None
    try:
        with open(plist_path, "rb") as f:
            return plistlib.load(f)["EnvironmentVariables"].get("WING_EDGE_TOKEN")
    except (OSError, KeyError, ValueError):
        return None


def _fetch_hub(extra_groups: str = "nos-admins") -> tuple[int, str]:
    token = _edge_token()
    if not token:
        pytest.skip("WING_EDGE_TOKEN not discoverable")
    r = subprocess.run(
        ["/usr/bin/curl", "-sS", "--max-time", "10",
         "-H", f"X-Wing-Edge-Token: {token}",
         # forge what the Traefik forward-auth middleware injects after a real
         # Authentik session — Wing renders RBAC-tier-aware against these
         "-H", "X-authentik-username: smoke",
         "-H", f"X-authentik-groups: {extra_groups}",
         "-H", "Remote-User: smoke",
         "-H", "Remote-Email: smoke@local",
         "-w", "\n---HTTP-CODE: %{http_code}---",
         "http://127.0.0.1:9000/hub"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        pytest.skip(f"wing daemon unreachable (curl rc={r.returncode})")
    body = r.stdout
    # extract HTTP code from the suffix we wrote with -w
    code_marker = "---HTTP-CODE: "
    if code_marker in body:
        head, _, tail = body.rpartition(code_marker)
        try:
            return int(tail.strip("- ")), head
        except ValueError:
            pass
    return 0, body


def test_hub_page_renders_without_500():
    """Render the /hub page as an admin viewer; assert 200 + a sys-card is
    present. A presenter signature drift / DI mismatch (like the live 500 the
    cache-clear handler b6a5357 prevents) would surface here."""
    code, html = _fetch_hub("nos-admins")
    # Tracy production "Server Error" is a 500 with a clean page; the cache-
    # cleared daemon should be 200.
    assert code == 200, f"/hub returned HTTP {code}\nfirst 400B:\n{html[:400]}"
    # The rendered grid must contain at least one card. The hub_card icon
    # overlay (P1a) adds data-icon to each sys-card.
    assert ".sys-card" in html or "sys-card" in html, \
        "no sys-card elements rendered — register/HubPresenter mismatch?"
    # The lucide glyph wiring (0177022) must reach the DOM.
    assert "data-icon=" in html, "icon glyph data-icon missing"
    # And the icon assets are referenced so the visible payoff actually loads.
    assert "lucide-slim.js" in html, "lucide self-host script tag missing (W6.5 slim)"


def test_hub_page_renders_for_lower_tier_viewer():
    """A nos-users tier viewer must also see /hub (no blank, no 500). The
    HubPresenter falls back to viewerTier=1 (show-all) when no nos-group
    matches, so even an unrecognised header set must NOT 500."""
    code, _ = _fetch_hub("nos-users")
    assert code == 200, f"/hub 500 for non-admin viewer (HTTP {code})"


def test_hub_page_handles_missing_groups_header():
    """Edge-token caller with NO nos-group: should NOT 500 (viewerTier defaults
    to 1, page renders). Defensive check on the RBAC overlay code path."""
    code, _ = _fetch_hub("")
    assert code == 200, f"/hub 500 with empty groups header (HTTP {code})"
