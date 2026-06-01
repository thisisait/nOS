"""Anatomy gate — autologin is legal ONLY for native_oidc services.

sso-autologin-plan.md §"Globální mechanismus" + §"Testy / gates":

  > `autologin` je legální jen pro `mode: native_oidc`. forward_auth/
  > header_oidc autologin nedeklarují (anti-pattern double-protection;
  > firefly = header_oidc → auto-login řeší outpost, ne tento blok).

Any plugin that declares an `authentik.autologin` block MUST have
`authentik.mode` (or its canonical alias `provider_type`) == native_oidc.
Stacking force-OIDC env on a forward_auth route is double-protection
(operator gets a double-login UX for no security benefit); firefly is
header_oidc — its auto-login is the proxy outpost injecting REMOTE_USER,
not a service-side env var.

At Batch 0 no plugin declares autologin yet, so this iterates over an
empty match set and passes vacuously. It starts biting the moment the
first autologin block lands on a non-native_oidc plugin.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS = REPO / "files" / "anatomy" / "plugins"


def _authentik_block(yaml_path: pathlib.Path) -> dict | None:
    data = yaml.safe_load(yaml_path.read_text())
    a = (data or {}).get("authentik")
    return a if isinstance(a, dict) else None


def test_autologin_only_for_native_oidc_services():
    offenders: list[tuple[str, str]] = []
    for p in sorted(PLUGINS.glob("*/plugin.yml")):
        a = _authentik_block(p)
        if not a or "autologin" not in a:
            continue
        mode = a.get("mode") or a.get("provider_type")
        if mode != "native_oidc":
            offenders.append((p.parent.name, str(mode)))
    assert not offenders, (
        "plugins declaring an authentik.autologin block but NOT mode "
        f"native_oidc (autologin is legal only for native_oidc): {offenders}"
    )
