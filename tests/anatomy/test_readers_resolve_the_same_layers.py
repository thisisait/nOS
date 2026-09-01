"""A port var lives in three layers; a reader that knows two drops probes.

MEASURED 2026-09-01 on `fix/ci-linux-edge`: `cortex_port`, `backrest_port` and
`stalwart_port_smtp` are declared ONLY in `roles/pazny.*/defaults/main.yml`.
`tools/nos-smoke.py` and `tools/discovery-scan.py` each resolved two layers
(default.config.yml + config.yml), so every probe keyed on those three
resolved None — and nos-smoke's caller dropped the cortex probe with a bare
`continue`. A probe that vanishes reports nothing, for ever, at exit 0.

The same hole runs through the `install_*` flags: five live only in a role
default, and nos-smoke read an absent flag as `false` — a service silently
unprobed. Four claims, all against the PARSED artifact, never the source text:
  1. both tools resolve a port var the way `nos_identity.resolve_flag` does;
  2. an unresolvable port is REPORTED, never silently dropped;
  3. both tools resolve a FLAG the same way, and default to the shared layer list;
  4. a flag no layer declares is reported too — absent is not false.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
from nos_identity import layer_paths, resolve_flag  # noqa: E402


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


#: install_* flags that live ONLY in a role default. A two-layer reader calls
#: them undeclared; in a worktree (no gitignored config.yml) these two resolve
#: in no other layer at all.
ROLE_DEFAULT_FLAGS = ("install_gitea_autowire_nos", "install_woodpecker_autowire_nos")


@pytest.mark.parametrize("flag", ROLE_DEFAULT_FLAGS)
def test_discovery_probe_e_sees_a_role_default_flag(flag):
    """Probe E skipped the whole comparison for a flag it could not resolve.

    Layers minus config.yml — the ephemeral-worktree shape, where the operator's
    gitignored override does not exist and the role default is the only one.
    """
    worktree = [p for p in layer_paths() if p.name != "config.yml"]
    assert flag.removeprefix("install_") in DISCOVERY.resolved_install_flags(worktree), (
        f"{flag} is undeclared to probe E, so its container is never compared"
    )


def test_the_probes_default_layer_list_is_the_shared_one():
    """AST, not a value: on a host whose config.yml happens to declare the same
    flags, a two-layer resolver returns the right answer for the wrong reason.
    What must not drift is WHICH list it defaults to."""
    src = (REPO / "tools/discovery-scan.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.parse(src).body
              if isinstance(n, ast.FunctionDef) and n.name == "resolved_install_flags")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "layer_paths" in names, (
        "resolved_install_flags no longer defaults to nos_identity.layer_paths() — "
        "it is back to a hand-listed subset of the config layers"
    )


def test_smoke_absent_flag_is_reported_not_treated_as_false(capsys):
    """A flag no layer declares is UNKNOWN; false is an answer it cannot give."""
    assert SMOKE.flag_enabled("install_no_such_service", {}, "ghost") is False
    err = capsys.readouterr().err
    assert "DROPPED" in err and "ghost" in err, (
        f"an unresolvable install flag produced no report; stderr was {err!r}"
    )


def test_smoke_falls_back_to_the_reader_not_to_false():
    """Empty vars_dict = the two layers absent (the worktree). Every manifest
    flag a lower layer declares must still resolve, not collapse to disabled."""
    rows = yaml.safe_load((REPO / "state/manifest.yml").read_text(encoding="utf-8"))["services"]
    disagree = []
    for r in rows:
        flag, layers = r.get("install_flag"), resolve_flag(r.get("install_flag") or "\0")
        if not layers:
            continue
        want = layers[-1][1] not in ("false", "no")
        if SMOKE.flag_enabled(flag, {}, r["id"]) is not want:
            disagree.append((r["id"], flag, layers[-1]))
    assert not disagree, (
        f"nos-smoke disagrees with nos_identity about {disagree} — a declared "
        f"flag it cannot see reads as disabled and its probe never runs"
    )


def test_an_unresolvable_port_is_reported_not_dropped(capsys):
    """The durable half: resolution can fail; vanishing may not."""
    row = {"id": "ghost", "port_var": "no_such_port_anywhere",
           "health_check": {"url_template": "http://localhost:{{ x }}/health"}}
    assert SMOKE._loopback_probe(row, {}) is None
    err = capsys.readouterr().err
    assert "DROPPED" in err and "ghost" in err and "no_such_port_anywhere" in err, (
        f"an unresolvable port produced no report; stderr was {err!r}"
    )
