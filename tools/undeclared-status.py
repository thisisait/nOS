#!/usr/bin/env python3
"""What runs on this host that nOS never declared.

The converge says what it put on the host; nothing asked what ELSE is there.
Three axes, each judged against a DERIVED declared set, never a hand list:

  launchd  plists in ~/Library/LaunchAgents, /Library/LaunchAgents and
           /Library/LaunchDaemons (Linux: *.service / *.timer in
           ~/.config/systemd/user, /etc/systemd/user, /etc/systemd/system),
           plus loaded eu.thisisait.nos.* labels, vs the anatomy-graph daemon
           roster + literal Labels of the repo's *.plist.j2 templates (a Linux
           unit carries the same label as its base name)
  ports    Docker-published listeners (any address) and every non-loopback
           listener, vs manifest port_vars resolved through the config layers,
           host ports in the rendered ~/stacks compose files, the PIDs of
           loaded declared daemons and the rows' `host_programs` (a cask's
           system extension has no launchd label; its executable name is declared)
  cron     the user crontab; the playbook declares no cron job

Habitat (lexicon): the owner's software beside nOS — Spotify, a game launcher,
an updater. The owner declares it in config.yml as `habitat_processes` (launchd
labels and executable names), resolved through the config layers like every
other declaration; undeclared until then, however harmless.

Loopback listeners of ordinary user processes (editors, dev servers) are not
judged — noise on a dev Mac. Binaries on the sealed system volume are the OS,
as is a socket systemd holds for activation (ssh.socket). On Linux `ss -p` as
the operator cannot name another user's process: such a listener is reported
with its owner "not visible", never guessed and never dropped.
Not read: app-bundled agents (SMAppService) and login items.
Every host probe goes through tools/nos_host.py (launchd or systemd --user,
netstat or ss) — platform is a fact, not a toggle.

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
import re
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import nos_host  # noqa: E402 — sibling helper, not a package

SYSTEM = nos_host.SYSTEM
GRAPH = REPO / "state" / "anatomy-graph.json"
STACKS_DIR = pathlib.Path(os.environ.get("NOS_STACKS_DIR", str(pathlib.Path.home() / "stacks")))
NOS_PREFIX = "eu.thisisait.nos."
#: The sealed system volume (Apple's), and systemd itself holding an
#: activation socket (Linux's): the OS, not a workload.
SYSTEM_PATHS = ("/System/", "/usr/libexec/", "/usr/sbin/", "/usr/bin/", "/sbin/", "/usr/lib/systemd/")
DOCKER_BINS = {"com.docker.backend", "docker-proxy"}
LOOPBACK = re.compile(r"^(127\.|::1$|localhost$)")


def _run(*argv: str, ok_rc: tuple[int, ...] = (0,)) -> str | None:
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode in ok_rc else None


def _host_run(argv: list) -> tuple[int, str] | None:
    """nos_host's runner, through `_run` — the seam the tests replace."""
    out = _run(*argv)
    return None if out is None else (0, out)


def _manager() -> tuple[str, str]:
    """(axis name, the command that reads it) on this platform — for UNKNOWN lines."""
    if SYSTEM == "Linux":
        return "systemd --user", "systemctl --user list-units"
    return "launchd", "launchctl list"


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
    # The systemd twin of a literal plist Label: a role template NAMED for its
    # unit (roles/pazny.ollama/templates/nos-ollama-loopback.socket.j2).
    for tpl in [*REPO.glob("roles/**/*.service.j2"), *REPO.glob("roles/**/*.timer.j2"),
                *REPO.glob("roles/**/*.socket.j2")]:
        unit = tpl.name[: -len(".j2")].rsplit(".", 1)[0]
        if unit not in ("service", "timer", "socket") and "{" not in unit:
            labels.add(unit)
    return labels | _brew_twins(labels)


# `brew services` wrote homebrew.mxcl.<formula> until Homebrew 7, sh.brew.<formula>
# since; the host runs whichever its brew writes, so a declared one is both.
_BREW_PREFIXES = ("homebrew.mxcl.", "sh.brew.")


def _brew_twins(labels: set[str]) -> set[str]:
    return {other + lb[len(pre):] for lb in labels for pre in _BREW_PREFIXES
            if lb.startswith(pre) for other in _BREW_PREFIXES}


def _identity():
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity  # noqa: PLC0415 — sibling helper, not a package
    return nos_identity


def declared_programs() -> frozenset[str]:
    """Executable basenames the manifest rows declare (`host_programs`)."""
    return frozenset(str(x) for row in _identity().services() for x in row.get("host_programs") or [])


def habitat() -> frozenset[str]:
    """The owner's declaration: `habitat_processes` from the config layers."""
    return frozenset(str(x) for x in _identity().resolve_list("habitat_processes"))


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
    nos_identity = _identity()
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
    """label -> pid of every job the user's service manager has loaded (nos_host)."""
    return nos_host.loaded_services(run=_host_run, system=SYSTEM)


def plist_files() -> dict[str, dict]:
    """label -> {path, program}: plists, or systemd unit files. Only the label
    and the program path are read (nos_host.unit_files)."""
    return nos_host.unit_files(system=SYSTEM)


def listeners() -> list[dict] | None:
    """Every TCP listener with its owner, or exe "?" when this user cannot see it (nos_host)."""
    return nos_host.listeners(run=_host_run, system=SYSTEM)


def _owner(exe: str) -> str:
    return "owner not visible to this user" if exe == nos_host.OWNER_HIDDEN else pathlib.Path(exe).name


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
        # A user `launchctl list` / `systemctl --user` cannot see the system
        # domain: not asked != not loaded.
        system = (row["path"] or "").startswith(nos_host.SYSTEM_DOMAINS) and lbl not in loaded
        out.append({"label": lbl, "loaded": None if system else lbl in loaded,
                    "pid": loaded.get(lbl), **row})
    return out


def judge_ports(rows: list[dict], declared: set[int], daemon_pids: set[int],
                daemon_exes: frozenset[str] = frozenset()) -> list[dict]:
    """`daemon_exes`: a declared plist's program (full path), or a declared
    program / habitat name (basename). Either joins the listener to a declaration."""
    out, seen = [], set()
    for r in sorted(rows, key=lambda r: r["port"]):
        exe = r.get("exe") or "?"
        docker = pathlib.Path(exe).name in DOCKER_BINS
        if exe.startswith(SYSTEM_PATHS) or (LOOPBACK.match(r["addr"]) and not docker):
            continue
        if (r["port"] in declared or {r["pid"], r.get("ppid")} & daemon_pids
                or exe in daemon_exes or pathlib.Path(exe).name in daemon_exes):
            continue
        if (r["port"], exe) not in seen:
            seen.add((r["port"], exe))
            out.append({"port": r["port"], "addr": r["addr"], "pid": r["pid"], "exe": exe})
    return out


def collect() -> dict:
    report: dict = {"sources_missing": []}
    labels, loaded, plists, own = declared_labels(), loaded_labels(), plist_files(), habitat()
    # A unit snapd generated from a snap's own declaration is the distro's
    # package manager at work — the OS, like the sealed system volume.
    plists = {k: v for k, v in plists.items() if v.get("generator") != "snapd"}
    if labels is None or loaded is None:
        axis, cmd = _manager()
        report["sources_missing"].append(f"{axis} ({cmd} / state/anatomy-graph.json)")
    else:
        report["launchd"] = judge_launchd(loaded, plists, labels | own)
    ports, rows = declared_ports(), listeners()
    if ports is None or rows is None or labels is None or loaded is None:
        report["sources_missing"].append(
            f"listening ports ({'ss -ltnp' if SYSTEM == 'Linux' else 'netstat'} / {STACKS_DIR})")
    else:
        pids = {p for lbl, p in loaded.items() if lbl in labels and p}
        # A root daemon's pid is not in a user job list; its program path is.
        exes = frozenset(v["program"] for lbl, v in plists.items() if lbl in labels)
        report["ports"] = judge_ports(rows, ports, pids, exes | declared_programs() | own)
    cron = crontab()
    if cron is None:
        report["sources_missing"].append("crontab -l")
    else:
        report["cron"] = cron
    return report


def summary(report: dict) -> list[str]:
    """One phrase per undeclared item — red-status joins them into its line."""
    return ([f"port {p['addr']}:{p['port']} ({_owner(p['exe'])})" for p in report.get("ports", [])]
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
        state = ({True: f"loaded pid={d['pid']}" if d["pid"] else "loaded, not running", False: "on disk, not loaded"}
                 .get(d["loaded"], "system domain, not asked"))
        print(f"  launchd  {d['label']:<44} {state:<26} {d['program']}  [{d['path']}]")
    for p in report.get("ports", []):
        exe = _owner(p["exe"]) if p["exe"] == nos_host.OWNER_HIDDEN else p["exe"]
        print(f"  port     {p['addr']}:{p['port']:<6} pid={str(p['pid'] or '-'):<7} {exe}")
    for c in report.get("cron", []):
        print(f"  cron     {c}")
    for m in report["sources_missing"]:
        print(f"  ?        {m} — unreadable, UNKNOWN not green")
    n = len(summary(report))
    print(f"{n} undeclared" + (" (some axes UNKNOWN)" if report["sources_missing"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
