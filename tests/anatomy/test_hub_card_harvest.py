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


def test_uptime_kuma_consumes_hub_card_health_check():
    """P1b: Uptime Kuma probes the service's declared health endpoint (from the
    harvested hub_card.health_check) instead of the bare root. Path-style
    health_checks are appended to the monitor URL; full-URL/absent keep root."""
    mon = (REPO / "roles/pazny.uptime_kuma/tasks/monitors.yml").read_text()
    assert "hub-cards.json" in mon, "monitors must read the plugin-harvested cards"
    assert "_kuma_health_paths" in mon and "startswith('/')" in mon, "path-style health_check appended to URL"


def test_wing_overlays_hub_card_icon_on_systems():
    """P1a render side: HubCardRepository reads hub-cards.json; HubPresenter
    overlays the card icon/tier onto the /hub systems by slug (render-time, no
    DB change), and exposes the viewer's RBAC tier. The icon glyph needs an
    icon system — data-icon is wired through to the DOM for it."""
    assert (REPO / "files/anatomy/wing/app/Model/HubCardRepository.php").is_file()
    pres = (REPO / "files/anatomy/wing/app/Presenters/HubPresenter.php").read_text()
    assert "HubCardRepository" in pres and "bySlug()" in pres
    assert "viewerTier" in pres, "viewer RBAC tier must be exposed for tier-aware presentation"
    neon = (REPO / "files/anatomy/wing/app/config/common.neon").read_text()
    assert "HubCardRepository" in neon, "repository must be DI-registered"
    latte = (REPO / "files/anatomy/wing/app/Templates/Hub/default.latte").read_text()
    assert "data-icon=" in latte, "card icon must reach the DOM"


def test_wing_deploy_clears_compiled_cache():
    """2026-05-29: /hub 500'd (ArgumentCountError) after HubPresenter gained a
    constructor arg — the rsync excludes temp/, so the STALE compiled Nette DI
    container called the new class with the old signature. The Restart-wing
    handler doesn't recompile. The deploy must clear temp/cache on source change
    so the container + Latte recompile."""
    main = (REPO / "roles/pazny.wing/tasks/main.yml").read_text()
    assert "temp/cache" in main and "state: absent" in main, "wing deploy must clear the compiled cache"
    assert "_wing_app_sync is changed" in main, "clear only when app source changed"


def test_systems_registry_orphan_sweep():
    """2026-05-29: /hub showed 18 hard 404s; 14 of them (hedgedoc, jellyfin,
    wordpress, miniflux, …) had install_*=false → the rendered registry no
    longer listed them, yet stale `source=registry` rows remained in the
    systems table from a prior run when they were on. Ingest must sweep rows
    whose id dropped out of the registry (stack-* and install_* exempt).
    Live: systems 66 → 51."""
    src = (REPO / "files/anatomy/wing/app/Model/SystemRepository.php").read_text()
    assert "registry_dropouts_swept" in src and "$importedIds" in src, \
        "registry-orphan sweep + tracked imported ids must be in ingestRegistry"
    cli = (REPO / "files/anatomy/wing/bin/ingest-registry.php").read_text()
    assert "registry dropouts" in cli, "CLI must report the new sweep count"


def test_hub_icon_glyph_assets_wired():
    """P1a icon glyph (2026-05-29): the .sys-icon span needs lucide to render
    a visible SVG. lucide is self-hosted (data sovereignty — no CDN), wired in
    Hub/default.latte alongside a tiny init JS that maps non-standard names
    (ai-chat → message-square-text, etc.) to lucide standard."""
    assert (REPO / "files/anatomy/wing/www/assets/lucide.min.js").is_file(), \
        "self-hosted lucide must be committed (no CDN dep on first load)"
    init = (REPO / "files/anatomy/wing/www/assets/hub-icons.js").read_text()
    assert "lucide.createIcons" in init and "ALIAS" in init
    css = (REPO / "files/anatomy/wing/www/assets/hub-icons.css").read_text()
    assert ".sys-icon" in css
    latte = (REPO / "files/anatomy/wing/app/Templates/Hub/default.latte").read_text()
    for tag in ("hub-icons.css", "lucide.min.js", "hub-icons.js"):
        assert tag in latte, f"Hub template must reference {tag}"
