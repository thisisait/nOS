"""A host that installed a kernel fix and still runs the old kernel is red, with how long it waited.

Measured 2026-11-03: a remote kernel CVE (fixed in 6.8.0-149) reached nothing in red-status;
unattended-upgrades installs with Automatic-Reboot false and no reader said a reboot was pending.
Executed: red-status's own _sibling()/reds() over a fake host root, kernel and apt.
"""
from __future__ import annotations

import importlib.util
import os
import stat
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _red():
    spec = importlib.util.spec_from_file_location("_red_hostpatch", REPO / "tools/red-status.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _host(tmp_path, monkeypatch, apt_out="Listing...\n", apt_rc=0):
    (tmp_path / "var/run").mkdir(parents=True)
    (tmp_path / "boot").mkdir()
    for k in ("6.8.0-140-generic", "6.8.0-149-generic"):
        (tmp_path / "boot" / f"vmlinuz-{k}").write_text("")
    apt = tmp_path / "apt"
    apt.write_text(f"#!/bin/sh\ncat <<'X'\n{apt_out}X\nexit {apt_rc}\n")
    apt.chmod(apt.stat().st_mode | stat.S_IXUSR)
    for k, v in {"NOS_HOST_PLATFORM": "linux", "NOS_HOST_ROOT": str(tmp_path),
                 "NOS_HOST_KERNEL": "6.8.0-140-generic", "NOS_APT": str(apt)}.items():
        monkeypatch.setenv(k, v)


def _lines():
    red = _red()
    hp = red._sibling("host-patch")
    return red.reds({"host_patch": hp["items"]}), hp["missing"]


def test_a_reboot_pending_three_days_and_a_stale_kernel_are_named(tmp_path, monkeypatch):
    _host(tmp_path, monkeypatch, apt_out="openssl/noble-updates,noble-security 3.0.13-0ubuntu3.6 amd64\n")
    flag = tmp_path / "var/run/reboot-required"
    flag.write_text("*** System restart required ***\n")
    (tmp_path / "var/run/reboot-required.pkgs").write_text("linux-image-6.8.0-149-generic\n")
    old = time.time() - 3 * 86400 - 60
    os.utime(flag, (old, old))
    lines, missing = _lines()
    text = "\n".join(lines)
    assert missing == []
    assert "reboot pending 3 days (linux-image-6.8.0-149-generic)" in text
    assert "running kernel 6.8.0-140-generic but 6.8.0-149-generic is installed" in text
    assert "1 -security update(s) pending: openssl" in text


def test_a_patched_host_is_quiet(tmp_path, monkeypatch):
    _host(tmp_path, monkeypatch)
    monkeypatch.setenv("NOS_HOST_KERNEL", "6.8.0-149-generic")
    lines, missing = _lines()
    assert missing == [] and not any(ln.startswith("host:") for ln in lines)


def test_an_unanswering_apt_and_an_empty_boot_are_unknown(tmp_path, monkeypatch):
    _host(tmp_path, monkeypatch, apt_rc=100)
    for p in (tmp_path / "boot").iterdir():
        p.unlink()
    _, missing = _lines()
    assert any("apt list" in m for m in missing) and any("vmlinuz" in m for m in missing)


def test_off_linux_the_reader_says_unknown(monkeypatch, capsys):
    monkeypatch.setenv("NOS_HOST_PLATFORM", "darwin")
    spec = importlib.util.spec_from_file_location("_hp", REPO / "tools/host-patch-status.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr("sys.argv", ["host-patch-status.py"])
    assert m.main() == 0 and capsys.readouterr().out.startswith("UNKNOWN")
