#!/usr/bin/env python3
"""The host's own answers, asked in one place, per platform.

nOS runs its organs under launchd on macOS and under `systemd --user` on
Ubuntu, with the SAME label (`eu.thisisait.nos.<organ>` is the plist Label and
the unit's base name — roles/pazny.linux.systemd_user). Platform is a fact, not
a toggle (docs/cross-platform.md). Readers that called `launchctl`, `netstat`,
`lsof` or `log` themselves were right on the Mac they were written on and a
FileNotFoundError traceback on the DGX Spark. This is the one place that knows
which binary answers which question; the gate
tests/anatomy/test_readers_ask_the_host_through_one_shim.py keeps it so.

THE CONTRACT. Every probe returns a normalized shape or None, and None means
UNKNOWN — the binary is absent, the user bus is unreachable, the command
failed. A reader renders None as UNKNOWN, never as green and never as "not
running". Nothing here mutates: only `print`, `list`, `show`, `list-units`,
`list-sockets`, `ss -l`, `ps`, `journalctl` reads and file reads.

Probes take `run=` (argv -> (rc, stdout) | None) and `system=` ("Darwin" |
"Linux") so a test feeds fixtures; the parsers are pure functions of text.

SECRETS. `service_definition()` and `service_env()` return environment VALUES,
because a caller needs one (thalamus's socket path, the model id a run is
scored under). Nothing in this module prints them, and no caller may: report a
secret's PRESENCE, never its value. The `env` CLI below exists for
tools/run-agent.sh, which exports the daemon's environment into the agent it
starts — into a pipe, never onto a terminal.

Importable: `sys.path.insert(0, "<repo>/tools"); import nos_host`.
CLI: `nos_host.py env <label>` prints the RUNNING job's environment as
`KEY => value` lines (exit 2 not loaded / not running, 3 unreadable).
"""

from __future__ import annotations

import os
import pathlib
import platform
import plistlib
import re
import shlex
import subprocess
import sys
from typing import Callable, Optional

SYSTEM = platform.system()
HOME = pathlib.Path.home()

Runner = Callable[[list], Optional[tuple]]

#: Where an agent or daemon definition lives, per platform. The last entry of
#: each is the SYSTEM domain: a user-level probe cannot see what is loaded there.
PLIST_DIRS = (HOME / "Library/LaunchAgents", pathlib.Path("/Library/LaunchAgents"),
              pathlib.Path("/Library/LaunchDaemons"))
UNIT_DIRS = (HOME / ".config/systemd/user", pathlib.Path("/etc/systemd/user"),
             pathlib.Path("/etc/systemd/system"))
SYSTEM_DOMAINS = ("/Library/LaunchDaemons", "/etc/systemd/system")

#: A socket systemd (pid 1) holds for socket activation: the OS's own listener.
SYSTEMD_EXE = "/usr/lib/systemd/systemd"
#: The owner of a socket another user holds is not visible to `ss -p` as us.
OWNER_HIDDEN = "?"


def _run(argv: list, timeout: int = 20) -> tuple[int, str] | None:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.returncode, p.stdout


def _unit(label: str) -> str:
    return label if label.endswith((".service", ".timer", ".socket")) else f"{label}.service"


# ── parsers: pure functions of a command's text ──────────────────────────────

def parse_launchctl_print(rc: int, text: str) -> dict:
    """`launchctl print gui/<uid>/<label>` -> {loaded, running, pid, detail}."""
    if rc != 0:
        return {"loaded": False, "running": False, "pid": None, "detail": f"not loaded (rc {rc})"}
    pid = None
    last_exit = None
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("pid =") and pid is None:
            v = s.split("=", 1)[1].strip()
            pid = int(v) if v.isdigit() else None
        elif s.startswith("last exit code =") and last_exit is None:
            last_exit = s.split("=", 1)[1].strip()
    if pid:
        return {"loaded": True, "running": True, "pid": pid, "detail": f"loaded, pid {pid}"}
    tail = f", last exit {last_exit}" if last_exit else ""
    return {"loaded": True, "running": False, "pid": None, "detail": f"loaded, not running{tail}"}


def parse_launchctl_env(text: str) -> dict[str, str]:
    """The `KEY => value` lines of `launchctl print` — the env the job holds."""
    out = {}
    for m in re.finditer(r"^\s*([A-Z][A-Z0-9_]*) => (.*)$", text, re.M):
        out.setdefault(m.group(1), m.group(2).strip())
    return out


def parse_launchctl_list(text: str) -> dict[str, int | None]:
    """`launchctl list` (PID\\tStatus\\tLabel) -> label -> pid (None when not running)."""
    rows = {}
    for line in text.splitlines()[1:]:
        f = line.split("\t")
        if len(f) == 3:
            rows[f[2]] = int(f[0]) if f[0].isdigit() else None
    return rows


def parse_systemctl_show(text: str) -> list[dict[str, str]]:
    """`systemctl show -p A -p B u1 u2` -> one {prop: value} per unit (blank-line separated)."""
    blocks, cur = [], {}
    for line in text.splitlines():
        if not line.strip():
            if cur:
                blocks.append(cur)
            cur = {}
            continue
        k, sep, v = line.partition("=")
        if sep:
            cur[k] = v
    if cur:
        blocks.append(cur)
    return blocks


def state_from_systemd(props: dict[str, str]) -> dict:
    """systemd unit properties -> the same {loaded, running, pid, detail} as launchd.

    `loaded` is LoadState (the unit file is found and parsed — what `launchctl
    list` means by a bootstrapped job); `running` is SubState=running, so a unit
    that is loaded but dead or crash-looping is loaded-not-running, as on launchd.
    """
    load = props.get("LoadState", "")
    active, sub = props.get("ActiveState", ""), props.get("SubState", "")
    pid = int(props["MainPID"]) if props.get("MainPID", "0").isdigit() and props.get("MainPID") != "0" else None
    if load != "loaded":
        return {"loaded": False, "running": False, "pid": None, "detail": f"not loaded ({load or 'no LoadState'})"}
    if sub == "running":
        return {"loaded": True, "running": True, "pid": pid,
                "detail": f"loaded, {active}/{sub}" + (f", pid {pid}" if pid else "")}
    return {"loaded": True, "running": False, "pid": None, "detail": f"loaded, not running ({active}/{sub})"}


def _split_addr(local: str) -> tuple[str, int] | None:
    """`127.0.0.1:631` / `[::]:22` / `*:80` / `127.0.0.53%lo:53` -> (addr, port)."""
    host, sep, port = local.rpartition(":")
    if not sep or not port.isdigit():
        return None
    host = host.split("%", 1)[0].strip("[]")
    return host, int(port)


def parse_ss_listeners(text: str) -> list[dict]:
    """`ss -ltnpH` -> [{addr, port, pid, name}]; pid/name None when not ours to see."""
    rows = []
    for line in text.splitlines():
        f = line.split()
        if len(f) < 4 or f[0] != "LISTEN":
            continue
        hp = _split_addr(f[3])
        if hp is None:
            continue
        m = re.search(r'users:\(\("([^"]*)",pid=(\d+)', line)
        rows.append({"addr": hp[0], "port": hp[1],
                     "pid": int(m.group(2)) if m else None, "name": m.group(1) if m else None})
    return rows


def parse_ss_sockets(text: str) -> list[dict]:
    """`ss -tunapH` -> [{proc, pid, local, peer, state}] for the sockets whose owner we can see."""
    rows = []
    for line in text.splitlines():
        f = line.split()
        m = re.search(r'users:\(\("([^"]*)",pid=(\d+)', line)
        if len(f) < 6 or not m:
            continue
        rows.append({"proc": m.group(1), "pid": int(m.group(2)), "local": f[4], "peer": f[5], "state": f[1]})
    return rows


def parse_netstat_anv(text: str) -> list[dict]:
    """Darwin `netstat -anv -p tcp` LISTEN rows -> [{addr, port, pid}] (every user's sockets)."""
    rows = []
    for line in text.splitlines():
        m = re.match(r"tcp(?:4|6|46)\s+\d+\s+\d+\s+(\S+)\.(\d+)\s+\S+\s+LISTEN\s.*?\s(\S.*?):(\d+)\s+[0-9a-f]{5}\s", line)
        if m:
            rows.append({"addr": m.group(1), "port": int(m.group(2)), "pid": int(m.group(4))})
    return rows


def parse_list_sockets(text: str) -> dict[tuple[str, int], str]:
    """`systemctl list-sockets --all --plain --no-legend` -> (addr, port) -> socket unit."""
    out = {}
    for line in text.splitlines():
        f = line.split()
        if len(f) >= 2 and (hp := _split_addr(f[0])):
            out[hp] = f[1]
    return out


def parse_docker_ports(text: str) -> set[int]:
    """`docker ps --format {{.Ports}}` -> the host ports Docker publishes (any address)."""
    ports = set()
    for m in re.finditer(r"(?:^|[\s,])(?:\[?[0-9a-f:.]*\]?):(\d+)(?:-(\d+))?->\d+(?:-\d+)?/tcp", text):
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        ports |= set(range(lo, hi + 1))
    return ports


def parse_unit_file(text: str) -> dict:
    """A systemd unit -> {argv, environment, environment_files}. Values are never printed."""
    argv, env, files = [], {}, []
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section != "Service":
            continue
        key, sep, val = line.partition("=")
        if not sep:
            continue
        key, val = key.strip(), val.strip()
        if key == "ExecStart" and not argv:
            try:
                argv = shlex.split(val.lstrip("@-:+!"))
            except ValueError:
                argv = val.split()
        elif key == "Environment":
            try:
                pairs = shlex.split(val)
            except ValueError:
                pairs = val.split()
            for p in pairs:
                k, s, v = p.partition("=")
                if s:
                    env[k] = v
        elif key == "EnvironmentFile":
            files.append(val.lstrip("-"))
    return {"argv": argv, "environment": env, "environment_files": files}


def parse_env_file(text: str) -> dict[str, str]:
    """KEY=VALUE lines (systemd EnvironmentFile syntax, quotes stripped)."""
    out = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", ";")):
            continue
        k, sep, v = s.removeprefix("export ").partition("=")
        if sep and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k.strip()):
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            out[k.strip()] = v
    return out


# ── probes: run one command, return the normalized shape or None ─────────────

def service_state(label: str, run: Runner | None = None, system: str | None = None) -> dict | None:
    """An organ's state by label: {loaded, running, pid, detail, source}; None = UNKNOWN."""
    run, system = run or _run, system or SYSTEM
    if system == "Darwin":
        argv = ["launchctl", "print", f"gui/{os.getuid()}/{label}"]
        src = f"launchctl print gui/<uid>/{label}"
        res = run(argv)
        if res is None:
            return None
        return {**parse_launchctl_print(res[0], res[1]), "source": src}
    if system == "Linux":
        argv = ["systemctl", "--user", "show", _unit(label),
                "-p", "Id", "-p", "LoadState", "-p", "ActiveState", "-p", "SubState", "-p", "MainPID"]
        src = f"systemctl --user show {_unit(label)}"
        res = run(argv)
        if res is None or res[0] != 0:
            return None   # no systemctl, or no user bus: not asked is not "not loaded"
        blocks = parse_systemctl_show(res[1])
        if not blocks:
            return None
        return {**state_from_systemd(blocks[0]), "source": src}
    return None


def loaded_services(run: Runner | None = None, system: str | None = None) -> dict[str, int | None] | None:
    """Every job the user's service manager has loaded: label -> pid (None when not running)."""
    run, system = run or _run, system or SYSTEM
    if system == "Darwin":
        res = run(["launchctl", "list"])
        return parse_launchctl_list(res[1]) if res and res[0] == 0 else None
    if system == "Linux":
        res = run(["systemctl", "--user", "list-units", "--type=service", "--all", "--plain", "--no-legend"])
        if res is None or res[0] != 0:
            return None
        units = [f[0] for f in (ln.split() for ln in res[1].splitlines()) if len(f) >= 2 and f[1] == "loaded"]
        if not units:
            return {}
        res = run(["systemctl", "--user", "show", "-p", "Id", "-p", "MainPID", *units])
        if res is None or res[0] != 0:
            return None
        out = {}
        for b in parse_systemctl_show(res[1]):
            if b.get("Id", "").endswith(".service"):
                pid = b.get("MainPID", "0")
                out[b["Id"][: -len(".service")]] = int(pid) if pid.isdigit() and pid != "0" else None
        return out
    return None


def _plist_program(doc: dict) -> str:
    return str(doc.get("Program") or (doc.get("ProgramArguments") or ["?"])[0])


def unit_files(system: str | None = None) -> dict[str, dict]:
    """label -> {path, program} for every agent/daemon definition on disk.

    Darwin: the plists in PLIST_DIRS. Linux: the *.service / *.timer files in
    UNIT_DIRS (a symlink is an alias or a mask, not a definition). Only the
    label and the program path are read — never an environment value.
    """
    system = system or SYSTEM
    found: dict[str, dict] = {}
    if system == "Darwin":
        for d in PLIST_DIRS:
            for p in sorted(d.glob("*.plist")) if d.is_dir() else ():
                try:
                    with p.open("rb") as fh:
                        doc = plistlib.load(fh)
                except Exception:  # noqa: BLE001 — unparseable is still a file on disk
                    doc = {}
                found[str(doc.get("Label") or p.stem)] = {"path": str(p), "program": _plist_program(doc)}
    elif system == "Linux":
        for d in UNIT_DIRS:
            for p in sorted([*d.glob("*.service"), *d.glob("*.timer")]) if d.is_dir() else ():
                if p.is_symlink() or "@" in p.stem:
                    continue
                label = p.stem
                if label in found and p.suffix == ".timer":
                    continue
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                argv = parse_unit_file(text)["argv"]
                found[label] = {"path": str(p), "program": argv[0] if argv else "?"}
                # snapd writes a snap's units from the snap's own declaration and
                # marks them; the distro's package manager, named as such.
                if re.search(r"^X-Snappy=yes\s*$", text, re.M):
                    found[label]["generator"] = "snapd"
    return found


def service_definition(label: str, system: str | None = None) -> dict | None:
    """What the job WILL run: {path, argv, env}. None when the definition is unreadable.

    Darwin: ~/Library/LaunchAgents/<label>.plist (ProgramArguments,
    EnvironmentVariables). Linux: ~/.config/systemd/user/<label>.service
    (ExecStart, Environment=, EnvironmentFile=). `env` carries VALUES — report
    presence, never print one.
    """
    system = system or SYSTEM
    if system == "Darwin":
        path = HOME / "Library/LaunchAgents" / f"{label}.plist"
        try:
            doc = plistlib.loads(path.read_bytes())
        except (OSError, plistlib.InvalidFileException, ValueError):
            return None
        if not isinstance(doc, dict):
            return None
        return {"path": str(path), "argv": [str(a) for a in doc.get("ProgramArguments") or []],
                "env": {str(k): str(v) for k, v in (doc.get("EnvironmentVariables") or {}).items()}}
    if system == "Linux":
        path = HOME / ".config/systemd/user" / _unit(label)
        try:
            unit = parse_unit_file(path.read_text(encoding="utf-8"))
        except OSError:
            return None
        env = {}
        for f in unit["environment_files"]:
            try:
                env.update(parse_env_file(pathlib.Path(f).read_text(encoding="utf-8")))
            except OSError:
                pass   # systemd itself tolerates a "-"-prefixed missing file
        env.update(unit["environment"])
        return {"path": str(path), "argv": unit["argv"], "env": env}
    return None


def service_env(label: str, run: Runner | None = None, system: str | None = None) -> dict[str, str] | None:
    """The environment the RUNNING job holds — not the file it will read at next start.

    Darwin: `launchctl print`'s `KEY => value` block. Linux: /proc/<MainPID>/environ
    (our own process, so readable). None when not loaded, not running, or unreadable.
    """
    run, system = run or _run, system or SYSTEM
    if system == "Darwin":
        res = run(["launchctl", "print", f"gui/{os.getuid()}/{label}"])
        return parse_launchctl_env(res[1]) if res and res[0] == 0 else None
    if system == "Linux":
        st = service_state(label, run=run, system=system)
        if not st or not st.get("pid"):
            return None
        try:
            raw = pathlib.Path(f"/proc/{st['pid']}/environ").read_bytes()
        except OSError:
            return None
        out = {}
        for item in raw.split(b"\0"):
            k, sep, v = item.decode(errors="replace").partition("=")
            if sep:
                out[k] = v
        return out
    return None


def service_log(label: str, lines: int = 2000, grep: str | None = None, run: Runner | None = None,
                system: str | None = None) -> tuple[list[str], str] | None:
    """The job's recent stderr: (lines, source), oldest first. None when unreadable.

    Darwin: the plist's StandardErrorPath, tailed. Linux: the user journal for
    the unit (`journalctl --user -u <unit> -o cat`). `grep` keeps only lines
    containing it — on Linux the journal filters, so a chatty daemon's start
    lines are not pushed out of the window by its request log.
    """
    run, system = run or _run, system or SYSTEM
    keep = (lambda ls: [ln for ln in ls if grep in ln]) if grep else (lambda ls: ls)
    if system == "Darwin":
        d = service_definition(label, system="Darwin")
        path = HOME / "Library/LaunchAgents" / f"{label}.plist"
        try:
            err = plistlib.loads(path.read_bytes()).get("StandardErrorPath")
        except (OSError, plistlib.InvalidFileException, ValueError, AttributeError):
            err = None
        if not d or not err:
            return None
        p = pathlib.Path(err)
        try:
            with p.open("rb") as f:
                f.seek(max(0, p.stat().st_size - (1 << 20)))
                return keep(f.read().decode(errors="replace").splitlines())[-lines:], str(p)
        except OSError:
            return None
    if system == "Linux":
        argv = ["journalctl", "--user", "-u", _unit(label), "-o", "cat", "--no-pager"]
        # `-n` with `--grep` returned matches NEWEST FIRST on systemd 255 (spark1,
        # 2026-10-22), so "the last start line" was a stale one: with a grep the
        # journal filters in order and the tail is cut here instead.
        res = run(argv + (["--grep", grep] if grep else ["-n", str(lines)]))
        # rc 1 with --grep is "no entry matched": an answer, not a failure.
        if res is None or res[0] not in ((0, 1) if grep else (0,)):
            return None
        return keep(res[1].splitlines())[-lines:], f"journalctl --user -u {_unit(label)}"
    return None


def _proc_exe(pid: int, fallback: str | None) -> tuple[int | None, str]:
    """(ppid, executable path) of a Linux process we can see; fallback name otherwise."""
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        exe = fallback or OWNER_HIDDEN
    try:
        stat = pathlib.Path(f"/proc/{pid}/stat").read_text()
        ppid = int(stat.rsplit(")", 1)[1].split()[1])
    except (OSError, IndexError, ValueError):
        ppid = None
    return ppid, exe


def listeners(run: Runner | None = None, system: str | None = None) -> list[dict] | None:
    """Every listening TCP socket: [{addr, port, pid, ppid, exe}]. None = UNKNOWN.

    Darwin: `netstat -anv` sees every user's sockets with their pid (lsof as a
    user does not); `ps` names the program. Linux: `ss -ltnp` names only OUR
    processes. A socket systemd holds for activation (`systemctl list-sockets`)
    is attributed to systemd, one Docker publishes (`docker ps`) to
    docker-proxy, and the rest get exe "?" with pid None: owner not visible to
    this user — a reader says so, it does not guess.
    """
    run, system = run or _run, system or SYSTEM
    if system == "Darwin":
        res = run(["netstat", "-anv", "-p", "tcp"])
        if res is None or res[0] != 0:
            return None
        rows = parse_netstat_anv(res[1])
        pids = ",".join(sorted({str(r["pid"]) for r in rows}))
        procs = {}
        ps = run(["ps", "-o", "pid=,ppid=,comm=", "-p", pids]) if pids else None
        for line in (ps[1] if ps and ps[0] == 0 else "").splitlines():
            try:
                pid, ppid, exe = line.split(None, 2)
                procs[int(pid)] = (int(ppid), exe.strip())
            except ValueError:
                continue
        for r in rows:
            r["ppid"], r["exe"] = procs.get(r["pid"], (None, OWNER_HIDDEN))
        return rows
    if system == "Linux":
        res = run(["ss", "-ltnpH"])
        if res is None or res[0] != 0:
            return None
        rows = parse_ss_listeners(res[1])
        sockets = run(["systemctl", "list-sockets", "--all", "--plain", "--no-legend"])
        held = parse_list_sockets(sockets[1]) if sockets and sockets[0] == 0 else {}
        dps = run(["docker", "ps", "--format", "{{.Ports}}"])
        published = parse_docker_ports(dps[1]) if dps and dps[0] == 0 else set()
        out = []
        for r in rows:
            name = r.pop("name")
            if r["pid"]:
                r["ppid"], r["exe"] = _proc_exe(r["pid"], name)
            elif (r["addr"], r["port"]) in held:
                r.update(pid=1, ppid=0, exe=SYSTEMD_EXE, unit=held[(r["addr"], r["port"])])
            elif r["port"] in published:
                r.update(ppid=None, exe="docker-proxy")
            else:
                r.update(ppid=None, exe=OWNER_HIDDEN)
            out.append(r)
        return out
    return None


def sockets(name: str, run: Runner | None = None, system: str | None = None) -> list[dict] | None:
    """Linux: the TCP/UDP sockets of processes whose name contains `name` (ours only)."""
    run, system = run or _run, system or SYSTEM
    if system != "Linux":
        return None
    res = run(["ss", "-tunapH"])
    if res is None or res[0] != 0:
        return None
    return [r for r in parse_ss_sockets(res[1]) if name.lower() in r["proc"].lower()]


def lsof(*args: str, run: Runner | None = None, system: str | None = None) -> str | None:
    """Darwin `lsof <args>` stdout (rc 1 = nothing matched, still an answer). None elsewhere."""
    run, system = run or _run, system or SYSTEM
    if system != "Darwin":
        return None
    res = run(["lsof", *args])
    return res[1] if res and res[0] in (0, 1) else None


def unified_log(args: list[str], timeout: int = 600, system: str | None = None) -> subprocess.CompletedProcess | None:
    """Darwin `log show ...`; None on a host that has no unified log."""
    if (system or SYSTEM) != "Darwin":
        return None
    try:
        return subprocess.run(["log", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "env":
        print("usage: nos_host.py env <label>", file=sys.stderr)
        return 64
    st = service_state(argv[1])
    if st is None:
        print(f"nos_host: cannot ask the service manager about {argv[1]}", file=sys.stderr)
        return 3
    if not st["loaded"] or (SYSTEM == "Linux" and not st["running"]):
        print(f"nos_host: {argv[1]} {st['detail']} [{st['source']}]", file=sys.stderr)
        return 2
    env = service_env(argv[1])
    if env is None:
        print(f"nos_host: {argv[1]}'s environment is unreadable", file=sys.stderr)
        return 3
    for k, v in env.items():
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", k) and "\n" not in v:
            sys.stdout.write(f"{k} => {v}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
