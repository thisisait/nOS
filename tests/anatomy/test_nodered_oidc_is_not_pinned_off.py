"""REM-256 — Node-RED native OIDC must not be pinned off in SOURCE.

The plugin declares authentik.mode: native_oidc. Traefik therefore does NOT
attach authentik@file (test_native_oidc_no_authentik_middleware,
test_forward_auth_does_not_stack). adminAuth in settings.js.j2 only renders
when install_authentik AND nodered_native_oidc_enabled are both true.

D2 promoted the var into default.config.yml (c64c397e) so play-scope can see
it. The promotion wrote a literal `false`, which outranks the role default
that follows install_authentik. Result: no adminAuth, no edge gate, /settings
and /flows answer 200 at the public hostname (cycle-57 probe).

WHAT THIS CANNOT DO: turn adminAuth on in the running container. That is a
nos --tags nodered, then a reader of /auth/login. A green here is the SOURCE
shape.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "default.config.yml"
ROLE_DEFAULTS = REPO / "roles/pazny.nodered/defaults/main.yml"
SETTINGS = REPO / "roles/pazny.nodered/templates/settings.js.j2"


def test_default_config_follows_install_authentik() -> None:
    cfg = CONFIG.read_text(encoding="utf-8")
    m = re.search(r"^nodered_native_oidc_enabled:\s*(.*)$", cfg, re.M)
    assert m, (
        "nodered_native_oidc_enabled left default.config.yml — D2 needs it "
        "visible at play scope; deleting the line hides the override again"
    )
    raw = m.group(1).strip()
    literal = raw.strip("\"'")
    assert literal.lower() not in {"false", "no", "0"}, (
        f"nodered_native_oidc_enabled is pinned {raw!r}. Traefik will not "
        "forward-auth this native_oidc route, so a false pin leaves the "
        "editor open at the public edge (REM-256). Follow install_authentik."
    )
    assert "install_authentik" in raw, (
        f"nodered_native_oidc_enabled is {raw!r}; it must follow "
        "install_authentik so an authentik-off estate does not render a "
        "strategy that cannot complete"
    )


def test_role_default_still_follows_install_authentik() -> None:
    body = ROLE_DEFAULTS.read_text(encoding="utf-8")
    m = re.search(r"^nodered_native_oidc_enabled:\s*(.*)$", body, re.M)
    assert m and "install_authentik" in m.group(1), (
        "role default stopped following install_authentik — that is the "
        "backstop if default.config.yml ever drops the var"
    )


def test_settings_admin_auth_needs_both_flags() -> None:
    body = SETTINGS.read_text(encoding="utf-8")
    assert "nodered_native_oidc_enabled" in body
    assert "install_authentik" in body
    assert "adminAuth" in body
