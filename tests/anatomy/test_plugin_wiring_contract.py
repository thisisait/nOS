"""Anatomy CI gate — uniform plugin wiring contract.

The service plugins under files/anatomy/plugins/ (counted live, not here —
55 when this gate was written, 60 by 2026-08-18) wire services into the
platform through optional manifest blocks. Coverage drifted as plugins were
authored by different passes, and the gating mechanism had real holes
(qdrant-base ran its post_compose wait_health on every run regardless of
toggle). This gate pins the uniform contract so future plugins can't
re-introduce the drift:

  1. Every plugin.yml validates against state/schema/plugin.schema.json.
  2. Every `service` plugin declares a gate (requires.feature_flag OR
     requires.app) — no service plugin runs ungated.
  3. A feature_flag resolves to a real toggle var in default.config.yml
     (typo-proofing: install_qdarnt would silently never gate).
  4. The plugin DAG resolves with no cycles.
  5. notification blocks use the canonical A9 severity-routing shape
     (on_critical/on_high/on_medium/on_low/on_info), not the dead event-key
     shape whose referenced template files don't exist on disk.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

# tests/conftest.py adds files/anatomy/ to sys.path.
from module_utils import load_plugins  # type: ignore  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO / "files" / "anatomy" / "plugins"
SCHEMA_PATH = REPO / "state" / "schema" / "plugin.schema.json"

CANONICAL_SEVERITIES = {"on_critical", "on_high", "on_medium", "on_low", "on_info"}


def _known_toggles() -> set[str]:
    """Top-level var names in default.config.yml (the toggle namespace)."""
    raw = (REPO / "default.config.yml").read_text(encoding="utf-8")
    raw = re.sub(r"\{\{[^}]+\}\}", "TEMPLATE", raw)
    return set((yaml.safe_load(raw) or {}).keys())


def _all_plugins() -> list[load_plugins.Plugin]:
    return load_plugins.discover(PLUGINS_ROOT)


def _service_plugins() -> list[load_plugins.Plugin]:
    return [p for p in _all_plugins()
            if "service" in (p.manifest.get("type") or [])]


def _plugin_ids(plugins) -> list[str]:
    return [p.name for p in plugins]


def test_all_manifests_validate_against_schema():
    """Every plugin.yml passes schema validation (jsonschema or fallback)."""
    import json
    schema = json.loads(SCHEMA_PATH.read_text())
    failures = {}
    for p in _all_plugins():
        errs = load_plugins.validate_manifest(p.manifest, schema)
        if errs:
            failures[p.name] = errs
    assert not failures, (
        "schema validation failures:\n" +
        "\n".join(f"  {n}: {e}" for n, e in failures.items()))


@pytest.mark.parametrize("plugin", _service_plugins(), ids=_plugin_ids(_service_plugins()))
def test_service_plugin_has_a_gate(plugin):
    """Every service plugin declares requires.feature_flag OR requires.app.

    Without a gate, the loader runs the plugin's lifecycle hooks on every
    playbook run — which is how qdrant-base's :6333 wait_health degraded
    every run before it gained feature_flag: install_qdrant.
    """
    req = plugin.manifest.get("requires") or {}
    assert req.get("feature_flag") or req.get("app"), (
        f"{plugin.name}: service plugin must declare requires.feature_flag "
        f"or requires.app")


@pytest.mark.parametrize("plugin", _service_plugins(), ids=_plugin_ids(_service_plugins()))
def test_feature_flag_resolves_to_real_toggle(plugin):
    """A declared feature_flag must be a real var in default.config.yml."""
    req = plugin.manifest.get("requires") or {}
    flag = req.get("feature_flag")
    if not flag:
        pytest.skip(f"{plugin.name} is app-gated, no feature_flag")
    assert flag in _known_toggles(), (
        f"{plugin.name}: feature_flag {flag!r} is not a toggle in "
        f"default.config.yml (typo?)")


def test_dag_resolves_without_cycles():
    """topological_order must not raise on the real plugin set."""
    load_plugins.topological_order(_all_plugins())


@pytest.mark.parametrize("plugin", _service_plugins(), ids=_plugin_ids(_service_plugins()))
def test_notification_block_uses_canonical_severity_shape(plugin):
    """notification blocks use the A9 severity-routing keys.

    The wing-base aggregator harvests notification blocks into the routing
    sidecar keyed by severity (on_critical/...). The legacy event-key shape
    (on_<event>: {channels, template}) referenced template files that were
    never committed, so those entries were dead. A present block must carry
    at least one canonical severity key.
    """
    n = plugin.manifest.get("notification")
    if not n:
        pytest.skip(f"{plugin.name} has no notification block")
    assert any(k in CANONICAL_SEVERITIES for k in n), (
        f"{plugin.name}: notification block uses no canonical severity key "
        f"(has {sorted(n)}); expected one of {sorted(CANONICAL_SEVERITIES)}")
