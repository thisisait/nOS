"""nos-proc reads the SAME unit file systemd would, and runs what it says.

A Linux host without systemd (a container, a Claude cloud sandbox — PID 1 is
`process_api`) gets its host daemons from files/anatomy/scripts/nos-proc.py
instead of `systemctl --user` (tasks/_platform.yml → nos_init == 'none'). The
unit contract stays single: pazny.linux.systemd_user renders one file, and the
two readers must agree on what it means. These gates run a real process.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NOS_PROC = REPO / "files" / "anatomy" / "scripts" / "nos-proc.py"

UNIT = """[Unit]
Description=probe
After=network-online.target

[Service]
Type=simple
WorkingDirectory={wd}
Environment="PROBE_A=alpha"
Environment="PROBE_B=two words"
EnvironmentFile={envfile}
ExecStart={py} -c "import os,time,pathlib; pathlib.Path('out.txt').write_text(os.environ['PROBE_A']+'|'+os.environ['PROBE_B']+'|'+os.environ['PROBE_C']); time.sleep(60)"
Restart=always
RestartSec=1

[Install]
WantedBy=default.target
"""


def _run(tmp: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ,
               NOS_PROC_UNIT_DIR=str(tmp / "units"),
               NOS_PROC_STATE_DIR=str(tmp / "state"))
    return subprocess.run([sys.executable, str(NOS_PROC), *args], env=env,
                          capture_output=True, text=True, timeout=30)


def _unit(tmp: Path) -> None:
    (tmp / "units").mkdir()
    (tmp / "wd").mkdir()
    (tmp / "probe.env").write_text("# comment\nPROBE_C=from-file\n")
    (tmp / "units" / "probe.service").write_text(UNIT.format(
        wd=tmp / "wd", envfile=tmp / "probe.env", py=sys.executable))


def _wait_for(path: Path, timeout: float = 10.0) -> str:
    end = time.time() + timeout
    while time.time() < end:
        if path.is_file() and path.read_text():
            return path.read_text()
        time.sleep(0.1)
    raise AssertionError(f"{path} never written")


def test_start_honours_env_envfile_and_workdir(tmp_path):
    _unit(tmp_path)
    try:
        assert _run(tmp_path, "start", "probe.service").returncode == 0
        out = _wait_for(tmp_path / "wd" / "out.txt")
        assert out == "alpha|two words|from-file"
        assert _run(tmp_path, "is-active", "probe").stdout.strip() == "active"
    finally:
        _run(tmp_path, "stop", "probe.service")
    assert _run(tmp_path, "is-active", "probe").returncode == 3


def test_systemctl_flags_are_accepted_so_call_sites_can_swap(tmp_path):
    """Handlers call `{{ nos_user_systemctl }} disable --now X` — the same
    argv they give systemctl. A flag nos-proc does not know must not be read
    as a unit name."""
    _unit(tmp_path)
    try:
        assert _run(tmp_path, "enable", "--now", "probe.service").returncode == 0
        _wait_for(tmp_path / "wd" / "out.txt")
        assert _run(tmp_path, "disable", "--now", "probe.service").returncode == 0
        assert _run(tmp_path, "is-active", "probe").returncode == 3
    finally:
        _run(tmp_path, "stop", "probe.service")


def test_a_timer_is_reported_absent_not_green(tmp_path):
    (tmp_path / "units").mkdir()
    (tmp_path / "units" / "x.timer").write_text("[Timer]\nOnCalendar=daily\n")
    r = _run(tmp_path, "start", "x.timer")
    assert r.returncode == 0
    assert "NOT-SCHEDULED" in r.stdout


def test_a_missing_unit_fails_loudly(tmp_path):
    (tmp_path / "units").mkdir()
    assert _run(tmp_path, "start", "nope.service").returncode != 0


def test_ensure_unit_routes_no_init_hosts_to_nos_proc():
    """The seam: ensure_unit must branch on nos_init, and every raw
    `systemctl --user` call site outside the library must go through
    nos_user_systemctl, or a no-init host silently runs nothing."""
    ensure = (REPO / "roles/pazny.linux.systemd_user/tasks/ensure_unit.yml").read_text()
    assert "nos_init" in ensure and "nos-proc.py" in ensure
    offenders = []
    for base in ("roles", "tasks"):
        for p in (REPO / base).rglob("*.yml"):
            # the library itself, and _platform.yml which DEFINES the swap
            if "pazny.linux.systemd_user" in str(p) or p.name == "_platform.yml":
                continue
            for n, line in enumerate(p.read_text().splitlines(), 1):
                code = line.split("#", 1)[0]
                if "systemctl --user" in code and "nos_user_systemctl" not in code:
                    offenders.append(f"{p.relative_to(REPO)}:{n}")
    main = (REPO / "main.yml").read_text().splitlines()
    for n, line in enumerate(main, 1):
        code = line.split("#", 1)[0]
        if "systemctl --user" in code and "nos_user_systemctl" not in code:
            offenders.append(f"main.yml:{n}")
    assert not offenders, "raw `systemctl --user` bypasses nos_init: " + ", ".join(offenders)
