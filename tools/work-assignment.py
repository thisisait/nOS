#!/usr/bin/env python3
"""Derive a currentState row's nos-work:// ASSIGNMENT address + match it to
agents (dtt-routing-address, the assignment side).

Symmetric to tools/agent-capability.py (the capability side). An assignment is
a currentState row's NEED, expressed as an address the planner matches against
held capabilities via `assignment ⊆ capability` (tools/nos_work_uri.py):

    nos-work://<where>/*/<kam>/<task_type>/<lease_until|*>

  WHERE  the row's `where` (`any` ⇒ *; the planner may place it anywhere a
         capability allows).
  WHO    always * on an assignment — it names no principal; the matcher finds
         which agents CAN take it (and a claim records which one did).
  KAM    the row's `kam` scope set (empty ⇒ *).
  CO     the row's `task_type`.
  KDY    the row's `lease_until` (a deadline) or * — a scheduling constraint,
         not part of the ⊆ match.

Pure functions (assignment_address, capable_agents) are the offline definition,
gated by tests/anatomy/test_work_assignment_matches.py. Live mode reads the
current-state table through the agent door and prints, per row, its address, its
claim, and which agents could satisfy it — the read-only match the Routing view
renders (loop DISPATCH from this stays a later, default-off change).

    tools/work-assignment.py            # live match report (needs KEAP)
    tools/work-assignment.py --json     # {slug: {address, claim, status, capable}}
    tools/work-assignment.py --check    # exit 1 if any live assignment is unparseable
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import subprocess
import sys
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import nos_work_uri  # noqa: E402


def _load(mod: str):
    spec = importlib.util.spec_from_file_location(mod, REPO / "tools" / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_capmod = _load("agent-capability")


def assignment_address(row: dict) -> str:
    """currentState row → its nos-work:// assignment address (pure)."""
    where = row.get("where") or "any"
    if where == "any":
        where = "*"
    kam = row.get("kam") or "*"
    task_type = row.get("task_type")
    if not task_type:
        raise ValueError(f"row {row.get('slug')!r} has no task_type — cannot address it")
    kdy = row.get("lease_until") or "*"
    return f"nos-work://{where}/*/{kam}/{task_type}/{kdy}"


def capable_agents(row: dict, capabilities: dict[str, str]) -> list[str]:
    """Names of agents whose capability satisfies this assignment (pure)."""
    asg = nos_work_uri.parse(assignment_address(row))
    out = []
    for name, cap_addr in capabilities.items():
        if nos_work_uri.satisfies(nos_work_uri.parse(cap_addr), asg):
            out.append(name)
    return sorted(out)


def _capabilities() -> dict[str, str]:
    return {d["name"]: a for d in _capmod._agents()
            if (a := _capmod.capability(d)) is not None}


def _live_rows(slug: str = "current-state") -> list[dict]:
    tok = subprocess.run(
        ["docker", "exec", "iiab-keap-1", "printenv", "KEAP_AGENT_TOKEN_RW"],
        capture_output=True, text=True, timeout=15).stdout.strip()
    req = urllib.request.Request(
        f"http://127.0.0.1:8091/agent/v1/tables/{slug}/rows",
        headers={"Authorization": f"Bearer {tok}"})
    d = json.load(urllib.request.urlopen(req, timeout=20))
    data = d.get("data", d)
    return data.get("rows", []) if isinstance(data, dict) else (data or [])


def _report() -> dict:
    caps = _capabilities()
    out = {}
    for row in _live_rows():
        try:
            addr = assignment_address(row)
            capable = capable_agents(row, caps)
            err = None
        except Exception as e:  # noqa: BLE001
            addr, capable, err = None, [], str(e)
        out[row.get("slug")] = {
            "address": addr, "claim": row.get("claim") or "", "status": row.get("status"),
            "capable": capable, "error": err,
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    rep = _report()
    if args.check:
        bad = [f"{s}: {r['error']}" for s, r in rep.items() if r["error"]]
        if bad:
            print("unparseable assignments:\n  " + "\n  ".join(bad), file=sys.stderr)
            return 1
        print(f"work-assignment: {len(rep)} assignments parse + matched")
        return 0
    if args.json:
        print(json.dumps(rep, indent=2))
        return 0
    if not rep:
        print("current-state is empty — no assignments filed yet.")
        return 0
    for slug, r in rep.items():
        held = f"claimed by {r['claim']}" if r["claim"] else "UNCLAIMED"
        print(f"{slug}  [{r['status']}, {held}]")
        print(f"    {r['address']}")
        print(f"    capable: {', '.join(r['capable']) or 'NONE — no agent can take this'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
