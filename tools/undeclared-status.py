#!/usr/bin/env python3
"""What runs on this host that nOS never declared.

The converge says what it put on the host; nothing asked what ELSE is there.
Three axes, each judged against a DERIVED declared set, never a hand list:

  launchd  plists in ~/Library/LaunchAgents, /Library/LaunchAgents and
           /Library/LaunchDaemons, plus loaded eu.thisisait.nos.* labels,
           vs the anatomy-graph daemon roster + literal Labels of the repo's
           *.plist.j2 templates
  ports    Docker-published listeners (any address) and every non-loopback
           listener, vs manifest port_vars resolved through the config layers,
           host ports in the rendered ~/stacks compose files, and the PIDs of
           loaded declared daemons
  cron     the user crontab; the playbook declares no cron job

Loopback listeners of ordinary user processes (editors, dev servers) are not
judged — noise on a dev Mac. Binaries on the sealed system volume are the OS.
Not read: app-bundled agents (SMAppService) and login items.

Reads only. Exit 0 always. An axis it cannot read is UNKNOWN, never green.
Never prints a plist's EnvironmentVariables — nOS plists embed tokens.

Usage:
    tools/undeclared-status.py          # undeclared items, per axis
    tools/undeclared-status.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import plistlib
import re
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
GRAPH = REPO / "state" / "anatomy-graph.json"
STACKS_DIR = pathlib.Path(os.environ.get("NOS_STACKS_DIR", str(pathlib.Path.home() / "stacks")))
PLIST_DIRS = (pathlib.Path.home() / "Library/LaunchAgents",
              pathlib.Path("/Library/LaunchAgents"), pathlib.Path("/Library/LaunchDaemons"))
NOS_PREFIX = "eu.thisisait.nos."
#: The sealed system volume: Apple's, not a workload.
SYSTEM_PATHS = ("/System/", "/usr/libexec/", "/usr/sbin/", "/usr/bin/", "/sbin/")
DOCKER_BINS = {"com.docker.backend", "docker-proxy"}
LOOPBACK = re.compile(r"^(127\.|::1$|localhost$)")


def _run(*argv: str, ok_rc: tuple[int, ...] = (0,)) -> str | None:
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode in ok_rc else None


# ── declared: derived from the repo and the converged artifacts ──────────────

def declared_labels() -> set[str] | None:
    try:
        nodes = json.loads(GRAPH.read_text(encoding="utf-8"))["nodes"]
    except (OSError, ValueError, KeyError):
        return None
    # A row's jobs sit on its service: node (I-12); a daemon: node is a row-less job.
    labels = {k.split(":", 1)[1] for k, v in nodes.items()
              if isinstance(v, dict) and v.get("kind") == "daemon"}
    labels |= {lb for v in nodes.values() if isinstance(v, dict) for lb in v.get("launchd_labels") or []}
    for tpl in REPO.glob("**/*.plist.j2"):
        m = re.search(r"<key>Label</key>\s*<string>([^<{]+)</string>", tpl.read_text(encoding="utf-8"))
        if m:
            labels.add(m.group(1).strip())
    return labels


def _host_ports(entry) -> set[int]:
    """Host side of one compose `ports:` item; container-only = no host port."""
    if isinstance(entry, dict):
        entry = f"{entry.get('published', '')}:"
    parts = str(entry).split("/")[0].rsplit(":", 2)
    if len(parts) < 2:
        return set()
    lo, _, hi = parts[-2].partition("-")
    try:
        return set(range(int(lo), int(hi or lo) + 1))
    except ValueError:
        return set()


def declared_ports() -> set[int] | None:
    if not STACKS_DIR.is_dir():
        return None
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity  # noqa: PLC0415 — sibling helper, not a package

    ports: set[int] = set()
    for row in nos_identity.services():
        layers = nos_identity.resolve_flag(row["port_var"]) if row.get("port_var") else []
        if layers and layers[-1][1].isdigit():
            ports.add(int(layers[-1][1]))
    for f in [*STACKS_DIR.glob("*/*.yml"), *STACKS_DIR.glob("*/overrides/*.yml")]:
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        for svc in (doc.get("services") or {}).values() if isinstance(doc, dict) else ():
            for entry in (svc or {}).get("ports") or []:
                ports |= _host_ports(entry)
    return ports


# ── observed: read-only probes ───────────────────────────────────────────────

def loaded_labels() -> dict[str, int | None] | None:
    out = _run("launchctl", "list")
    if out is None:
        return None
    rows = {}
    for line in out.splitlines()[1:]:
        f = line.split("\t")
        if len(f) == 3:
            rows[f[2]] = int(f[0]) if f[0].isdigit() else None
    return rows


def plist_files() -> dict[str, dict]:
    """label -> {path, program}. Only Label and the program path are read."""
    found = {}
    for d in PLIST_DIRS:
        for p in sorted(d.glob("*.plist")) if d.is_dir() else ():
            try:
                with p.open("rb") as fh:
                    doc = plistlib.load(fh)
            except Exception:  # noqa: BLE001 — unparseable is still a file on disk
                doc = {}
            prog = doc.get("Program") or (doc.get("ProgramArguments") or ["?"])[0]
            found[str(doc.get("Label") or p.stem)] = {"path": str(p), "program": str(prog)}
    return found


def listeners() -> list[dict] | None:
    """Darwin `netstat -anv` sees every user's sockets (lsof as a user does not)."""
    # ponytail: Darwin only; Linux (ss -ltnp needs root for pids) reads UNKNOWN.
    out = _run("netstat", "-anv", "-p", "tcp")
    if out is None:
        return None
    rows = []
    for line in out.splitlines():
        m = re.match(r"tcp(?:4|6|46)\s+\d+\s+\d+\s+(\S+)\.(\d+)\s+\S+\s+LISTEN\s.*?\s(\S.*?):(\d+)\s+[0-9a-f]{5}\s", line)
        if m:
            rows.append({"addr": m.group(1), "port": int(m.group(2)), "pid": int(m.group(4))})
    pids = ",".join(sorted({str(r["pid"]) for r in rows}))
    procs = {}
    for line in (_run("ps", "-o", "pid=,ppid=,comm=", "-p", pids) or "").splitlines() if pids else ():
        pid, ppid, exe = line.split(None, 2)
        procs[int(pid)] = (int(ppid), exe.strip())
    for r in rows:
        r["ppid"], r["exe"] = procs.get(r["pid"], (None, "?"))
    return rows


def crontab() -> list[str] | None:
    try:
        out = subprocess.run(("crontab", "-l"), capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return [] if "no crontab" in out.stderr else None
    return [ln for ln in out.stdout.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


# ── judge: pure, so the tests feed it fixtures ───────────────────────────────

def judge_launchd(loaded: dict, plists: dict, declared: set[str]) -> list[dict]:
    names = set(plists) | {lbl for lbl in loaded if lbl.startswith(NOS_PREFIX)}
    out = []
    for lbl in sorted(names - declared):
        row = plists.get(lbl, {"path": None, "program": "?"})
        # A user `launchctl list` cannot see the system domain: not asked != not loaded.
        system = (row["path"] or "").startswith("/Library/LaunchDaemons") and lbl not in loaded
        out.append({"label": lbl, "loaded": None if system else lbl in loaded,
                    "pid": loaded.get(lbl), **row})
    return out


def judge_ports(rows: list[dict], declared: set[int], daemon_pids: set[int],
                daemon_exes: frozenset[str] = frozenset()) -> list[dict]:
    out, seen = [], set()
    for r in sorted(rows, key=lambda r: r["port"]):
        exe = r.get("exe") or "?"
        docker = pathlib.Path(exe).name in DOCKER_BINS
        if exe.startswith(SYSTEM_PATHS) or (LOOPBACK.match(r["addr"]) and not docker):
            continue
        if r["port"] in declared or {r["pid"], r.get("ppid")} & daemon_pids or exe in daemon_exes:
            continue
        if (r["port"], exe) not in seen:
            seen.add((r["port"], exe))
            out.append({"port": r["port"], "addr": r["addr"], "pid": r["pid"], "exe": exe})
    return out


def collect() -> dict:
    report: dict = {"sources_missing": []}
    labels, loaded, plists = declared_labels(), loaded_labels(), plist_files()
    if labels is None or loaded is None:
        report["sources_missing"].append("launchd (launchctl list / state/anatomy-graph.json)")
    else:
        report["launchd"] = judge_launchd(loaded, plists, labels)
    ports, rows = declared_ports(), listeners()
    if ports is None or rows is None or labels is None or loaded is None:
        report["sources_missing"].append(f"listening ports (netstat / {STACKS_DIR})")
    else:
        pids = {p for lbl, p in loaded.items() if lbl in labels and p}
        # A root daemon's pid is not in a user `launchctl list`; its program path is.
        exes = frozenset(v["program"] for lbl, v in plists.items() if lbl in labels)
        report["ports"] = judge_ports(rows, ports, pids, exes)
    cron = crontab()
    if cron is None:
        report["sources_missing"].append("crontab -l")
    else:
        report["cron"] = cron
    return report


def summary(report: dict) -> list[str]:
    """One phrase per undeclared item — red-status joins them into its line."""
    return ([f"port {p['addr']}:{p['port']} ({pathlib.Path(p['exe']).name})" for p in report.get("ports", [])]
            + [f"cron `{c[:60]}`" for c in report.get("cron", [])]
            + [f"launchd {d['label']}{' (loaded)' if d['loaded'] else ''}" for d in report.get("launchd", [])])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = collect()
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    for d in report.get("launchd", []):
        state = ({True: f"loaded pid={d['pid']}", False: "on disk, not loaded"}
                 .get(d["loaded"], "system domain, not asked"))
        print(f"  launchd  {d['label']:<44} {state:<26} {d['program']}  [{d['path']}]")
    for p in report.get("ports", []):
        print(f"  port     {p['addr']}:{p['port']:<6} pid={p['pid']:<7} {p['exe']}")
    for c in report.get("cron", []):
        print(f"  cron     {c}")
    for m in report["sources_missing"]:
        print(f"  ?        {m} — unreadable, UNKNOWN not green")
    n = len(summary(report))
    print(f"{n} undeclared" + (" (some axes UNKNOWN)" if report["sources_missing"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
