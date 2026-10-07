"""`tools/undeclared-status.py`: a declaration explains what the owner runs beside nOS.

MEASURED 2026-10-07, converge day: 16 undeclared on the operator host, red every
session. Two of them nOS installed and never said how to recognise (the
Tailscale cask's system extension listens on two ports; its manifest row knew it
only as prose, `host_process`). The rest are habitat (lexicon): Spotify, Steam,
Epic, Google's updaters, OpenVPN, Docker Desktop's privileged helpers — the
machine owner's software, and the owner had NO place to declare it, so the
reader could only keep shouting. Fixed at the cause: a row declares the
programs it runs (`host_programs`, matched by executable basename), and the
owner declares theirs in config.yml (`habitat_processes`, a launchd label or an
executable name) — read through the config layers like every other declaration,
default empty in the host-desktop layer beside santa_dev_toolchain_trees.
Fixtures only, never the live host.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "undeclared-status.py"
SYSEXT = "io.tailscale.ipn.macsys.network-extension"
SYSEXT_EXE = f"/Library/SystemExtensions/B5068DF6/{SYSEXT}.systemextension/Contents/MacOS/{SYSEXT}"


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_list_var_resolves_through_the_layers_last_wins(tmp_path):
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity as ni  # noqa: PLC0415
    low, high = tmp_path / "a.yml", tmp_path / "b.yml"
    low.write_text("habitat_processes: []\n")
    high.write_text("habitat_processes:\n  - com.google.keystone.agent\n  - Spotify\n")
    assert ni.resolve_list("habitat_processes", [low, high]) == ["com.google.keystone.agent", "Spotify"]
    assert ni.resolve_list("habitat_processes", [high, low]) == [], "the last layer wins, even when empty"
    assert ni.resolve_list("nope", [low]) == []


def test_the_default_is_an_empty_list_in_the_host_desktop_layer():
    doc = yaml.safe_load((REPO / "config.d" / "10-host-desktop.yml").read_text(encoding="utf-8"))
    assert doc.get("habitat_processes") == [], "the owner's declaration surface: default empty, config.yml fills it"


def test_a_declared_program_is_matched_by_its_basename():
    mod = _load(TOOL, "_hab_a")
    rows = [{"addr": "*", "port": 57621, "pid": 8, "ppid": 1, "exe": "/Applications/Spotify.app/Contents/MacOS/Spotify"},
            {"addr": "*", "port": 49640, "pid": 9, "ppid": 1, "exe": SYSEXT_EXE}]
    assert len(mod.judge_ports(rows, set(), set())) == 2, "fixture must be undeclared without a declaration"
    assert not mod.judge_ports(rows, set(), set(), frozenset({"Spotify", SYSEXT}))


def test_the_tailscale_row_declares_its_system_extension():
    mod = _load(TOOL, "_hab_b")
    rows = {r["id"]: r for r in yaml.safe_load((REPO / "state/manifest.yml").read_text(encoding="utf-8"))["services"]}
    assert SYSEXT in (rows["tailscale"].get("host_programs") or []), "the cask's listener, declared on its row"
    assert SYSEXT in mod.declared_programs()


def test_collect_tolerates_what_the_owner_and_the_rows_declare(monkeypatch):
    """The wiring, with every live probe replaced: a habitat label and a habitat
    executable are declared; a stranger beside them is still named."""
    mod = _load(TOOL, "_hab_c")
    monkeypatch.setattr(mod, "declared_labels", lambda: {"eu.thisisait.nos.bone"})
    monkeypatch.setattr(mod, "declared_ports", lambda: set())
    monkeypatch.setattr(mod, "declared_programs", lambda: frozenset({SYSEXT}))
    monkeypatch.setattr(mod, "habitat", lambda: frozenset({"com.google.keystone.agent", "Spotify"}))
    monkeypatch.setattr(mod, "loaded_labels", lambda: {"eu.thisisait.nos.bone": 500, "com.vendor.agent": 501})
    monkeypatch.setattr(mod, "plist_files", lambda: {
        "com.google.keystone.agent": {"path": "/u/L/k.plist", "program": "?"},
        "com.vendor.agent": {"path": "/u/L/v.plist", "program": "/v"}})
    monkeypatch.setattr(mod, "listeners", lambda: [
        {"addr": "*", "port": 57621, "pid": 8, "ppid": 1, "exe": "/Applications/Spotify.app/Contents/MacOS/Spotify"},
        {"addr": "*", "port": 49640, "pid": 9, "ppid": 1, "exe": SYSEXT_EXE},
        {"addr": "*", "port": 18080, "pid": 10, "ppid": 1, "exe": "/opt/x/node"}])
    monkeypatch.setattr(mod, "crontab", lambda: [])
    report = mod.collect()
    assert report["sources_missing"] == []
    assert [d["label"] for d in report["launchd"]] == ["com.vendor.agent"]
    assert [p["port"] for p in report["ports"]] == [18080]
