#!/usr/bin/env python3
"""Is this Linux host running what it has installed: pending reboot, stale kernel, -security updates.

Measured 2026-11-03: a remote kernel CVE was fixed by a package the host could install, and
nothing said the host still ran the old kernel. unattended-upgrades installs -security with
Automatic-Reboot false, so the fix waits on a reboot nobody is told about. Red here:
/var/run/reboot-required older than a day, a running kernel older than the newest in /boot,
and -security upgrades apt lists as pending. red-status reads collect()/summary().
Not Linux = UNKNOWN (not read). An unreadable source is UNKNOWN, never green. Reads only.

Usage:
    tools/host-patch-status.py [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time

REBOOT_GRACE_DAYS = 1  # unattended-upgrades runs nightly; a same-day flag is normal


def _ver(release: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", release))


def collect(now: float | None = None) -> dict:
    now = now or time.time()
    platform = os.environ.get("NOS_HOST_PLATFORM", sys.platform)
    report: dict = {"linux": platform.startswith("linux"), "reboot": None, "kernel": None,
                    "security": None, "sources_missing": []}
    if not report["linux"]:
        return report  # not applicable: main() says UNKNOWN, red-status stays quiet
    root = pathlib.Path(os.environ.get("NOS_HOST_ROOT", "/"))
    flag = root / "var/run/reboot-required"
    try:
        pkgs = root / "var/run/reboot-required.pkgs"
        report["reboot"] = {"days": int((now - flag.stat().st_mtime) // 86400),
                            "pkgs": pkgs.read_text().split() if pkgs.is_file() else []}
    except FileNotFoundError:
        report["reboot"] = False
    except OSError as exc:
        report["sources_missing"].append(f"{flag} ({exc.strerror})")
    running = os.environ.get("NOS_HOST_KERNEL") or os.uname().release
    installed = sorted((p.name[len("vmlinuz-"):] for p in (root / "boot").glob("vmlinuz-*")), key=_ver)
    if installed:
        report["kernel"] = {"running": running, "newest": installed[-1],
                            "stale": _ver(installed[-1]) > _ver(running)}
    else:
        report["sources_missing"].append(f"{root / 'boot'}/vmlinuz-* (none)")
    try:
        out = subprocess.run([os.environ.get("NOS_APT", "apt"), "list", "--upgradable"],
                             capture_output=True, text=True, timeout=60)
        if out.returncode:
            raise OSError(out.returncode, "rc")
        report["security"] = [ln.split("/")[0] for ln in out.stdout.splitlines() if "-security" in ln]
    except (OSError, subprocess.TimeoutExpired):
        report["sources_missing"].append("apt list --upgradable (no answer)")
    return report


def summary(report: dict) -> list[str]:
    out = []
    rb = report.get("reboot")
    if rb and rb["days"] >= REBOOT_GRACE_DAYS:
        out.append(f"reboot pending {rb['days']} days ({', '.join(rb['pkgs'][:4]) or 'no package list'})")
    k = report.get("kernel")
    if k and k["stale"]:
        out.append(f"running kernel {k['running']} but {k['newest']} is installed — the fix loads on reboot")
    sec = report.get("security")
    if sec:
        out.append(f"{len(sec)} -security update(s) pending: {', '.join(sec[:6])}" + (" …" if len(sec) > 6 else ""))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    report = collect()
    if ap.parse_args().json:
        print(json.dumps(report, indent=2))
        return 0
    if not report["linux"]:
        print("UNKNOWN — not a Linux host; its patch state is not read here")
        return 0
    for line in summary(report) or ["host runs what it has installed; no -security update pending"]:
        print(line)
    for m in report["sources_missing"]:
        print(f"UNKNOWN — {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
