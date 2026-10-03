"""Gate: removing a plugin's authentik: block retires its provider, not the converge.

2026-10-01: ntfy / onlyoffice / woodpecker stopped claiming a forward_auth gate
the edge never enforced. An un-registered slug's destroy is REFUSED by the tofu
guard; the generator keeps a disabled tombstone, which the guard applies.
"""
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))
from nos_tofu_guard import nos_tofu_destroy_split  # noqa: E402

REGISTRY = yaml.safe_load((REPO / "state/tofu-authentik-services.yml").read_text())["tofu_authentik_services"]
TOMBS = [e for e in REGISTRY if e.get("retired")]


def _authored_slugs() -> set:
    out = set()
    for f in list((REPO / "files/anatomy/plugins").glob("*/plugin.yml")) + list((REPO / "apps").glob("[!_]*.yml")):
        block = (yaml.safe_load(f.read_text()) or {}).get("authentik")
        if isinstance(block, dict) and block.get("slug"):
            out.add(block["slug"])
    return out


def test_the_three_are_tombstoned():
    assert {"ntfy", "onlyoffice", "woodpecker", "spacetimedb"} <= {e["slug"] for e in TOMBS}


def test_a_tombstone_is_disabled_and_unauthored():
    authored = _authored_slugs()
    for e in TOMBS:
        assert e["enabled"] is False and e["slug"] not in authored, e["slug"]


def test_the_guard_applies_a_tombstones_destroy():
    for e in TOMBS:
        rc = {"address": f'module.service["{e["slug"]}"].authentik_provider_proxy.this[0]',
              "type": "authentik_provider_proxy", "change": {"actions": ["delete"]}}
        split = nos_tofu_destroy_split([rc], REGISTRY)
        assert split["unexplained"] == [] and len(split["declared_off"]) == 1, (e["slug"], split)


def test_probes_outlive_the_sso_block():
    """e2e-plan took `enabled` from the authentik: block; without one, a
    plugin's probes vanished from the plan silently (woodpecker, 2026-10-01)."""
    for f in (REPO / "files/anatomy/plugins").glob("*/plugin.yml"):
        doc = yaml.safe_load(f.read_text()) or {}
        if (doc.get("e2e") or {}).get("probes") and not doc.get("authentik"):
            assert "enabled" in doc["e2e"], f"{f.parent.name}: probes with no enabled — never run"
