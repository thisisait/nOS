"""Anatomy gate — autologin block carries the full identity contract.

sso-autologin-plan.md §"Testy / gates":

  > `test_autologin_block_has_required_fields`: je-li `autologin` přítomen,
  > blok má `client_id`, `client_secret`, `slug`, `mode`, `tier`, `supports`.

An autologin block only makes sense alongside a complete OIDC client
identity: the blueprint needs client_id/client_secret/slug/tier to mint
the provider, `mode` to confirm it's native_oidc, and `supports` to carry
the honesty verdict. A partial block would render a half-wired provider.

`client_id`, `client_secret`, `slug`, `mode`, `tier` live on the
`authentik` block itself; `supports` lives inside the `autologin` sub-block.

Batch 0: no autologin blocks → vacuous pass.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS = REPO / "files" / "anatomy" / "plugins"

# Fields that must live on the authentik block when autologin is present.
REQUIRED_AUTHENTIK_FIELDS = ("client_id", "client_secret", "slug", "mode", "tier")


def _authentik_block(yaml_path: pathlib.Path) -> dict | None:
    data = yaml.safe_load(yaml_path.read_text())
    a = (data or {}).get("authentik")
    return a if isinstance(a, dict) else None


def test_autologin_block_has_required_fields():
    failures: list[str] = []
    for p in sorted(PLUGINS.glob("*/plugin.yml")):
        a = _authentik_block(p)
        if not a or not isinstance(a.get("autologin"), dict):
            continue
        missing = [f for f in REQUIRED_AUTHENTIK_FIELDS if a.get(f) in (None, "")]
        if "supports" not in a["autologin"] or a["autologin"].get("supports") in (None, ""):
            missing.append("autologin.supports")
        if missing:
            failures.append(f"{p.parent.name}: missing {missing}")
    assert not failures, (
        "autologin block present but identity contract incomplete:\n"
        + "\n".join(f"  {f}" for f in failures))
