#!/usr/bin/env python3
"""Is the thalamus up, and what did it last do?

Reads the socket (~/.nos/thalamus.sock: a socket, mode 0600, accepting a connect), the launchd job
(eu.thisisait.nos.thalamus), the model serve last started with (~/thalamus/log/launchd.err.log),
the ledger (<--data-dir>/ledger.db, its dir 0700; the dir is read from the deployed plist, the path
the daemon opens), the ledger's last session and the face's relay door (bound exactly when the plist
sets THALAMUS_RELAY_SECRET; an accepted connect without a hello is refused by serve, never a session). Each line is OK / RED / UNKNOWN with its source;
serving without a model is UNKNOWN (degraded).

On Linux the same daemon is the systemd --user unit of the same label: the
argv and env come from the unit + its EnvironmentFile, the start lines from the
user journal, and a shared socket (THALAMUS_SOCKET_SHARED=1, src/main.rs) is
0666 by design — every login connects, the peer's uid names it. All of it
through tools/nos_host.py; platform is a fact, not a toggle.

Reads only (the connect opens no session). Exit 0 always. A source it cannot read is UNKNOWN, never green.
`--tags thalamus,verify` fails on any line that is not OK, except the model line, which warns.

Usage:
    tools/thalamus-status.py [--json]
Env (tests): NOS_THALAMUS_SOCKET, NOS_THALAMUS_LEDGER, NOS_THALAMUS_LOG.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import plistlib
import pathlib
import socket
import sqlite3
import stat
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import nos_host  # noqa: E402 — launchd or systemd --user, by platform fact

OK, RED, UNKNOWN = "OK", "RED", "UNKNOWN"
HOME = pathlib.Path.home()
LABEL = "eu.thisisait.nos.thalamus"
PLIST = HOME / "Library/LaunchAgents" / f"{LABEL}.plist"


def line(check: str, state: str, detail: str, source: str) -> dict:
    return {"check": check, "state": state, "detail": detail, "source": source}


def judge_socket(path: pathlib.Path, want_mode: int = 0o600) -> dict:
    try:
        st = path.lstat()
    except FileNotFoundError:
        return line("socket", RED, "absent — the daemon is not serving", str(path))
    except OSError as exc:
        return line("socket", UNKNOWN, f"unreadable ({type(exc).__name__})", str(path))
    if not stat.S_ISSOCK(st.st_mode):
        return line("socket", RED, "not a socket", str(path))
    mode = stat.S_IMODE(st.st_mode)
    if mode != want_mode:
        return line("socket", RED, f"mode {mode:o}, want {want_mode:o}", str(path))
    # A crashed daemon leaves its socket on disk: only an accepted connect() is serving.
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(2)
        try:
            s.connect(str(path))
        except (ConnectionRefusedError, FileNotFoundError):
            return line("socket", RED, "mode 600, stale: nobody accepts", str(path))
        except OSError as exc:
            return line("socket", UNKNOWN, f"connect failed ({type(exc).__name__})", str(path))
    return line("socket", OK, f"mode {want_mode:o}, accepting", str(path))


def judge_service(st: dict | None, check: str = "launchd", src: str = f"launchctl print gui/<uid>/{LABEL}") -> dict:
    """nos_host.service_state -> the job line. None = the manager could not be asked."""
    if st is None:
        return line(check, UNKNOWN, "service manager unavailable", src)
    src = st.get("source", src)
    if not st["loaded"]:
        return line(check, RED, st["detail"], src)
    if not st["running"]:
        return line(check, RED, f"{st['detail']} (crash loop?)", src)
    return line(check, OK, st["detail"], src)


def judge_launchd(res: tuple[int, str] | None) -> dict:
    """(rc, `launchctl print` text) -> the job line; parsing is nos_host's."""
    return judge_service(None if res is None else nos_host.parse_launchctl_print(*res))


def _open_ro(db: pathlib.Path):
    spec = importlib.util.spec_from_file_location("_ledger_open", pathlib.Path(__file__).resolve().parent / "_ledger_open.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.open_ledger_ro(db)


def ledger_path(plist: pathlib.Path) -> tuple[pathlib.Path | None, str]:
    """The ledger `serve --data-dir` opens, read from the plist; (None, why) when it cannot be read."""
    try:
        argv = plistlib.loads(plist.read_bytes()).get("ProgramArguments") or []
    except (OSError, plistlib.InvalidFileException, ValueError, AttributeError) as exc:
        return None, f"plist unreadable ({type(exc).__name__})"
    return ledger_from_argv(argv, "plist")


def ledger_from_argv(argv: list, where: str) -> tuple[pathlib.Path | None, str]:
    if "--data-dir" in argv[:-1]:
        return pathlib.Path(argv[argv.index("--data-dir") + 1]) / "ledger.db", ""
    return None, f"{where} passes no --data-dir"


def judge_ledger(db: pathlib.Path) -> list[dict]:
    con, how = _open_ro(db)
    if con is None:
        return [line("ledger", UNKNOWN, how, str(db)), line("last session", UNKNOWN, "no ledger read", str(db))]
    try:
        row = con.execute("SELECT uuid, actor_id, status, started_at, ended_at, stop_reason"
                          " FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
    except sqlite3.Error as exc:
        con.close()
        return [line("ledger", UNKNOWN, f"unreadable: {exc}", str(db)), line("last session", UNKNOWN, "no ledger read", str(db))]
    con.close()
    try:
        mode = stat.S_IMODE(db.parent.stat().st_mode)
        led = line("ledger", OK if mode == 0o700 else RED, f"readable{', ' + how if how else ''}; dir mode {mode:o}", str(db))
    except OSError as exc:
        led = line("ledger", UNKNOWN, f"dir unreadable ({type(exc).__name__})", str(db.parent))
    if row is None:
        return [led, line("last session", OK, "none yet", str(db))]
    detail = f"{row['started_at']} {row['actor_id']} {row['status']}" + (
        f", ended {row['ended_at']} ({row['stop_reason']})" if row["ended_at"] else "")
    return [led, line("last session", OK, detail, str(db))]


def _tail(log: pathlib.Path) -> list[str]:
    with log.open("rb") as f:
        f.seek(max(0, log.stat().st_size - (1 << 20)))
        return f.read().decode(errors="replace").splitlines()


def judge_model(log: pathlib.Path | str, lines: list[str] | None = None) -> dict:
    """The last `thalamus: model ` line serve printed at start (src/main.rs): launchd's
    stderr log, or `lines` already read (the systemd journal); `log` then names the source."""
    if lines is None:
        try:
            lines = _tail(pathlib.Path(log))
        except OSError as exc:
            return line("model", UNKNOWN, f"no start line read ({type(exc).__name__})", str(log))
    said = next((ln[len("thalamus: model "):] for ln in reversed(lines) if ln.startswith("thalamus: model ")), None)
    if said is None:
        return line("model", UNKNOWN, "no start line in the log", str(log))
    if said.startswith("bound "):
        return line("model", OK, said, str(log))
    # Controls still answer, turns are refused: degraded, never green.
    return line("model", UNKNOWN, f"degraded: serving without a model: {said.removeprefix('UNBOUND: ')}", str(log))


def judge_relay(log: pathlib.Path | str, plist: pathlib.Path | str, lines: list[str] | None = None,
                want: bool | None = None) -> dict:
    """The face's door (src/relay.rs): bound exactly when the definition carries
    THALAMUS_RELAY_SECRET (presence only, never printed). `want` / `lines` given
    = already read from the systemd unit / journal; `plist` / `log` then name them."""
    if want is None:
        try:
            want = bool((plistlib.loads(pathlib.Path(plist).read_bytes()).get("EnvironmentVariables") or {})
                        .get("THALAMUS_RELAY_SECRET"))
        except (OSError, plistlib.InvalidFileException, ValueError, AttributeError) as exc:
            return line("relay", UNKNOWN, f"plist unreadable ({type(exc).__name__})", str(plist))
    if lines is None:
        try:
            lines = _tail(pathlib.Path(log))
        except OSError as exc:
            return line("relay", UNKNOWN, f"no start line read ({type(exc).__name__})", str(log))
    said = next((ln[len("thalamus: relay "):] for ln in reversed(lines) if ln.startswith("thalamus: relay ")), None)
    if said is None:
        return line("relay", UNKNOWN, "no start line in the log", str(log))
    if not said.startswith("bound "):
        if said.startswith("closed") and not want:
            return line("relay", OK, "closed: no secret, no face on this host", str(log))
        return line("relay", RED, f"{said} (the plist {'sets' if want else 'sets no'} secret)", str(log))
    if not want:
        return line("relay", RED, f"{said}, but the plist sets no secret", str(log))
    host, _, port = said.removeprefix("bound ").rpartition(":")
    try:
        with socket.create_connection((host, int(port)), timeout=2):
            pass
    except (OSError, ValueError) as exc:
        return line("relay", RED, f"{said} in the log, nobody accepts ({type(exc).__name__})", str(log))
    return line("relay", OK, f"{said}, accepting", str(log))


def collect() -> list[dict]:
    if nos_host.SYSTEM == "Linux":
        return collect_systemd()
    sock = pathlib.Path(os.environ.get("NOS_THALAMUS_SOCKET", HOME / ".nos/thalamus.sock"))
    log = pathlib.Path(os.environ.get("NOS_THALAMUS_LOG", HOME / "thalamus/log/launchd.err.log"))
    head = [judge_socket(sock), judge_service(nos_host.service_state(LABEL)), judge_model(log), judge_relay(log, PLIST)]
    if os.environ.get("NOS_THALAMUS_LEDGER"):
        return head + judge_ledger(pathlib.Path(os.environ["NOS_THALAMUS_LEDGER"]))
    db, why = ledger_path(PLIST)
    if db is None:
        return head + [line("ledger", UNKNOWN, why, str(PLIST)), line("last session", UNKNOWN, "no ledger read", str(PLIST))]
    return head + judge_ledger(db)


def collect_systemd() -> list[dict]:
    """The same lines from the systemd --user unit, its env file and the journal."""
    unit = HOME / ".config/systemd/user" / f"{LABEL}.service"
    d = nos_host.service_definition(LABEL)
    env = (d or {}).get("env") or {}
    sock = pathlib.Path(os.environ.get("NOS_THALAMUS_SOCKET") or env.get("THALAMUS_SOCKET") or HOME / ".nos/thalamus.sock")
    shared = env.get("THALAMUS_SOCKET_SHARED") == "1"
    sock_line = (judge_socket(sock, 0o666 if shared else 0o600) if d is not None or os.environ.get("NOS_THALAMUS_SOCKET")
                 else line("socket", UNKNOWN, "unit unreadable: which socket it serves is unknown", str(unit)))
    head = [sock_line,
            judge_service(nos_host.service_state(LABEL), check="systemd", src=f"systemctl --user show {LABEL}.service")]
    got = nos_host.service_log(LABEL, grep="thalamus: ")
    if got is None:
        why = f"journal unreadable (journalctl --user -u {LABEL}.service)"
        head += [line("model", UNKNOWN, why, "journal"), line("relay", UNKNOWN, why, "journal")]
    else:
        lines, src = got
        head.append(judge_model(src, lines))
        if d is None:
            head.append(line("relay", UNKNOWN, "unit unreadable", str(unit)))
        else:
            head.append(judge_relay(src, d["path"], lines, want=bool(env.get("THALAMUS_RELAY_SECRET"))))
    if os.environ.get("NOS_THALAMUS_LEDGER"):
        return head + judge_ledger(pathlib.Path(os.environ["NOS_THALAMUS_LEDGER"]))
    if d is None:
        return head + [line("ledger", UNKNOWN, "unit unreadable", str(unit)),
                       line("last session", UNKNOWN, "no ledger read", str(unit))]
    db, why = ledger_from_argv(d["argv"], "unit ExecStart")
    if db is None:
        return head + [line("ledger", UNKNOWN, why, d["path"]), line("last session", UNKNOWN, "no ledger read", d["path"])]
    return head + judge_ledger(db)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = collect()
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(f"{r['state']:<8} {r['check']:<14} {r['detail']}  [{r['source']}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
