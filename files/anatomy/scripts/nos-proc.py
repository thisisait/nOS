#!/usr/bin/env python3
"""nos-proc — run systemd --user units on a Linux host that has no systemd.

A container or a cloud agent sandbox (Claude Code on the web: PID 1 is
`process_api`) cannot run `systemctl --user`. The playbook still renders the
SAME unit files into ~/.config/systemd/user/ (pazny.linux.systemd_user); this
reads them and supervises the process, so the unit contract stays single.

    nos-proc start|stop|restart|status|enable|disable|is-active <unit>[.service]
    nos-proc daemon-reload
    nos-proc list

Honoured unit keys: ExecStart, WorkingDirectory, Environment, EnvironmentFile,
Type (simple|oneshot), Restart (no|always|on-failure), RestartSec.

What it is NOT, said out loud rather than discovered: no dependency ordering
(After=/Wants= are ignored), no timers (a `.timer` unit is refused with exit 0
and a NOT-SCHEDULED line — the job is visible as absent, never as green), no
boot persistence (a sandbox restart loses every daemon; re-run the playbook or
`nos-proc start`). docs/cloud-e2e.md §No init system.

State: ~/.nos/proc/<unit>.{pid,log}. The pidfile holds the SUPERVISOR's pid,
which leads its own process group; stop signals the whole group.
"""
from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

UNIT_DIR = Path(os.environ.get("NOS_PROC_UNIT_DIR",
                               Path.home() / ".config" / "systemd" / "user"))
STATE_DIR = Path(os.environ.get("NOS_PROC_STATE_DIR", Path.home() / ".nos" / "proc"))


def _unit_name(arg: str) -> str:
    return arg if "." in arg else f"{arg}.service"


def parse_unit(path: Path) -> dict:
    """Parse the [Service] section. Repeated keys (Environment) accumulate."""
    svc: dict = {"Environment": [], "EnvironmentFile": []}
    section = None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section != "Service" or "=" not in line:
            continue
        key, _, val = line.partition("=")
        if key in ("Environment", "EnvironmentFile"):
            svc[key].append(val)
        else:
            svc[key] = val
    return svc


def _env_assignments(val: str) -> dict:
    out = {}
    for tok in shlex.split(val):
        k, sep, v = tok.partition("=")
        if sep:
            out[k] = v
    return out


def build_env(svc: dict) -> dict:
    env = dict(os.environ)
    for val in svc["Environment"]:
        env.update(_env_assignments(val))
    for val in svc["EnvironmentFile"]:
        optional = val.startswith("-")
        p = Path(val.lstrip("-"))
        if not p.is_file():
            if optional:
                continue
            raise SystemExit(f"nos-proc: EnvironmentFile missing: {p}")
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                env.update(_env_assignments(line))
    return env


def _pidfile(unit: str) -> Path:
    return STATE_DIR / f"{unit}.pid"


def _logfile(unit: str) -> Path:
    return STATE_DIR / f"{unit}.log"


def running_pid(unit: str) -> int | None:
    pf = _pidfile(unit)
    try:
        pid = int(pf.read_text().strip())
        os.kill(pid, 0)
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return None
    # A dead supervisor whose parent never reaps it is a zombie, and kill(0)
    # still succeeds on a zombie. Without an init system PID 1 may be exactly
    # the process that does not reap (a cloud sandbox), so read the state.
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        if stat.rsplit(")", 1)[1].split()[0] in ("Z", "X"):
            return None
    except (FileNotFoundError, IndexError):
        pass
    return pid


def supervise(unit: str) -> None:
    """Child of `start`: owns the service process, respawns per Restart=."""
    svc = parse_unit(UNIT_DIR / unit)
    argv = shlex.split(svc["ExecStart"].lstrip("@-+!:"))
    restart = svc.get("Restart", "no")
    delay = float(svc.get("RestartSec", "3").rstrip("s") or 3)
    cwd = svc.get("WorkingDirectory") or str(Path.home())
    cwd = cwd.lstrip("-").replace("~", str(Path.home()), 1)
    child: subprocess.Popen | None = None
    stopping = False

    # The handler only records the request and forwards it. Waiting here would
    # nest inside the main loop's child.wait(), which holds Popen's waitpid
    # lock — the inner wait spins until its timeout (measured: 10 s per stop).
    def _term(_sig, _frm):
        nonlocal stopping
        stopping = True
        if child and child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)
    while not stopping:
        env = build_env(parse_unit(UNIT_DIR / unit))  # re-read: rotated secrets land on restart
        print(f"[nos-proc] {time.strftime('%FT%T')} exec {argv}", flush=True)
        child = subprocess.Popen(argv, cwd=cwd, env=env)
        rc = child.wait()
        print(f"[nos-proc] {time.strftime('%FT%T')} exited rc={rc}", flush=True)
        if stopping or restart == "no" or (restart == "on-failure" and rc == 0):
            return
        time.sleep(delay)


def start(unit: str) -> int:
    path = UNIT_DIR / unit
    if unit.endswith(".timer"):
        print(f"nos-proc: {unit} NOT-SCHEDULED — no init system runs timers here")
        return 0
    if not path.is_file():
        print(f"nos-proc: no such unit {path}", file=sys.stderr)
        return 5
    svc = parse_unit(path)
    if running_pid(unit):
        return 0
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if svc.get("Type") == "oneshot":
        with open(_logfile(unit), "ab") as log:
            argv = shlex.split(svc["ExecStart"].lstrip("@-+!:"))
            return subprocess.call(argv, cwd=svc.get("WorkingDirectory") or None,
                                   env=build_env(svc), stdout=log, stderr=log,
                                   stdin=subprocess.DEVNULL)
    log = open(_logfile(unit), "ab")
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "_supervise", unit],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         start_new_session=True, close_fds=True)
    _pidfile(unit).write_text(str(p.pid))
    time.sleep(0.5)
    if p.poll() is not None and svc.get("Restart", "no") == "no":
        print(f"nos-proc: {unit} exited immediately (rc={p.returncode}); see {_logfile(unit)}",
              file=sys.stderr)
        return 1
    return 0


def stop(unit: str) -> int:
    pid = running_pid(unit)
    if pid:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        for _ in range(100):
            if running_pid(unit) is None:
                break
            time.sleep(0.1)
        else:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    _pidfile(unit).unlink(missing_ok=True)
    return 0


def main(argv: list[str]) -> int:
    # Accept and drop systemctl-style flags so call sites can swap the command.
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    cmd, units = args[0], [_unit_name(u) for u in args[1:]]
    if cmd == "_supervise":
        supervise(units[0])
        return 0
    if cmd == "daemon-reload":
        return 0
    if cmd == "list":
        for p in sorted(UNIT_DIR.glob("*.service")):
            state = "active" if running_pid(p.name) else "inactive"
            print(f"{p.name:60} {state}")
        return 0
    rc = 0
    for unit in units:
        if cmd in ("start", "enable"):
            # `enable --now` is start; a bare `enable` is a no-op without an
            # init to persist it, and starting is what every caller wants.
            rc |= start(unit) if (cmd == "start" or "--now" in argv) else 0
        elif cmd in ("stop", "disable"):
            rc |= stop(unit) if (cmd == "stop" or "--now" in argv) else 0
        elif cmd == "restart":
            stop(unit)
            rc |= start(unit)
        elif cmd in ("status", "is-active"):
            pid = running_pid(unit)
            print("active" if pid else "inactive")
            if cmd == "status" and _logfile(unit).is_file():
                print("".join(_logfile(unit).read_text(errors="replace").splitlines(True)[-15:]))
            rc |= 0 if pid else 3
        else:
            print(f"nos-proc: unsupported command {cmd}", file=sys.stderr)
            return 2
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
