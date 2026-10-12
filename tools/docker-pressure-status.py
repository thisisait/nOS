#!/usr/bin/env python3
"""Is the Docker VM short of memory right now — /proc/pressure/memory, `full` line.

The size check (docker_min_memory_gib) passed a VM reading full avg300=34.55
on 2026-10-12; the converge died 10 min later on an Authentik EOF. Pressure is
the fact, size is not. main.yml refuses on `--json` verdict "starved";
red-status reads collect()/summary(). An unreadable probe is UNKNOWN, never ok.

Usage:
    tools/docker-pressure-status.py [--json] [--max-full-avg60 N]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import platform
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
VAR = "docker_memory_pressure_max_full_avg60"
ESCAPE = "nos_allow_memory_pressure"
PSI = pathlib.Path("/proc/pressure/memory")
UNITS = {"b": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12,
         "kib": 2**10, "mib": 2**20, "gib": 2**30, "tib": 2**40}


def parse_psi(text: str | None) -> dict:
    """{'some': {...}, 'full': {'avg10','avg60','avg300'}} — whatever lines parse."""
    out: dict = {}
    for kind, body in re.findall(r"^(some|full)\s+(.*)$", text or "", re.M):
        vals = dict(re.findall(r"(avg\d+)=([\d.]+)", body))
        if {"avg10", "avg60", "avg300"} <= vals.keys():
            out[kind] = {k: float(vals[k]) for k in ("avg10", "avg60", "avg300")}
    return out


def decide(psi: dict, max_full_avg60: float) -> str:
    full = psi.get("full")
    if not full:
        return "unknown"
    return "starved" if full["avg60"] > max_full_avg60 else "ok"


def read_psi(docker: str = "docker", image: str = "alpine:3", timeout: int = 30) -> str | None:
    """Linux: Docker shares the host kernel, read the file. Else ask the VM's kernel."""
    try:
        if platform.system() == "Linux":
            return PSI.read_text(encoding="utf-8")
        r = subprocess.run([docker, "run", "--rm", "--network", "none", image,
                            "cat", str(PSI)], capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _bytes(usage: str) -> int:
    m = re.match(r"\s*([\d.]+)\s*([a-zA-Z]+)", usage)
    return int(float(m.group(1)) * UNITS.get(m.group(2).lower(), 0)) if m else 0


def top_containers(docker: str = "docker", timeout: int = 30) -> list[tuple[str, int]]:
    try:
        r = subprocess.run([docker, "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}"],
                           capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return []
    rows = [line.split("\t", 1) for line in r.stdout.splitlines() if "\t" in line]
    return sorted(((n, _bytes(u)) for n, u in rows), key=lambda x: -x[1])


def message(psi: dict, limit: float, top: list[tuple[str, int]]) -> str:
    full = psi["full"]
    tops = "\n".join(f"  {n:<32} {b / 2**30:5.2f} GiB" for n, b in top[:5]) \
        or "  (docker stats did not answer in time — itself a sign of starvation)"
    return f"""\
The Docker VM is starved of memory right now, so this run stops before it starts.

/proc/pressure/memory inside the VM:
  full avg10={full['avg10']} avg60={full['avg60']} avg300={full['avg300']}
That is the % of time every task waited on memory. The avg60 limit
is {limit} ({VAR}); a quiet VM reads below 1.
At avg300=34.55 a converge died 10 minutes in, on an Authentik EOF that
named no cause (2026-10-12).

Biggest containers now:
{tops}

Two fixes, pick one:
  1. Docker Desktop -> Settings -> Resources -> Memory: give the VM more. On a
     host that also runs ollama, past ~14.5 GiB the host itself starves ollama,
     so more memory is not always the answer.
  2. Run fewer services: set install_<service>: false in config.yml for the
     heavy ones above you do not need, then re-run.

To run anyway (it will likely fail late): -e {ESCAPE}=true"""


def _limit() -> float:
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity as ni  # noqa: PLC0415

    return float(ni.resolve_flag(VAR)[-1][1])


def collect(limit: float | None = None, docker: str = "docker", image: str = "alpine:3") -> dict:
    limit = _limit() if limit is None else limit
    psi = parse_psi(read_psi(docker, image))
    verdict = decide(psi, limit)
    report = {"verdict": verdict, "psi": psi, "limit": limit, "top": [], "sources_missing": []}
    if verdict == "unknown":
        report["sources_missing"].append(f"Docker VM {PSI} (no answer)")
    elif verdict == "starved":
        report["top"] = top_containers(docker)[:5]
        report["message"] = message(psi, limit, report["top"])
    return report


def summary(report: dict) -> list[str]:
    if report["verdict"] != "starved":
        return []
    full = report["psi"]["full"]
    tops = ", ".join(f"{n} {b / 2**30:.1f}G" for n, b in report["top"])
    return [f"Docker VM starved of memory: full avg60={full['avg60']} avg300={full['avg300']} "
            f"(limit {report['limit']}) — top: {tops or 'docker stats did not answer'}"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-full-avg60", type=float)
    ap.add_argument("--docker", default="docker")
    ap.add_argument("--image", default="alpine:3")
    args = ap.parse_args()
    report = collect(args.max_full_avg60, args.docker, args.image)
    if args.json:
        print(json.dumps(report, indent=2))
    elif report["verdict"] == "unknown":
        print("UNKNOWN — " + report["sources_missing"][0])
    else:
        full = report["psi"]["full"]
        print(f"{report['verdict']}: full avg10={full['avg10']} avg60={full['avg60']} "
              f"avg300={full['avg300']} (limit {report['limit']})")
        print(report.get("message", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
