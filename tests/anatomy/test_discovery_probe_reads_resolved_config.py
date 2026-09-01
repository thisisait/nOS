"""Anatomy gate: probe E compares the RESOLVED config against the estate.

THE WRONG-LAYER INVERSION, measured 2026-08-10. Probe E of
`tools/discovery-scan.py` ("install_<svc>: false while the container is up")
read its flags from `default.config.yml` alone — the committed default — while
the documented config layering says `config.yml` (gitignored, operator-owned)
overrides it. On this host that inverted the probe's verdict twice over:

  * it reported SIXTEEN services as "switched off but running" — every one of
    them `install_*: true` in config.yml, i.e. running because they are
    ENABLED. Committed-default-vs-estate is *expected* drift for every
    config.yml-enabled service, not a contradiction;
  * it MISSED the one service the operator actually switched off:
    `install_mailpit: false` in config.yml with `iiab-mailpit-1` up — the
    genuine hidden_fees/01 instance on this host.

The sixteen-name figure then propagated into docs/hidden_fees/01, the
prune-disabled.yml header, and three remediation-queue amendments before
anyone re-derived it. A probe that measures the wrong layer does not merely
miscount — it manufactures a believable narrative.

The cure is `resolved_install_flags()`: role defaults first, then
default.config.yml, then config.yml overlaid when present — the same order
`main.yml`'s vars_files declares, and the layer list `nos_identity` owns. This
gate pins both the resolver's semantics and the fact that probe E actually
calls it (a resolver the probe ignores is the same bug wearing a fix's name).
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCANNER = REPO / "tools" / "discovery-scan.py"


def _scanner():
    spec = importlib.util.spec_from_file_location(
        "discovery_scan_probe_layer_under_test", SCANNER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def scan():
    return _scanner()


def test_override_wins_and_both_layers_are_read(scan, tmp_path) -> None:
    default = tmp_path / "default.config.yml"
    default.write_text(
        "install_foo: false\ninstall_bar: true\ninstall_baz: false\n",
        encoding="utf-8",
    )
    override = tmp_path / "config.yml"
    override.write_text(
        "install_foo: true\ninstall_qux: false\n", encoding="utf-8"
    )
    flags = scan.resolved_install_flags([default, override])
    assert flags["foo"] == "true", (
        "config.yml did not win over default.config.yml — this is exactly the "
        "wrong-layer read that reported sixteen enabled services as zombies"
    )
    assert flags["bar"] == "true" and flags["baz"] == "false", (
        "flags only the committed default declares must survive the overlay"
    )
    assert flags["qux"] == "false", (
        "a flag declared only in config.yml (the mailpit shape on this host: "
        "operator switches OFF something the default ships ON) must be seen"
    )


def test_absent_override_falls_back_to_the_committed_default(scan, tmp_path) -> None:
    """CI and a fresh clone have no config.yml; the probe must still run."""
    default = tmp_path / "default.config.yml"
    default.write_text("install_foo: false\n", encoding="utf-8")
    flags = scan.resolved_install_flags([default, tmp_path / "config.yml"])
    assert flags == {"foo": "false"}


def test_probe_e_calls_the_resolver() -> None:
    """The resolver must be what probe E reads — not a helper beside a raw read.

    AST, not import: the wiring is a property of the source, and a monkeypatched
    module could lie about it.
    """
    tree = ast.parse(SCANNER.read_text(encoding="utf-8"))
    probe = next(
        (
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "probe_disabled_vs_running"
        ),
        None,
    )
    assert probe is not None, "probe_disabled_vs_running is gone from the scanner"
    called = {
        node.func.id
        for node in ast.walk(probe)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "resolved_install_flags" in called, (
        "probe_disabled_vs_running does not call resolved_install_flags() — it "
        "is back to reading a single config layer, which inverts its verdict on "
        "any host that carries a config.yml"
    )
