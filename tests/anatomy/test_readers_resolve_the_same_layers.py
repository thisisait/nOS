"""A port var lives in three layers; a reader that knows two drops probes.

MEASURED 2026-09-01 on `fix/ci-linux-edge`: `cortex_port`, `backrest_port` and
`stalwart_port_smtp` are declared ONLY in `roles/pazny.*/defaults/main.yml`.
`tools/nos-smoke.py` and `tools/discovery-scan.py` each resolved two layers
(default.config.yml + config.yml), so every probe keyed on those three
resolved None — and nos-smoke's caller dropped the cortex probe with a bare
`continue`. A probe that vanishes reports nothing, for ever, at exit 0.

Two claims, both against the PARSED artifact rather than the source text:
  1. both tools resolve a port var the way `nos_identity.resolve_flag` does;
  2. an unresolvable port is REPORTED, never silently dropped.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
from nos_identity import resolve_flag  # noqa: E402


def _tool(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses in discovery-scan need this
    spec.loader.exec_module(mod)
    return mod


SMOKE = _tool("_nos_smoke", "nos-smoke.py")
DISCOVERY = _tool("_discovery_scan", "discovery-scan.py")

#: The three that were unresolvable. Named rather than derived, so the gate
#: stays red if a future edit makes them unresolvable again by another route.
ROLE_DEFAULT_PORTS = ("cortex_port", "backrest_port", "stalwart_port_smtp")


@pytest.mark.parametrize("port_var", ROLE_DEFAULT_PORTS)
def test_the_role_default_layer_is_the_only_declaration(port_var):
    """Positive control: without the role-defaults layer there is nothing."""
    layers = resolve_flag(port_var)
    assert layers, f"{port_var} is declared in no layer at all"
    assert all(lyr.startswith("roles/") for lyr, _ in layers), (
        f"{port_var} now also lives in a vars_file — this gate's premise moved; "
        f"pick another role-default-only port or delete the parametrisation"
    )


@pytest.mark.parametrize("port_var", ROLE_DEFAULT_PORTS)
def test_discovery_scan_resolves_three_layers(port_var):
    want = resolve_flag(port_var)[-1][1]
    got = DISCOVERY.loopback_port(port_var)
    assert got == want, (
        f"discovery-scan resolves {port_var} to {got!r}, nos_identity to {want!r}. "
        f"Two readers, one fact — and the disagreement is a silent skip."
    )


def test_every_manifest_port_var_resolves_for_both_readers():
    rows = yaml.safe_load((REPO / "state/manifest.yml").read_text(encoding="utf-8"))["services"]
    unresolved = [
        (r.get("id"), r["port_var"]) for r in rows
        if r.get("port_var") and DISCOVERY.loopback_port(r["port_var"]) is None
    ]
    assert not unresolved, (
        f"manifest declares port_var(s) no config layer holds: {unresolved}. "
        f"Every probe keyed on them skips."
    )


def test_the_smoke_loopback_probe_resolves_the_role_default():
    """The concrete drop: cortex is unrouted, so its probe IS the loopback one."""
    vars_dict = SMOKE.merge_config(REPO / "default.config.yml", REPO / "config.yml")
    rows = yaml.safe_load((REPO / "state/manifest.yml").read_text(encoding="utf-8"))["services"]
    cortex = next(r for r in rows if r["id"] == "cortex")
    probe = SMOKE._loopback_probe(cortex, vars_dict)
    assert probe is not None, "the cortex loopback probe is being dropped again"
    assert f":{resolve_flag('cortex_port')[-1][1]}/" in probe[0], probe


def test_an_unresolvable_port_is_reported_not_dropped(capsys):
    """The durable half: resolution can fail; vanishing may not."""
    row = {"id": "ghost", "port_var": "no_such_port_anywhere",
           "health_check": {"url_template": "http://localhost:{{ x }}/health"}}
    assert SMOKE._loopback_probe(row, {}) is None
    err = capsys.readouterr().err
    assert "DROPPED" in err and "ghost" in err and "no_such_port_anywhere" in err, (
        f"an unresolvable port produced no report; stderr was {err!r}"
    )
