"""Anatomy gate — /hub backend-only suppression is plugin-harvested.

phi-hub-card-icon-gap (2026-06-14): HubPresenter::BACKEND_ONLY_SLUGS was a
hardcoded allow-list of 7 backend service slugs (loki, tempo, prometheus,
alloy, bluesky_pds, qgis_server, nginx) — a service with a domain route but no
clickable browser-root UI that /hub must suppress (else the tile 404s). A new
backend plugin wouldn't auto-hide; it needed a PHP edit.

Fix (mechanical): a top-level `kind: backend` flag on the plugin manifest,
harvested by the wing-base aggregator (from: consumer_kind, block_path kind)
into backend-slugs.json, read by HubPresenter::backendOnlySlugs() and UNIONed
with a minimal non-plugin host floor (nginx — no manifest). This gate runs the
REAL loader + render template so a manifest/template/presenter regression is
caught before a blank run.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "files/anatomy/module_utils"))

# The 6 backend services that own a plugin manifest (nginx is a non-plugin host
# service → can't carry the flag → stays on the presenter's hardcoded floor).
_EXPECTED_PLUGIN_BACKENDS = {
    "alloy", "bluesky_pds", "loki", "prometheus", "qgis_server", "tempo",
}


def _harvest_backend_entries() -> list[dict]:
    import load_plugins as lp
    plugins = lp.discover(REPO / "files/anatomy/plugins")
    lp.run_aggregators(plugins)
    wing = next(p for p in plugins if p.name == "wing-base")
    return wing.inputs.get("backend_kinds", [])


def test_schema_allows_kind_backend():
    """plugin.schema.json must accept the optional top-level `kind: backend`."""
    schema = json.loads(
        (REPO / "state/schema/plugin.schema.json").read_text()
    )
    kind = schema["properties"].get("kind")
    assert kind is not None, "schema must declare a top-level `kind` field"
    assert kind.get("enum") == ["backend"], "kind enum must be exactly ['backend']"


def test_six_backend_plugins_declare_kind():
    """Every backend service that owns a manifest declares `kind: backend`."""
    import yaml
    for slug in _EXPECTED_PLUGIN_BACKENDS:
        name = slug.replace("_", "-") + "-base"
        manifest = REPO / "files/anatomy/plugins" / name / "plugin.yml"
        assert manifest.is_file(), f"{name} manifest missing"
        m = yaml.safe_load(manifest.read_text()) or {}
        assert m.get("kind") == "backend", f"{name} must declare `kind: backend`"


def test_wing_base_declares_backend_kind_aggregator():
    """wing-base must harvest the flag and render the sidecar."""
    wing = (REPO / "files/anatomy/plugins/wing-base/plugin.yml").read_text()
    assert "from: consumer_kind" in wing, "wing-base must harvest kind via consumer_kind"
    assert "block_path: kind" in wing
    assert "output_var: backend_kinds" in wing
    assert "provisioning.backend_slugs" in wing, "post_compose must render the sidecar"
    assert (REPO / "files/anatomy/plugins/wing-base/templates/backend-slugs.json.j2").is_file()


def test_harvest_collects_exactly_the_plugin_backends():
    """The real loader harvest yields exactly the 6 manifest-backed backends."""
    entries = _harvest_backend_entries()
    slugs = {
        str(e["slug"]).replace("-", "_")
        for e in entries
        if e.get("kind") == "backend" and "slug" in e
    }
    assert slugs == _EXPECTED_PLUGIN_BACKENDS, (
        f"harvested {sorted(slugs)} != expected {sorted(_EXPECTED_PLUGIN_BACKENDS)}"
    )


def test_render_template_produces_valid_underscore_slugs():
    """backend-slugs.json renders the underscore-normalised systems-table ids."""
    try:
        from jinja2 import Environment
    except ImportError:  # pragma: no cover
        pytest.skip("jinja2 not available")
    entries = _harvest_backend_entries()
    env = Environment()
    env.filters["to_json"] = json.dumps
    tmpl = env.from_string(
        (REPO / "files/anatomy/plugins/wing-base/templates/backend-slugs.json.j2").read_text()
    )
    doc = json.loads(tmpl.render(inputs={"backend_kinds": entries}))
    rendered = set(doc["backend_slugs"])
    assert rendered == _EXPECTED_PLUGIN_BACKENDS
    # underscore-normalised (matches systems.id shape), never hyphenated.
    assert all("-" not in s for s in rendered), "slugs must be underscore-normalised"


def test_union_with_floor_reconstructs_original_seven():
    """harvested 6 + the non-plugin floor (nginx) == the original allow-list of
    7 → behaviour is preserved (zero-drift mechanical fix)."""
    entries = _harvest_backend_entries()
    harvested = {
        str(e["slug"]).replace("-", "_")
        for e in entries
        if e.get("kind") == "backend" and "slug" in e
    }
    union = harvested | {"nginx"}
    assert union == {
        "bluesky_pds", "loki", "tempo", "prometheus", "alloy", "nginx", "qgis_server",
    }, "harvest + floor must equal the original BACKEND_ONLY_SLUGS"


def test_presenter_reads_sidecar_not_only_constant():
    """HubPresenter must query the harvested sidecar (dynamic), keep nginx as a
    non-plugin floor, and no longer reference the constant directly in the
    clickable filter (it survives only as the absent-sidecar fallback)."""
    pres = (REPO / "files/anatomy/wing/app/Presenters/HubPresenter.php").read_text()
    assert "backend-slugs.json" in pres, "presenter must read the harvested sidecar"
    assert "backendOnlySlugs()" in pres, "presenter must expose the dynamic lookup"
    assert "BACKEND_NON_PLUGIN_FLOOR" in pres and "'nginx'" in pres, \
        "non-plugin host floor (nginx) must survive"
    # The clickable closure must use the dynamic list, not the constant.
    assert "in_array($sys['id'] ?? '', $backendOnly, true)" in pres, \
        "clickable filter must use the harvested $backendOnly, not the constant"
