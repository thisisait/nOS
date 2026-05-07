"""native_oidc plugins must not emit authentik@file middleware (Anatomy 2026-05-07).

When a plugin declares ``authentik.mode: native_oidc``, the service
handles its own OIDC login inside the app. Wrapping it with the Traefik
forward-auth middleware (`authentik@file`) on TOP of that creates:
  - double-login UX (Authentik gate, then in-app "Sign in with Authentik")
  - duplicate-router collisions when file-provider auto-derives a route
    WITHOUT the middleware while docker labels emit one WITH it
  - non-deterministic Traefik routing → 404 spinner

Surfaced live 2026-05-07 12:25: Node-RED's `nodered-base.compose.yml.j2`
still emitted `authentik@file` middleware after β1.B flipped the SSO
mode to native_oidc. File-provider entry (no middleware) and docker
entry (with middleware) collided; Traefik picked the docker one ~50%
of the time, returned 404 because the inner Authentik provider didn't
match — smoke probe failed.

This gate is the structural fix companion to the nodered cleanup commit.
It walks every plugin manifest with mode=native_oidc and inspects every
compose-extension template for actual middleware label declarations
(comments don't count).
"""

from __future__ import annotations

import os
import re
from glob import glob

import pytest
import yaml

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _native_oidc_plugins() -> list[str]:
    """Yield every plugin.yml whose authentik.mode is native_oidc."""
    out: list[str] = []
    for path in glob(f"{_REPO}/files/anatomy/plugins/*/plugin.yml"):
        try:
            with open(path) as fh:
                doc = yaml.safe_load(fh) or {}
        except (yaml.YAMLError, OSError):
            continue
        mode = (doc.get("authentik") or {}).get("mode")
        if mode == "native_oidc":
            out.append(path)
    return out


# Match a non-commented line that declares `authentik@file` as part of a
# Traefik middleware label — both YAML-list ("- traefik.http.routers...
# .middlewares=authentik@file,...") and dict ("traefik.http.routers...
# .middlewares: authentik@file") forms.
_LABEL_RE = re.compile(
    r"^[^#]*traefik\.http\.routers\.[^=:\s]+\.middlewares\s*[=:][^#]*authentik@file",
    re.MULTILINE,
)


def test_native_oidc_compose_extensions_dont_emit_authentik_middleware():
    offenders: list[str] = []
    for plugin_yml in _native_oidc_plugins():
        plugin_dir = os.path.dirname(plugin_yml)
        tpl_dir = os.path.join(plugin_dir, "templates")
        if not os.path.isdir(tpl_dir):
            continue
        for tpl in glob(os.path.join(tpl_dir, "*.j2")):
            try:
                with open(tpl) as fh:
                    body = fh.read()
            except OSError:
                continue
            if _LABEL_RE.search(body):
                rel = os.path.relpath(tpl, _REPO)
                offenders.append(rel)

    assert not offenders, (
        "native_oidc plugins MUST NOT emit `authentik@file` Traefik middleware in\n"
        "compose-extension templates. The service handles OIDC inside the app;\n"
        "wrapping it in forward-auth creates duplicate routers + double login.\n\n"
        "Fix: remove the `traefik.http.routers.<name>.middlewares` label from the\n"
        "extension, OR delete the extension entirely if Traefik routing was its\n"
        "only purpose. The file-provider router (auto-derived from state/manifest.yml\n"
        "+ traefik_auth_modes) is the canonical Tier-1 route.\n\n"
        "Offenders:\n  - " + "\n  - ".join(offenders)
    )
