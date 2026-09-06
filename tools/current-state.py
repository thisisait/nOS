#!/usr/bin/env python3
"""The currentState board's WRITE interface — file / claim / release / progress
(dtt-mcp-harness core, dtt-routing-address).

This is how an agent CLAIMS a row so parallel agents do not collide. It is the
reusable engine the in-process AgentKit tool and the external mcpo MCP server
both wrap; agents call it directly today. The rule that makes the routing
grammar load-bearing rather than advisory: **a claim is refused unless the
match says the claimer is capable** (assignment ⊆ capability, tools/
nos_work_uri.py) — an agent cannot take work it could not do. A human
(`user:<uid>`) may claim anything.

Atomicity is OPTIMISTIC (ponytail: read → check-claimable → write → re-read to
confirm the claim stuck; a lease that has expired is reclaimable). The estate's
agent concurrency is ~none and leases bound a stuck claim, so a compare-and-set
race is tolerable; the robust upgrade is a KEAP-side atomic claim endpoint when
concurrency rises.

    tools/current-state.py board                      # the live match report
    tools/current-state.py claim <slug> --as agent:x [--hours 4]
    tools/current-state.py release <slug>
    tools/current-state.py progress <slug> working|blocked|review|done
    tools/current-state.py file <slug> --title T --work W --task-type CO \
        [--where local --kam repo --note N]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
SLUG = "current-state"


def _load(mod: str):
    spec = importlib.util.spec_from_file_location(mod, REPO / "tools" / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


wa = _load("work-assignment")


# ── pure claim logic (gated offline) ─────────────────────────────────────────
def claimable(row: dict, now: int) -> bool:
    """A row is claimable if unclaimed, or its lease has expired."""
    if not (row.get("claim") or ""):
        return True
    lease = row.get("lease_until")
    try:
        return lease is not None and int(lease) < now
    except (TypeError, ValueError):
        return False  # a claim with no/invalid lease is held (never auto-steals)


def may_claim(row: dict, principal: str, capabilities: dict[str, str]) -> tuple[bool, str]:
    """(ok, reason). Refuses a non-claimable row, and an agent the match says
    cannot do the work. A human principal is always allowed."""
    if not claimable(row, int(time.time())):
        return False, f"already claimed by {row.get('claim')} (lease not expired)"
    if principal.startswith("user:"):
        return True, "human principal"
    name = principal.split(":", 1)[1] if ":" in principal else principal
    capable = wa.capable_agents(row, capabilities)
    if name not in capable:
        return False, (
            f"{principal} is not capable of {wa.assignment_address(row)} — "
            f"capable: {', '.join(capable) or 'none'}"
        )
    return True, "capable"


# ── live door I/O ────────────────────────────────────────────────────────────
def _tok() -> str:
    return subprocess.run(
        ["docker", "exec", "iiab-keap-1", "printenv", "KEAP_AGENT_TOKEN_RW"],
        capture_output=True, text=True, timeout=15).stdout.strip()


def _get_row(slug: str) -> dict | None:
    for r in wa._live_rows(SLUG):
        if r.get("slug") == slug:
            return r
    return None


def _post(fields: dict) -> int:
    req = urllib.request.Request(
        f"http://127.0.0.1:8091/agent/v1/tables/{SLUG}/rows",
        data=json.dumps(fields).encode(),
        headers={"Authorization": f"Bearer {_tok()}", "Content-Type": "application/json"},
        method="POST")
    try:
        return urllib.request.urlopen(req, timeout=20).status
    except urllib.error.HTTPError as e:
        print(f"  door: {e.code} {e.read().decode()[:160]}", file=sys.stderr)
        return e.code


def _claim(slug: str, principal: str, hours: int) -> int:
    row = _get_row(slug)
    if row is None:
        print(f"no such assignment: {slug}", file=sys.stderr)
        return 1
    ok, why = may_claim(row, principal, wa._capabilities())
    if not ok:
        print(f"REFUSED: {why}", file=sys.stderr)
        return 1
    now = int(time.time())
    st = _post({"slug": slug, "claim": principal, "lease_until": now + hours * 3600,
                "status": "claimed", "started_at": now})
    if st not in (200, 201):
        return 1
    # optimistic verify: re-read and confirm my claim stuck (last-writer wins)
    fresh = _get_row(slug)
    if fresh and fresh.get("claim") == principal:
        print(f"CLAIMED {slug} by {principal} (lease {hours}h)")
        return 0
    print(f"LOST {slug} — now held by {fresh.get('claim') if fresh else '?'}", file=sys.stderr)
    return 1


def _release(slug: str) -> int:
    if _get_row(slug) is None:
        print(f"no such assignment: {slug}", file=sys.stderr)
        return 1
    st = _post({"slug": slug, "claim": None, "lease_until": None, "status": "released"})
    print(f"RELEASED {slug}" if st in (200, 201) else f"release failed ({st})")
    return 0 if st in (200, 201) else 1


def _progress(slug: str, status: str) -> int:
    st = _post({"slug": slug, "status": status})
    print(f"{slug} -> {status}" if st in (200, 201) else f"failed ({st})")
    return 0 if st in (200, 201) else 1


def _file(a) -> int:
    row = {"slug": a.slug, "title": a.title, "work": a.work, "task_type": a.task_type,
           "where": a.where, "kam": a.kam, "status": "unclaimed"}
    if a.note:
        row["note"] = a.note
    st = _post(row)
    print(f"FILED {a.slug}" if st in (200, 201) else f"file failed ({st})")
    return 0 if st in (200, 201) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("board")
    c = sub.add_parser("claim"); c.add_argument("slug"); c.add_argument("--as", dest="principal", required=True); c.add_argument("--hours", type=int, default=4)
    r = sub.add_parser("release"); r.add_argument("slug")
    p = sub.add_parser("progress"); p.add_argument("slug"); p.add_argument("status", choices=["working", "blocked", "review", "done"])
    f = sub.add_parser("file")
    f.add_argument("slug"); f.add_argument("--title", required=True); f.add_argument("--work", required=True)
    f.add_argument("--task-type", dest="task_type", required=True); f.add_argument("--where", default="local")
    f.add_argument("--kam", default="repo"); f.add_argument("--note", default="")
    a = ap.parse_args()

    if a.cmd == "board":
        return _board()
    if a.cmd == "claim":
        return _claim(a.slug, a.principal, a.hours)
    if a.cmd == "release":
        return _release(a.slug)
    if a.cmd == "progress":
        return _progress(a.slug, a.status)
    if a.cmd == "file":
        return _file(a)
    return 2


def _board() -> int:
    sys.argv = ["work-assignment.py"]
    return wa.main()


if __name__ == "__main__":
    sys.exit(main())
