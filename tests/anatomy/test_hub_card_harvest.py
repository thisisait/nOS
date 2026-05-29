"""Anatomy gate — Wing /hub cards are plugin-harvested (P1a, 2026-05-29).

49 plugins authored `ui-extension.hub_card` blocks that nothing consumed. The
wing-base aggregator now harvests them (block_path ui-extension → output_var
hub_cards) and a post_compose render writes hub-cards.json; HubCardRepository
+ HubPresenter render them on /hub, RBAC-filtered by the viewer's tier.

This gate exercises the REAL harvest (loader run) + the render template, so a
manifest/template regression is caught before a blank run.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "files/anatomy/module_utils"))


def test_wing_base_declares_hub_card_aggregator():
    wing = (REPO / "files/anatomy/plugins/wing-base/plugin.yml").read_text()
    assert "block_path: ui-extension" in wing, "wing-base must harvest the ui-extension block"
    assert "output_var: hub_cards" in wing
    assert "provisioning.hub_cards" in wing, "post_compose must render the cards JSON"
    assert (REPO / "files/anatomy/plugins/wing-base/templates/hub-cards.json.j2").is_file()


def test_harvest_collects_cards_and_renders_valid_json():
    import load_plugins as lp
    plugins = lp.discover(REPO / "files/anatomy/plugins")
    lp.run_aggregators(plugins)
    wing = next(p for p in plugins if p.name == "wing-base")
    cards = wing.inputs.get("hub_cards", [])
    assert len(cards) >= 30, f"expected the bulk of the 49 cards harvested, got {len(cards)}"
    # Every harvested entry carries the source slug + a hub_card.
    assert all("hub_card" in e and "slug" in e for e in cards)

    try:
        from jinja2 import Environment
    except ImportError:  # pragma: no cover
        pytest.skip("jinja2 not available")
    env = Environment()
    env.filters["to_json"] = json.dumps
    tmpl = env.from_string(
        (REPO / "files/anatomy/plugins/wing-base/templates/hub-cards.json.j2").read_text()
    )
    doc = json.loads(tmpl.render(inputs={"hub_cards": cards}, ansible_date_time={"iso8601": "x"}))
    assert len(doc["cards"]) >= 30
    c0 = doc["cards"][0]
    assert {"slug", "title", "icon", "url", "tier", "description", "health_check"} <= set(c0)
