#!/usr/bin/env python3
"""Estate work happening OUTSIDE the control centre, and how to get to it.

WHY. The control centre only shows what it can see, and the operator's habit —
reasonably — is to run a converge in whatever terminal is already open. So the
one window built to answer "what is happening" can be the one window where a
converge is invisible, which is the surface's own failure mode arriving on day
one. This finds the work wherever it is and names the session it is in.

WHAT COUNTS AS ESTATE WORK, and why the list is short: a converge
(`ansible-playbook`), an agent run (`run-agent.sh`, `pulse-run-agent.sh`, the
`claude` CLI under a runner), and the `nos` CLI itself. Not "any busy pane" —
an operator compiling something is not estate work, and a tool that says so
gets muted.

HOW IT MAPS A PROCESS TO A PANE, and the version that did not work. The first
attempt walked UP from each interesting process to a pane pid, and found
nothing — because the estate's own tooling runs work through wrapper shells
whose command lines CONTAIN the words being searched for, so the upward walk
matched the wrapper and not the work, and the real child was never examined.

The reliable direction is DOWN. tmux gives every pane's shell pid; the work is a
descendant of that shell. So: one `ps` snapshot, build a children map, and walk
each pane's subtree. This also answers the question a name-match cannot —
`pane_current_command` says `php`, and only the subtree says which php.

WHAT IT WILL NOT DO: kill, attach, or switch anything. It prints the command
that would. A tool that grabs your terminal because it decided you were in the
wrong one is a tool you close.

Usage:
    tools/elsewhere-status.py            # what is running, and where
    tools/elsewhere-status.py --json
    tools/elsewhere-status.py --quiet    # print nothing when all is in-session

Exit 0 always.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

CC_SESSION = os.environ.get("NOS_CC_SESSION", "nos-cc")

#: What we consider estate work, and the label to report it under. Ordered:
#: the first pattern that matches a command line wins, so `run-agent.sh` is
#: recognised before the bare `claude` it eventually execs.
WORK = (
    (re.compile(r"\bansible-playbook\b"), "converge"),
    (re.compile(r"tools/run-[a-z-]*agent\.sh|pulse-run-agent\.sh"), "agent run"),
    (re.compile(r"\bbin/run-agent\.php\b"), "agent run (bound)"),
    (re.compile(r"files/vuln-scan/scan-runner\.sh"), "security scan"),
    (re.compile(r"(^|/)nos(\s|$)"), "nos CLI"),
)


def _ps() -> dict[int, tuple[int, str]]:
    out = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,command="], capture_output=True, text=True,
    ).stdout
    table: dict[int, tuple[int, str]] = {}
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        try:
            table[int(parts[0])] = (int(parts[1]), parts[2])
        except ValueError:
            continue
    return table


def _panes() -> dict[int, dict]:
    if subprocess.run(["which", "tmux"], capture_output=True).returncode != 0:
        return {}
    out = subprocess.run(
        ["tmux", "list-panes", "-a", "-F",
         "#{pane_pid}\t#{session_name}\t#{window_index}\t#{window_name}"],
        capture_output=True, text=True,
    ).stdout
    panes: dict[int, dict] = {}
    for line in out.splitlines():
        bits = line.split("\t")
        if len(bits) != 4:
            continue
        try:
            # INDEX, not name: tmux auto-renames a window after whatever it is
            # running, so the name of the window holding a converge is
            # "python3.13" — which reads as nonsense in a sentence about where
            # to go. The index is what you type.
            panes[int(bits[0])] = {
                "session": bits[1], "window": bits[2], "window_name": bits[3],
            }
        except ValueError:
            continue
    return panes


def _label(command: str) -> str | None:
    if "elsewhere-status" in command:
        return None   # this tool's own command line contains every pattern
    return next((name for pattern, name in WORK if pattern.search(command)), None)


def collect() -> dict:
    procs, panes = _ps(), _panes()

    children: dict[int, list[int]] = {}
    for pid, (ppid, _command) in procs.items():
        children.setdefault(ppid, []).append(pid)

    found = []
    claimed: set[int] = set()

    # DOWN from each pane, breadth-first, bounded. A pane's own shell is never
    # the work; its descendants are.
    for pane_pid, where in panes.items():
        queue, seen = list(children.get(pane_pid, [])), set()
        while queue:
            pid = queue.pop(0)
            if pid in seen:
                continue
            seen.add(pid)
            queue.extend(children.get(pid, []))
            command = procs.get(pid, (0, ""))[1]
            label = _label(command)
            if label:
                claimed.add(pid)
                found.append({
                    "pid": pid, "what": label, "command": command[:110],
                    "session": where["session"], "window": where["window"],
                    "attachable": True,
                })

    # Anything left is not under a pane at all: a launchd job, a cron child, a
    # plain terminal. That is not "elsewhere in tmux", it is "nowhere you can
    # attach to", and the two must not read alike.
    for pid, (_ppid, command) in procs.items():
        if pid in claimed:
            continue
        label = _label(command)
        if label:
            found.append({
                "pid": pid, "what": label, "command": command[:110],
                "session": None, "window": None, "attachable": False,
            })

    outside = [
        f for f in found
        if f["attachable"] and f["session"] != CC_SESSION
    ]
    detached = [f for f in found if not f["attachable"]]

    return {
        "control_centre": CC_SESSION,
        "control_centre_exists": subprocess.run(
            ["tmux", "has-session", "-t", f"={CC_SESSION}"],
            capture_output=True,
        ).returncode == 0,
        "work": found,
        "outside": outside,
        "not_in_tmux": detached,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true",
                    help="say nothing unless work is running outside")
    args = ap.parse_args()

    report = collect()
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    if not report["outside"] and not report["not_in_tmux"]:
        if not args.quiet:
            print("no estate work running outside the control centre")
        return 0

    for item in report["outside"]:
        print(f"⟶  {item['what']} running in tmux session "
              f"'{item['session']}' window {item['window']}, not in "
              f"{report['control_centre']}")
        print(f"   {item['command']}")

    for item in report["not_in_tmux"]:
        print(f"⟶  {item['what']} running outside tmux entirely (pid {item['pid']})")
        print(f"   {item['command']}")
        print("   nothing to attach to — a launchd job, a cron child, or a plain shell")

    if report["outside"]:
        cc = report["control_centre"]
        print(f"\n   to watch it from the control centre:")
        print(f"     tools/nos-cc.sh                    # attach ({cc})")
        # Deliberately printed, not executed. Moving somebody's terminal for
        # them is the one thing that would make this unwelcome.
        print(f"     tmux switch-client -t ={report['outside'][0]['session']}"
              f"   # or go to where it is")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
