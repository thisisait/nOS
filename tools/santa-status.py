#!/usr/bin/env python3
"""What Santa saw execute outside the trees nOS declares.

Santa (pazny.mac.santa) runs in MONITOR mode: it allows everything and logs every
exec to /var/db/santa/santa.log. This reader judges those EXEC lines against the
declared trees — the Pulse runner's own allow-list (_REPO_TREES under the repo,
_HOME_TREES under $HOME, _SYSTEM_PREFIXES) plus the OS, Homebrew and /Applications —
and reports what ran elsewhere. Telemetry, not a verdict: on a dev Mac pyenv, node
and cargo binaries land here, and that is the point of looking.

Red: Santa declared (install_santa) but absent; a mode other than Monitor; any
DENY; executables outside the declared trees in the window.

Reads only. Exit 0 always. A source it cannot read is UNKNOWN, never green.

Usage:
    tools/santa-status.py              # last 24h
    tools/santa-status.py --hours 168 --json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
from nos_identity import layer_paths, resolve_flag  # noqa: E402

LOG = pathlib.Path(os.environ.get("NOS_SANTA_LOG", "/var/db/santa/santa.log"))
SANTACTL = os.environ.get("NOS_SANTACTL", "/usr/local/bin/santactl")
#: The OS, the package manager and app bundles: not workloads nOS declares, not news.
OS_TREES = ("/System/", "/usr/bin/", "/usr/sbin/", "/usr/libexec/", "/bin/", "/sbin/",
            "/Library/Apple/", "/Library/Developer/CommandLineTools/", "/Applications/",
            "/opt/homebrew/", "/usr/local/libexec/nos-agent/")
TAIL_BYTES = 16 * 1024 * 1024
LINE_RE = re.compile(r"^\[(?P<ts>[^\]]+)\] \w santad: (?P<body>action=EXEC\|.*)$")


def declared_trees() -> tuple[str, ...]:
    """The Pulse runner's trees, resolved for this repo and $HOME, plus OS_TREES."""
    spec = importlib.util.spec_from_file_location(
        "_pulse_subprocess_runner", REPO / "files/anatomy/pulse/pulse/runners/subprocess.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # its dataclasses resolve their module by name
    spec.loader.exec_module(mod)
    repo = os.environ.get("NOS_REPO_ROOT", str(REPO)).rstrip("/") + "/"
    home = str(pathlib.Path.home()).rstrip("/") + "/"
    return (OS_TREES + tuple(mod._SYSTEM_PREFIXES)
            + tuple(repo + t for t in mod._REPO_TREES) + tuple(home + t for t in mod._HOME_TREES))


def ni_default(name: str) -> list:
    """A list var from the config layers, last layer wins."""
    import yaml  # noqa: PLC0415 — only this reader path needs it
    value: list = []
    for p in layer_paths():
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if isinstance(doc, dict) and isinstance(doc.get(name), list):
            value = doc[name]
    return value


def dev_trees() -> tuple[str, ...]:
    """santa_dev_toolchain_trees from the config layers, under $HOME."""
    home = str(pathlib.Path.home()).rstrip("/") + "/"
    return tuple(home + str(t).lstrip("/") for t in ni_default("santa_dev_toolchain_trees"))


def parse(line: str) -> dict | None:
    m = LINE_RE.match(line.rstrip("\n"))
    if not m:
        return None
    fields = dict(kv.split("=", 1) for kv in m["body"].split("|") if "=" in kv)
    try:
        fields["ts"] = datetime.fromisoformat(m["ts"].replace("Z", "+00:00"))
    except ValueError:
        return None
    return fields


def judge(lines, trees: tuple[str, ...], since: datetime, dev: tuple[str, ...] = ()) -> dict:
    outside: dict[str, dict] = {}
    toolchain: dict[str, int] = {}
    denied: list[dict] = []
    for line in lines:
        ev = parse(line)
        if not ev or ev["ts"] < since:
            continue
        path = ev.get("path", "")
        if ev.get("decision", "").startswith("DENY"):
            denied.append({"path": path, "ts": ev["ts"].isoformat(), "reason": ev.get("reason", "")})
        if path and dev and path.startswith(dev):
            toolchain[path] = toolchain.get(path, 0) + 1
        elif path and not path.startswith(trees):
            row = outside.setdefault(path, {"path": path, "count": 0, "users": set(),
                                            "teamid": ev.get("teamid", ""), "last": ""})
            row["count"] += 1
            row["users"].add(ev.get("user", ev.get("uid", "?")))
            row["last"] = max(row["last"], ev["ts"].isoformat())
    rows = sorted(outside.values(), key=lambda r: (-r["count"], r["path"]))
    for r in rows:
        r["users"] = sorted(r["users"])
    return {"outside": rows, "denied": denied,
            "dev_toolchain": [{"path": p, "count": c} for p, c in sorted(toolchain.items(), key=lambda x: -x[1])]}


def _tail(path: pathlib.Path) -> list[str]:
    with path.open("rb") as fh:
        fh.seek(max(0, path.stat().st_size - TAIL_BYTES))
        return fh.read().decode("utf-8", "replace").splitlines()


def collect(hours: int = 24, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    layers = resolve_flag("install_santa")
    report: dict = {"sources_missing": [], "window_h": hours,
                    "declared": bool(layers) and layers[-1][1].lower() == "true"}
    if not pathlib.Path(SANTACTL).exists():
        report["installed"] = False
        return report
    report["installed"] = True
    try:
        out = subprocess.run([SANTACTL, "status", "--json"], capture_output=True, text=True, timeout=20)
        report["mode"] = json.loads(out.stdout)["daemon"]["mode"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        report["sources_missing"].append(f"{SANTACTL} status --json")
    try:
        report.update(judge(_tail(LOG), declared_trees(), now - timedelta(hours=hours), dev_trees()))
    except OSError as exc:
        report["sources_missing"].append(f"{LOG} ({exc.strerror or exc})")
    return report


def summary(report: dict) -> list[str]:
    """One phrase per red — red-status joins them into its line."""
    out = []
    if report.get("declared") and not report.get("installed"):
        out.append("Santa declared (install_santa) but not installed")
    mode = report.get("mode")
    if mode and mode != "Monitor":
        out.append(f"Santa mode is {mode} — nOS declares Monitor only")
    if report.get("denied"):
        out.append(f"{len(report['denied'])} exec DENY")
    rows = report.get("outside") or []
    if rows:
        out.append(f"{len(rows)} executable(s) outside the declared trees in {report['window_h']}h: "
                   + ", ".join(f"{r['path']} ×{r['count']}" for r in rows[:5]) + (" …" if len(rows) > 5 else ""))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = collect(args.hours)
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True, default=str)
        sys.stdout.write("\n")
        return 0
    if not report["installed"]:
        print("santa: not installed" + (" — DECLARED by install_santa: red" if report["declared"] else
                                        " (install_santa off)"))
        return 0
    print(f"santa: mode {report.get('mode', 'UNKNOWN')}")
    for r in report.get("outside", []):
        print(f"  {r['count']:>6}  {r['path']}  users={','.join(r['users'])} team={r['teamid'] or '-'} last={r['last']}")
    dev = report.get("dev_toolchain") or []
    if dev:
        print(f"  dev toolchain (santa_dev_toolchain_trees, not red): "
              + ", ".join(f"{d['path']} ×{d['count']}" for d in dev[:5]) + (" …" if len(dev) > 5 else ""))
    for d in report.get("denied", []):
        print(f"  DENY    {d['path']} ({d['reason']}) {d['ts']}")
    for m in report["sources_missing"]:
        print(f"  ?       {m} — unreadable, UNKNOWN not green")
    print(f"{len(report.get('outside', []))} outside the declared trees in {report['window_h']}h"
          + (" (some sources UNKNOWN)" if report["sources_missing"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
