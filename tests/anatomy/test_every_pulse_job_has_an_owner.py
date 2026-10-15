"""Every Pulse job, loop and plugin resolves to an owning install flag.

MEASURED 2026-10-15: eight plugins (discovery, gitleaks, invoice-vision, ...)
declared no requires.feature_flag, and every agent and loop job was emitted
installed whatever the host ran — a core host scheduled the maintainer's
development loops. Owned = the catalog drops the entry with every flag off;
declared = it keeps the entry with every declared flag on. Ruling 2026-10-15:
Pulse is core, the development loops (install_loops) are not.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

CATALOG = REPO / "files/anatomy/scripts/discover-pulse-catalog.py"
PLUGINS = {p.parent.name: yaml.safe_load(p.read_text(encoding="utf-8")) or {}
           for p in (REPO / "files/anatomy/plugins").glob("*/plugin.yml")}
LOOPS = sorted((REPO / "files/anatomy/loops").glob("*.loop.yml"))
DEFAULTS = [p for p in ni.layer_paths() if p != REPO / "config.yml"]
#: Development-loop jobs and invoice-vision (needs Ollama), each a core-host stray.
NOT_ON_CORE = {"loop:repo-check", "loop:news-scout", "loop:vision-bench", "loop:pipeline-exercise",
               "loop-base:propose", "loop-base:drive", "loop-base:review",
               "surveyor:surface-survey", "upgrade-architect:recipe-author",
               "invoice-vision-base:intake-sweep"}


def _catalog(flags: dict) -> dict[str, bool]:
    env = {**os.environ, "NOS_PLAYBOOK_DIR": str(REPO), "NOS_INSTALL_FLAGS": json.dumps(flags)}
    out = subprocess.run([sys.executable, str(CATALOG)], capture_output=True, text=True, env=env, check=True)
    return {f"{e['plugin_name']}:{e['job']['name']}": e["installed"] for e in json.loads(out.stdout)}


def test_no_job_runs_with_every_flag_off() -> None:
    ownerless = sorted(j for j, on in _catalog({}).items() if on)
    assert not ownerless, f"Pulse jobs no install flag owns: {ownerless}"


def test_every_owner_is_a_declared_flag() -> None:
    every = {f: True for f in ni.install_flags(DEFAULTS)}
    dead = sorted(j for j, on in _catalog(every).items() if not on)
    assert not dead, f"owned by a flag no default layer declares (never runs): {dead}"


def test_every_plugin_has_an_owner() -> None:
    ownerless = sorted(n for n in PLUGINS if ni.plugin_installed(n, PLUGINS, {}))
    assert not ownerless, f"plugins with no owning install flag: {ownerless}"


def test_every_loop_has_a_declared_owner() -> None:
    declared = set(ni.install_flags(DEFAULTS))
    bad = [p.name for p in LOOPS if (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("owner") not in declared]
    assert not bad, f"loops with no declared owner flag: {bad}"


def test_core_runs_pulse_but_not_the_development_loops() -> None:
    flags = ni.install_flags(ni.profile_layers(REPO / "profiles" / "core.yml"))
    assert flags.get("install_pulse") is True and flags.get("install_loops") is False, flags
    on = {j for j, v in _catalog(flags).items() if v}
    assert not on & NOT_ON_CORE, f"core would schedule {sorted(on & NOT_ON_CORE)}"
    assert {"wing-base:dispatch-notifications", "keap-base:keap-embed-sync"} <= on


def test_the_defaults_run_the_development_loops() -> None:
    on = {j for j, v in _catalog(ni.install_flags(DEFAULTS)).items() if v}
    assert {"loop:repo-check", "loop-base:drive"} <= on
