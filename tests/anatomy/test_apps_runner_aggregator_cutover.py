"""Anatomy gates for the Tier-2 aggregator cleanup (2026-05-17).

Pre-cleanup, apps_runner/post.yml shadowed the X.3 aggregator path by
also `set_fact`'ing extensions into the legacy `authentik_oidc_apps` +
`authentik_app_tiers` vars. The blueprint templates UNION those two
sources, so every Tier-2 app appeared TWICE in the rendered Authentik
blueprints. Cleanup deletes the legacy set_fact blocks; aggregator
becomes the single source of truth (with tier resolution reading
nginx.rbac_tier).

Active-work punch #3 was the original tracker.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_apps_runner_no_longer_set_facts_authentik_legacy_vars():
    """apps_runner/post.yml must NOT extend `authentik_oidc_apps` or
    `authentik_app_tiers` via set_fact — those are retired post-X.3."""
    src = (REPO / "roles/pazny.apps_runner/tasks/post.yml").read_text()
    # The pre-cleanup set_fact tasks had these exact line shapes.
    assert "authentik_oidc_apps: >-" not in src, (
        "apps_runner still extends `authentik_oidc_apps` via set_fact "
        "(duplicates the X.3 aggregator path → blueprint emits each "
        "Tier-2 app twice). Drop the set_fact and let the aggregator "
        "own the merge."
    )
    assert "authentik_app_tiers: >-" not in src, (
        "apps_runner still extends `authentik_app_tiers` via set_fact "
        "(retired post-X.3; aggregator reads tier from nginx.rbac_tier)."
    )
    # The legacy `_apps_authentik_extras` builder is also retired.
    assert "_apps_authentik_extras:" not in src, (
        "_apps_authentik_extras set_fact retired — use the presence test "
        "`_apps_has_authentik_consumers` instead."
    )
    # New presence-test variable IS present (gating the blueprint reconverge).
    assert "_apps_has_authentik_consumers" in src


def test_aggregator_reads_tier_from_nginx_rbac_tier():
    """The aggregator's `from: app_manifest` branch must resolve tier
    from `nginx.rbac_tier` (where every existing apps/*.yml stores it)
    before defaulting to 2. Pre-cleanup the aggregator hardcoded
    `tier=2` for every Tier-2 app, ignoring the manifest's rbac_tier."""
    src = (REPO / "files/anatomy/module_utils/load_plugins.py").read_text()
    assert 'app.get("nginx")' in src
    assert "nginx.get(\"rbac_tier\")" in src


def test_end_to_end_aggregator_picks_correct_tiers():
    """Run the real aggregator against the live apps/*.yml manifests +
    discovered plugins; confirm Tier-2 apps land in inputs.clients with
    tier matching nginx.rbac_tier from each manifest."""
    sys.path.insert(0, str(REPO / "files/anatomy/module_utils"))
    import importlib
    import load_plugins as lp
    importlib.reload(lp)
    import yaml

    plugins = lp.discover(REPO / "files/anatomy/plugins")
    apps = []
    for p in (REPO / "apps").glob("*.yml"):
        if p.name == "_template.yml":
            continue
        data = yaml.safe_load(p.read_text())
        if isinstance(data, dict):
            apps.append(data)
    lp.run_aggregators(plugins, app_manifests=apps)
    auth = next(p for p in plugins if p.name == "authentik-base")
    clients = auth.inputs.get("clients") or []
    tier_two_apps = [c for c in clients
                     if (c.get("plugin_name") or "").startswith("app:")]
    # Every Tier-2 app has a tier set (no None / missing).
    assert tier_two_apps, "no Tier-2 apps harvested at all — manifest layout regressed"
    for c in tier_two_apps:
        assert c.get("tier") is not None, (
            f"Tier-2 app {c.get('slug')!r} landed without a tier — "
            f"aggregator should read nginx.rbac_tier"
        )
        assert isinstance(c.get("tier"), int), (
            f"Tier-2 app {c.get('slug')!r} tier should be int, got "
            f"{type(c.get('tier')).__name__}"
        )
