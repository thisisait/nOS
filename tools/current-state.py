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

THE JOIN (row plat-active-work-datatable): `work` must be a roadmap row's slug. `file` reads the roadmap
the way `nos dtt status` does (roadmap-status.py: the human door, GET only, never this tool's RW token)
and refuses an absent slug; an unreadable roadmap refuses too (UNKNOWN, nothing filed). `board` adds the
rows grouped by their step: open steps, closed steps (shipped / dropped / review), and orphans (absent).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
SLUG = "current-state"


def _load(mod: str):
    spec = importlib.util.spec_from_file_location(mod, REPO / "tools" / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


wa = _load("work-assignment")

#: A step in one of these is CLOSED, not gone (state/keap-tables/roadmap.table.yml status options).
CLOSED = ("shipped", "dropped", "review")


class RoadmapUnknown(Exception):
    """The roadmap could not be read: a refusal, never an empty roadmap."""


def roadmap_steps() -> dict[str, dict]:
    """slug -> {title, status}, read like `nos dtt status` (GET through the human door)."""
    try:
        rs = _load("roadmap-status")
        rows = [r.get("values", r) for r in rs.paged(rs.get, rs.BASE + "/rows")["data"]["rows"]]
    except (urllib.error.URLError, OSError, KeyError, ValueError, TypeError, SystemExit) as exc:
        raise RoadmapUnknown(str(exc)[:200] or type(exc).__name__) from None
    steps = {str(r["slug"]): {"title": r.get("title") or "", "status": r.get("status") or ""}
             for r in rows if r.get("slug")}
    if not steps:
        raise RoadmapUnknown("the roadmap answered with no rows")
    return steps


def group_by_step(rows: list[dict], steps: dict[str, dict]) -> dict[str, list]:
    """{"open": [(step, rows)], "closed": [(step, rows)], "orphans": [rows]} — pure, for the board."""
    by: dict[str, list] = {}
    orphans = []
    for r in rows:
        w = str(r.get("work") or "")
        (by.setdefault(w, []) if w in steps else orphans).append(r)
    out = {"open": [], "closed": [], "orphans": orphans}
    for w, rs in sorted(by.items()):
        out["closed" if steps[w]["status"] in CLOSED else "open"].append((w, rs))
    return out


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
    # Env first (a shell that exported it, or a host where the caller is not in
    # the docker group), the running container second — same order as
    # roadmap-update.py, so every tool resolves the token the same way.
    tok = os.environ.get("KEAP_AGENT_TOKEN_RW", "").strip()
    if tok:
        return tok
    try:
        return subprocess.run(
            ["docker", "exec", "iiab-keap-1", "printenv", "KEAP_AGENT_TOKEN_RW"],
            capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


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
    try:
        steps = roadmap_steps()
    except RoadmapUnknown as exc:
        print(f"REFUSED: roadmap UNKNOWN ({exc}): nothing filed", file=sys.stderr)
        return 2
    step = steps.get(a.work)
    if step is None:
        print(f"REFUSED: '{a.work}' is not a roadmap row: nothing filed", file=sys.stderr)
        return 2
    if step["status"] in CLOSED:
        print(f"  note: step {a.work} is {step['status']}", file=sys.stderr)
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
    rc = wa.main()
    try:
        steps, rows = roadmap_steps(), wa._live_rows(SLUG)
    except RoadmapUnknown as exc:
        print(f"\nby roadmap step: UNKNOWN (roadmap unreadable: {exc})")
        return rc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"\nby roadmap step: UNKNOWN (board unreadable: {str(exc)[:200]})")
        return rc
    g = group_by_step(rows, steps)
    for label, groups in (("open steps", g["open"]), ("closed steps", g["closed"])):
        print(f"\n{label} ({len(groups)}):")
        for w, rs in groups:
            print(f"  {w} [{steps[w]['status']}] {steps[w]['title'][:80]}")
            for r in rs:
                print(f"      {r.get('slug')} · {r.get('status')} · {r.get('claim') or 'unclaimed'}")
    print(f"\norphans ({len(g['orphans'])}): work names no roadmap row")
    for r in g["orphans"]:
        print(f"  {r.get('slug')} · work={r.get('work') or '(empty)'} · {r.get('status')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
