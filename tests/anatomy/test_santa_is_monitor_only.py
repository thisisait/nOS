"""Santa is telemetry: MONITOR mode only, and its reader never reports blind as green.

Row santa-monitor (epic workload-allowlist; the 2026-10-03 Fable review): a lockdown
generated from declared state either blocks the operator's interpreted tools and
weekly brew upgrades or allows everything that matters. So pazny.mac.santa renders
NO configuration (ClientMode defaults to 1 = Monitor), stops if anything else set a
mode, and tools/santa-status.py judges EXEC lines against the Pulse runner's trees.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
ROLE = REPO / "roles" / "pazny.mac.santa"
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def _reader():
    spec = importlib.util.spec_from_file_location("_santa_status", REPO / "tools" / "santa-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _line(path: str, decision: str = "ALLOW", ts: datetime = NOW - timedelta(hours=1)) -> str:
    stamp = ts.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return (f"[{stamp}] I santad: action=EXEC|decision={decision}|reason=UNKNOWN|sha256=ab|pid=1"
            f"|pidversion=1|ppid=1|uid=501|user=op|gid=20|group=staff|mode=M|path={path}|args=x y")


def test_the_reader_judges_against_the_declared_trees():
    mod = _reader()
    trees = mod.declared_trees()
    lines = [_line("/opt/homebrew/bin/jq"), _line("/usr/bin/curl"),
             _line(str(REPO / "tools" / "red-status.py")),
             _line("/tmp/dropper"), _line("/tmp/dropper"),
             _line("/Users/op/Downloads/x", ts=NOW - timedelta(days=3)),
             _line("/usr/bin/true", decision="DENY")]
    got = mod.judge(lines, trees, NOW - timedelta(hours=24))
    assert [(r["path"], r["count"]) for r in got["outside"]] == [("/tmp/dropper", 2)]
    assert [d["path"] for d in got["denied"]] == ["/usr/bin/true"]


def test_the_dev_toolchain_is_its_own_set_not_red():
    """2026-10-04: pyenv python ×2264, claude, nvm node read as 3 strangers on the
    first live day. They are declared (santa_dev_toolchain_trees), shown apart."""
    mod = _reader()
    home = str(Path.home())
    dev = tuple(f"{home}/{t}" for t in mod.ni_default("santa_dev_toolchain_trees"))
    lines = [_line(f"{home}/.pyenv/versions/3.13.13/bin/python3.13"), _line(f"{home}/.cargo/bin/evil")]
    got = mod.judge(lines, mod.declared_trees(), NOW - timedelta(hours=24), dev)
    assert [r["path"] for r in got["outside"]] == [f"{home}/.cargo/bin/evil"]
    assert [d["path"] for d in got["dev_toolchain"]] == [f"{home}/.pyenv/versions/3.13.13/bin/python3.13"]
    assert all(d.startswith(f"{home}/") for d in mod.dev_trees()), "dev trees resolve under $HOME"


@pytest.fixture
def estate(tmp_path, monkeypatch):
    mod = _reader()
    santactl = tmp_path / "santactl"
    log = tmp_path / "santa.log"
    log.write_text(_line("/tmp/dropper") + "\n")

    def mode(m: str):
        santactl.write_text(f"#!/bin/sh\necho '{json.dumps({'daemon': {'mode': m}})}'\n")
        santactl.chmod(0o755)
    mode("Monitor")
    monkeypatch.setattr(mod, "SANTACTL", str(santactl))
    monkeypatch.setattr(mod, "LOG", log)
    monkeypatch.setattr(mod, "resolve_flag", lambda flag: [("default.config.yml", "true")])
    return mod, log, mode, santactl


def test_an_unreadable_log_is_unknown_not_green(estate):
    mod, log, _mode, _ = estate
    log.chmod(0o000)
    try:
        report = mod.collect(now=NOW)
    finally:
        log.chmod(0o600)
    assert any(str(log) in m for m in report["sources_missing"]), report
    assert "outside" not in report


def test_a_mode_other_than_monitor_is_red(estate):
    mod, _log, mode, _ = estate
    mode("Lockdown")
    assert any("Lockdown" in s for s in mod.summary(mod.collect(now=NOW)))


def test_declared_but_absent_is_red_and_undeclared_absent_is_silent(estate, monkeypatch):
    mod, _log, _mode, santactl = estate
    santactl.unlink()
    assert mod.summary(mod.collect(now=NOW)) == ["Santa declared (install_santa) but not installed"]
    monkeypatch.setattr(mod, "resolve_flag", lambda flag: [("default.config.yml", "false")])
    report = mod.collect(now=NOW)
    assert mod.summary(report) == [] and report["sources_missing"] == []


def test_the_role_renders_no_mode_and_stops_on_anything_but_monitor():
    # No template, no profile: nothing this role ships can carry a ClientMode.
    assert not (ROLE / "templates").exists() and not (ROLE / "files").exists()
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    flat = [t for t in tasks for t in ([t] + t.get("block", []))]
    santactl = [t["ansible.builtin.command"]["argv"] for t in flat
                if "santactl" in str(t.get("ansible.builtin.command", {}).get("argv", ""))]
    assert santactl and all(a[1] == "status" for a in santactl), santactl
    gate = next(t for t in flat if "ansible.builtin.assert" in t and "verify" in t.get("tags", []))
    assert gate["ansible.builtin.assert"]["that"] == "(santa_status.stdout | from_json).daemon.mode == 'Monitor'"
    dl = next(t["ansible.builtin.get_url"] for t in flat if "ansible.builtin.get_url" in t)
    assert dl["checksum"] == "sha256:{{ santa_pkg_sha256 }}"


def test_santa_ships_off_with_a_pinned_digest():
    cfg = yaml.safe_load((REPO / "default.config.yml").read_text())
    assert cfg["install_santa"] is False
    assert len(cfg["santa_pkg_sha256"]) == 64 and cfg["santa_version"]


def test_the_pkg_root_installs_is_root_downloaded_and_verified():
    """Review 2026-10-04: the pkg landed in /tmp as the operator, was checksummed as
    the operator, then `installer` ran it as root — a swap in between is root.
    Parse the role: download + check under become, into a root dir, not /tmp."""
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text(encoding="utf-8"))
    flat = [t for t in tasks for t in (t.get("block") or [t])]
    get = next(t for t in flat if "ansible.builtin.get_url" in t)
    inst = next(t for t in flat if "/usr/sbin/installer" in str(t))
    defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text(encoding="utf-8"))
    pkg = inst["ansible.builtin.command"]["argv"][2]
    resolved = pkg.replace("{{ santa_pkg_cache }}", str(defaults.get("santa_pkg_cache", "")))
    assert not resolved.startswith(("/tmp", "/private/tmp", "/var/tmp")), resolved
    assert get["ansible.builtin.get_url"]["dest"] == pkg, "install exactly what was verified"
    assert get.get("become") is True and get["ansible.builtin.get_url"].get("checksum")
    assert get["ansible.builtin.get_url"].get("owner") == "root"
    d = next(t for t in flat if "ansible.builtin.file" in t)["ansible.builtin.file"]
    assert (d["owner"], d["mode"]) == ("root", "0700") and defaults["santa_pkg_cache"].startswith(
        "{{ santa_pkg_dir }}/"), "the pkg's directory must be root-only"
