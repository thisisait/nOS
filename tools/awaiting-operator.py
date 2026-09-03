#!/usr/bin/env python3
"""What is waiting for a HUMAN right now, across every source that asks for one.

WHY THIS EXISTS. `red-status.py` answers "what is broken"; this answers a
different question the same operator has to ask several times a day — "what
cannot proceed without me". They are not the same list. A judged proposal that
never landed is not broken; a signed ruling amended after signing is not red;
an agent that stopped to ask a question is working exactly as designed. None of
them move until a person acts, and until 2026-08-29 nothing collected them.

WHAT IT IS NOT. It does not approve, sign, answer, land or clear anything, and
it never will — the same rule the other readers in this directory carry. Half
the defects this estate has paid for were a success marker written by the code
that attempted the work; a reader that could also act would eventually be asked
to certify its own action.

Sources, and where each one is READ from rather than inferred:

  * `agent_questions`   — an agent stopped and asked (`AskOperatorTool`).
  * `notifications`     — unread CRITICAL/HIGH in the Wing inbox.
  * loop proposals      — judged and never landed; delegated to
                          `tools/loop-status.py::awaiting()` rather than
                          re-deriving the join, because two implementations of
                          "is this patch in the tree" is two things to be wrong.
  * `files/anatomy/apex/ruling.yml` — a SIGNED allow-list. Its signature is a
    status flag and a name, not a digest over the content, so an amendment
    after signing is invisible: this reader compares the ruled set against the
    digest recorded at signing time and says so when they differ.

Usage:
    tools/awaiting-operator.py            # the list, most urgent first
    tools/awaiting-operator.py --json     # for a caller
    tools/awaiting-operator.py --quiet    # count only

Exit 0 always, including when everything is waiting. Reporting IS its job.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import pathlib
import sqlite3
import sys
from datetime import datetime, timezone

REPO = pathlib.Path(__file__).resolve().parents[1]
WING_DB = pathlib.Path.home() / "wing" / "app" / "data" / "wing.db"
RULING = REPO / "files/anatomy/apex/ruling.yml"

#: Rank. The operator reads top-down and stops when they run out of evening.
URGENCY = {"question": 0, "signature": 1, "inbox": 2, "proposal": 3}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age(raw: str | None) -> str:
    if not raw:
        return "unknown age"
    try:
        when = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return "unknown age"
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delta = _now() - when
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{int(delta.total_seconds() / 60)} min"
    if hours < 48:
        return f"{hours:.0f} h"
    return f"{delta.days} d"


def _db() -> tuple[sqlite3.Connection | None, str]:
    # 2026-08-20 measurement, bit again 2026-09-03 (agent-status): a bare
    # mode=ro open dies once Wing checkpoints and drops the WAL sidecars.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_ledger_open", REPO / "tools" / "_ledger_open.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.open_ledger_ro(WING_DB)


def questions(conn: sqlite3.Connection) -> list[dict]:
    """An agent suspended itself waiting for an answer. Nothing else it was
    doing proceeds until someone replies."""
    try:
        rows = conn.execute(
            "SELECT uuid, agent_name, severity, prompt, created_at, expires_at, "
            "       default_on_expiry "
            "  FROM agent_questions WHERE answered_at IS NULL ORDER BY created_at"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{
        "kind": "question",
        "what": f"{r['agent_name']} asked: {(r['prompt'] or '')[:90]}",
        "severity": r["severity"] or "medium",
        "age": _age(r["created_at"]),
        "where": f"/inbox — question {r['uuid'][:8]}",
        # An expiry that defaults to anything but refusal is a decision made by
        # silence, which is the shape this estate refuses everywhere else.
        "note": (f"expires {r['expires_at']}, then {r['default_on_expiry']}"
                 if r["expires_at"] else None),
    } for r in rows]


def inbox(conn: sqlite3.Connection) -> list[dict]:
    try:
        rows = conn.execute(
            "SELECT uuid, severity, title, created_at FROM notifications "
            " WHERE wing_inbox_read_at IS NULL AND superseded_at IS NULL "
            "   AND severity IN ('critical','high') ORDER BY created_at"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{
        "kind": "inbox",
        "what": (r["title"] or "")[:90],
        "severity": r["severity"],
        "age": _age(r["created_at"]),
        "where": f"/inbox — {r['uuid'][:8]}",
        "note": None,
    } for r in rows]


def proposals() -> list[dict] | None:
    """Delegated to loop-status, which already owns the join. None when that
    reader cannot load — UNKNOWN, not an empty queue."""
    spec = importlib.util.spec_from_file_location(
        "_loop_status", REPO / "tools" / "loop-status.py")
    if spec is None or spec.loader is None:
        return None
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        report = mod.awaiting()
    except Exception:  # noqa: BLE001 — any failure is the same answer: cannot ask
        return None
    if report.get("error"):
        return None
    return [{
        "kind": "proposal",
        "what": f"{r['weakness_id']} judged {r['state']}, never landed",
        "severity": "medium",
        "age": _age(r.get("verdict_at")),
        "where": f"loop proposal {r['uuid'][:8]}",
        "note": None,
    } for r in report.get("unlanded", [])]


def ruling() -> list[dict] | None:
    """A signature that is a flag, not a digest.

    `status: SIGNED` plus `signed_by:` says someone once signed something. It
    does not say they signed THIS. Amended 2026-08-29 by a session that added
    two withheld nodes; nothing noticed, and nothing could have. Until the
    ruling records a digest of what was signed, this reader compares against
    `signed_digest:` if present and reports the absence of one honestly.
    """
    if not RULING.is_file():
        return None
    text = RULING.read_text(encoding="utf-8")
    signed = "status: SIGNED" in text
    recorded = None
    for line in text.splitlines():
        if line.startswith("signed_digest:"):
            recorded = line.split(":", 1)[1].strip().strip('"')
            break
    if not signed:
        return [{
            "kind": "signature", "severity": "high",
            "what": "the apex ruling is not SIGNED — the public build is preview-only",
            "age": "-", "where": str(RULING.relative_to(REPO)), "note": None,
        }]
    if recorded is None:
        return [{
            "kind": "signature", "severity": "medium",
            "what": "the apex ruling is SIGNED with no digest of what was signed",
            "age": "-", "where": str(RULING.relative_to(REPO)),
            "note": "an amendment after signing is invisible; add signed_digest:",
        }]
    actual = hashlib.sha256(
        "".join(l for l in text.splitlines(keepends=True)
                if not l.startswith("signed_digest:")).encode()
    ).hexdigest()
    if actual != recorded:
        return [{
            "kind": "signature", "severity": "high",
            "what": "the apex ruling was AMENDED after it was signed",
            "age": "-", "where": str(RULING.relative_to(REPO)),
            "note": "read the change and re-sign, or revert it",
        }]
    return []


def collect() -> dict:
    items: list[dict] = []
    unknown: list[str] = []

    conn, how = _db()
    if conn is None:
        unknown.append(f"{WING_DB} — {how}; questions and inbox are UNKNOWN")
    else:
        with conn:
            items += questions(conn)
            items += inbox(conn)
        conn.close()

    p = proposals()
    if p is None:
        unknown.append("tools/loop-status.py — could not load; unlanded proposals UNKNOWN")
    else:
        items += p

    r = ruling()
    if r is None:
        unknown.append(f"{RULING} — missing; the signature state is UNKNOWN")
    else:
        items += r

    items.sort(key=lambda i: (URGENCY.get(i["kind"], 9), i["severity"] != "critical"))
    return {"generated_at": _now().isoformat(), "items": items, "unknown": unknown}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="the count line only")
    args = ap.parse_args()

    report = collect()
    items, unknown = report["items"], report["unknown"]

    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    if not items and not unknown:
        print("nothing awaits you — every source read, none asking")
        return 0

    print(f"{len(items)} awaiting you:")
    if not args.quiet:
        for i in items:
            sev = i["severity"].upper()[:4]
            print(f"  {i['kind']:9} {sev:5} {i['age']:>7}  {i['what']}")
            print(f"  {'':9} {'':5} {'':>7}  {i['where']}"
                  + (f" · {i['note']}" if i.get("note") else ""))
    for u in unknown:
        print(f"  ? source unreadable, so its state is UNKNOWN not empty: {u}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
