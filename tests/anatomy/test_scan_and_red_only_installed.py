"""The security scan and red-status speak only of what this host installed.

MEASURED 2026-10-15 on a core host (profiles/core.yml): red-status listed
scan_failed for bluesky_pds, mailpit, mariadb, spacetimedb — none installed,
because scan-runner.sh batched every key of a notebook seeded from the
maintainer's estate. And with the Pulse daemon not loaded it printed ~30
"was due and did not fire" lines: one cause, thirty symptoms.

Installed = nos_identity's one derivation (manifest row + resolved install_*),
here core's flags over the defaults. Pulse liveness is a fake probe result.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "profiles" / "core.yml"
RUNNER = REPO / "files" / "vuln-scan" / "scan-runner.sh"
SEED = REPO / "docs" / "llm" / "security" / "scan-state.json"
NOT_ON_CORE = {"bluesky_pds", "mailpit", "mariadb", "spacetimedb", "freepbx", "nginx"}

sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

_spec = importlib.util.spec_from_file_location("red_status", REPO / "tools" / "red-status.py")
red = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(red)


def _core_flags() -> dict:
    return ni.install_flags(ni.profile_layers(CORE))


def _targets(state: Path, batch: int) -> list[str]:
    return ni.scan_batch(state, batch, _core_flags())


def test_core_scans_only_its_installed_components(tmp_path: Path) -> None:
    """The real seed notebook's keys, batched by the function scan-runner.sh calls."""
    picked = set(_targets(SEED, 999))
    assert not picked & NOT_ON_CORE, f"core would scan what it did not install: {picked & NOT_ON_CORE}"
    assert {"traefik", "authentik", "postgres", "postgresql", "wing"} <= picked, picked


def test_batch_is_oldest_first_among_installed(tmp_path: Path) -> None:
    comps = {"mariadb": {"last_checked": None}, "traefik": {"last_checked": "2026-01-02T00:00:00Z"},
             "authentik": {"last_checked": "2026-01-01T00:00:00Z"}, "keap": {"last_checked": "2026-03-01T00:00:00Z"}}
    state = tmp_path / "scan-state.json"
    state.write_text(json.dumps({"components": comps}))
    assert _targets(state, 2) == ["authentik", "traefik"]


def test_scan_runner_takes_its_batch_from_scan_batch(tmp_path: Path) -> None:
    """Run the runner's own batch snippet (this checkout's layers) on an empty notebook."""
    m = re.search(r"^BATCH=\$\(python3 -c '(.*?)'", RUNNER.read_text(), re.MULTILINE | re.DOTALL)
    assert m and "scan_batch" in m.group(1), "scan-runner.sh batches without the installed set"
    state = tmp_path / "scan-state.json"
    state.write_text(json.dumps({"components": {"freepbx": {}}}))
    run = subprocess.run([sys.executable, "-c", m.group(1), str(REPO / "tools"), str(state), "5"],
                         capture_output=True, text=True)
    assert run.returncode == 0 and run.stdout.strip() == "", run


def test_red_status_drops_scan_failed_of_uninstalled(tmp_path: Path, monkeypatch) -> None:
    comps = {n: {"status": "scan_failed"} for n in [*NOT_ON_CORE, "traefik"]}
    state = tmp_path / "scan-state.json"
    state.write_text(json.dumps({"components": comps, "last_full_scan": "2026-10-15T00:00:00Z"}))
    monkeypatch.setattr(red, "SCAN_STATE", state)
    scan = red.security_scan(flags=_core_flags())
    assert scan["scan_failed"] == ["traefik"], scan


def test_red_status_keeps_scan_failed_when_flags_unknown(tmp_path: Path, monkeypatch) -> None:
    """No installed set = UNKNOWN: every scan_failed stays, never silently dropped."""
    state = tmp_path / "scan-state.json"
    state.write_text(json.dumps({"components": {"mailpit": {"status": "scan_failed"}}}))
    monkeypatch.setattr(red, "SCAN_STATE", state)
    assert red.security_scan(flags=None)["scan_failed"] == ["mailpit"]


OVERDUE = [{"job": f"x:job-{i}", "schedule": "* * * * *", "due_at": "2026-10-15T00:00:00Z",
            "overdue_by": "3 h", "last_fired": None} for i in range(30)]


def test_pulse_down_collapses_overdue_to_one_line() -> None:
    pulse = red.judge_pulse((113, "Could not find service"), "launchctl print gui/501/eu.thisisait.nos.pulse")
    assert pulse["running"] is False
    lines = red.reds({"overdue_jobs": OVERDUE, "pulse": pulse})
    assert not [ln for ln in lines if "did not fire" in ln], lines
    one = [ln for ln in lines if "Pulse is not running" in ln]
    assert len(one) == 1 and "launchctl print" in one[0] and "30" in one[0], lines


def test_pulse_up_lists_overdue_jobs_as_today() -> None:
    pulse = red.judge_pulse((0, "state = running\n\tpid = 4242\n"), "launchctl print gui/501/x")
    assert pulse["running"] is True
    lines = red.reds({"overdue_jobs": OVERDUE, "pulse": pulse})
    assert len([ln for ln in lines if "did not fire" in ln]) == 30
    assert not [ln for ln in lines if "Pulse is not running" in ln]


def test_pulse_unknown_is_not_green() -> None:
    pulse = red.judge_pulse(None, "launchctl print gui/501/x")
    assert pulse["running"] is None
    lines = red.reds({"overdue_jobs": OVERDUE, "pulse": pulse})
    assert len([ln for ln in lines if "did not fire" in ln]) == 30


def test_infra_main_yml_switches_on_counts_as_installed() -> None:
    """redis's flag is redis_docker, and main.yml's set_fact turns redis/postgresql on for
    Authentik (REVIEW I3: core and the defaults dropped redis, the defaults postgresql)."""
    seed = json.loads(SEED.read_text())["components"]
    for layers in (_core_flags(), ni.install_flags(ni.profile_layers(REPO / "profiles" / "all-on.yml")),
                   ni.install_flags([p for p in ni.layer_paths() if p.name != "config.yml"])):
        assert {"redis", "postgres", "postgresql"} <= set(ni.installed_names(seed, layers)), layers


def test_nginx_key_follows_install_nginx_not_apex_image() -> None:
    """'nginx' is host nginx (install_nginx), not apex's nginx image."""
    assert ni.installed_names(["nginx"], {"install_nginx": True, "install_apex": False}) == ["nginx"]
    assert ni.installed_names(["nginx"], {"install_nginx": False, "install_apex": True}) == []
