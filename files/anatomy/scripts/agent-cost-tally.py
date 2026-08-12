#!/usr/bin/env python3
"""Daily agent-cost tally — reads agent_run_end events, reports spend, notifies.

WHY THIS EXISTS
    pulse-run-agent.sh now persists `cost_usd` + `cost_basis` into every
    agent_run_end event (REM/readiness item 2). A number nobody reads is the
    estate's recurring shape, so this job sums the last window and, above a
    floor, fires an A9 notification where the operator will see it.

HONESTY CONTRACT (the reason cost_basis exists)
    claude-CLI's total_cost_usd is ALWAYS priced against Anthropic's rate table.
    When a job runs against a non-Anthropic backend (ANTHROPIC_BASE_URL points
    elsewhere) that dollar figure is fiction. pulse-run-agent.sh drops the figure
    and stamps `cost_basis: foreign:<host>` in that case. So here:
      * dollars are summed ONLY from basis=="anthropic" rows (truthful spend);
      * foreign / basis-less rows are counted and their TOKENS reported, with NO
        invented dollar total — absence is rendered as absence, never as $0 calm.

    A notification fires when truthful spend >= floor OR any run was unpriced
    (foreign backend) — so foreign-backend usage can never spend in silence.

USAGE
    agent-cost-tally.py            # last 24h, floor from env
    env vars:
      WING_DATA_DIR            wing.db dir     (default ~/wing/app/data)
      WING_API_URL             notif endpoint  (default http://127.0.0.1:9000)
      WING_EVENTS_HMAC_SECRET  HMAC key for /api/v1/notifications (required to notify)
      NOS_COST_TALLY_WINDOW_H  window hours    (default 24)
      NOS_COST_TALLY_FLOOR_USD dollar floor    (default 5.00)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _db_path() -> Path:
    d = os.environ.get("WING_DATA_DIR") or str(Path.home() / "wing" / "app" / "data")
    return Path(d) / "wing.db"


def _window_start(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def gather(db: Path, since_iso: str) -> dict:
    """Sum agent_run_end rows since `since_iso`. Truthful dollars only."""
    tally = {
        "runs": 0,
        "priced_runs": 0,
        "unpriced_runs": 0,
        "cost_usd": 0.0,          # basis=anthropic only
        "tokens_input": 0,
        "tokens_output": 0,
        "tokens_cache_read": 0,
        "foreign_bases": {},      # host -> run count
        "by_agent": {},           # agent -> {"cost": x, "runs": n}
    }
    if not db.exists():
        tally["error"] = f"wing.db not found at {db}"
        return tally
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cur = con.execute(
            "SELECT source, result_json FROM events "
            "WHERE type='agent_run_end' AND ts >= ? ORDER BY ts",
            (since_iso,),
        )
        rows = cur.fetchall()
    finally:
        con.close()

    for source, result_json in rows:
        try:
            r = json.loads(result_json or "{}")
        except (ValueError, TypeError):
            r = {}
        tally["runs"] += 1
        for col in ("tokens_input", "tokens_output", "tokens_cache_read"):
            v = r.get(col)
            if isinstance(v, (int, float)):
                tally[col] += int(v)
        basis = r.get("cost_basis")
        cost = r.get("cost_usd")
        agent = source or "?"
        agent_row = tally["by_agent"].setdefault(agent, {"cost": 0.0, "runs": 0})
        agent_row["runs"] += 1
        # Truthful dollars: basis anthropic AND a numeric figure present.
        if basis == "anthropic" and isinstance(cost, (int, float)):
            tally["priced_runs"] += 1
            tally["cost_usd"] += float(cost)
            agent_row["cost"] += float(cost)
        else:
            # Foreign backend, OR a legacy row with no basis recorded at all.
            tally["unpriced_runs"] += 1
            if isinstance(basis, str) and basis.startswith("foreign:"):
                host = basis.split(":", 1)[1]
                tally["foreign_bases"][host] = tally["foreign_bases"].get(host, 0) + 1
    return tally


def render(tally: dict, window_h: float, floor: float) -> str:
    lines = [
        f"# Agent cost tally — last {window_h:g}h",
        "",
        f"- runs: {tally['runs']} "
        f"({tally['priced_runs']} priced, {tally['unpriced_runs']} unpriced)",
        f"- truthful spend (basis=anthropic): ${tally['cost_usd']:.4f} "
        f"(floor ${floor:.2f})",
        f"- tokens: in={tally['tokens_input']} out={tally['tokens_output']} "
        f"cache_read={tally['tokens_cache_read']}",
    ]
    if tally["unpriced_runs"]:
        fb = tally.get("foreign_bases") or {}
        if fb:
            detail = ", ".join(f"{h}×{n}" for h, n in sorted(fb.items()))
            lines.append(
                f"- UNPRICED: {tally['unpriced_runs']} run(s) on a non-Anthropic "
                f"backend ({detail}) — tokens counted above, no dollar figure is "
                f"truthful for these."
            )
        else:
            lines.append(
                f"- UNPRICED: {tally['unpriced_runs']} run(s) carried no cost_basis "
                f"(legacy events pre-dating cost persistence) — not counted in $."
            )
    top = sorted(
        tally["by_agent"].items(), key=lambda kv: kv[1]["cost"], reverse=True
    )[:5]
    if any(v["cost"] for _, v in top):
        lines.append("- top agents by spend:")
        for agent, v in top:
            if v["cost"]:
                lines.append(f"    - {agent}: ${v['cost']:.4f} ({v['runs']} run)")
    if "error" in tally:
        lines.append(f"- NOTE: {tally['error']}")
    return "\n".join(lines)


def notify(severity: str, title: str, body: str) -> int:
    """POST an A9 notification with the same HMAC contract pulse-run-agent uses."""
    url = os.environ.get("WING_API_URL", "http://127.0.0.1:9000")
    secret = os.environ.get("WING_EVENTS_HMAC_SECRET", "")
    if not secret:
        sys.stderr.write("WARN: WING_EVENTS_HMAC_SECRET unset — cannot notify\n")
        return 0
    payload_obj = {
        "severity": severity,
        "title": title,
        "body": body,
        "origin_agent": "cost-tally",
        "actor_id": "agent:cost-tally",
        "actor_action_id": f"cost-tally-{int(time.time())}",
    }
    # Canonical body: jq -a --sort-keys -nc equivalent (sorted keys, compact,
    # ensure_ascii to match jq's -a). The Bone verifier re-canonicalises, but
    # matching here keeps the signed bytes identical to what we send.
    payload = json.dumps(payload_obj, sort_keys=True, separators=(",", ":"))
    ts = str(int(time.time()))
    sig = hmac.new(
        secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256
    ).hexdigest()
    req = urllib.request.Request(
        f"{url}/api/v1/notifications",
        data=payload.encode(),
        headers={
            "X-Wing-Timestamp": ts,
            "X-Wing-Signature": sig,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except Exception as exc:  # noqa: BLE001 — a notif failure must not crash the job
        sys.stderr.write(f"WARN: notification POST failed: {exc}\n")
        return 0


def main() -> int:
    window_h = float(os.environ.get("NOS_COST_TALLY_WINDOW_H", "24"))
    floor = float(os.environ.get("NOS_COST_TALLY_FLOOR_USD", "5.00"))
    since = _window_start(window_h)
    tally = gather(_db_path(), since)
    report = render(tally, window_h, floor)
    print(report)

    breach = tally["cost_usd"] >= floor
    unpriced = tally["unpriced_runs"] > 0
    if breach or unpriced:
        if tally["cost_usd"] >= floor * 3:
            sev = "critical"
        elif breach:
            sev = "high"
        else:
            sev = "low"  # foreign-backend usage surfaced, but under the dollar floor
        title = (
            f"Agent spend ${tally['cost_usd']:.2f}/{window_h:g}h"
            + (f" +{tally['unpriced_runs']} unpriced" if unpriced else "")
        )
        code = notify(sev, title, report)
        print(f"INFO: notification sev={sev} http={code}")
    else:
        print("INFO: under floor, no unpriced runs — no notification")
    return 0


if __name__ == "__main__":
    sys.exit(main())
