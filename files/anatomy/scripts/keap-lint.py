#!/usr/bin/env python3
"""keap-lint — nightly knowledge-lint run over the KEAP (cortex) corpus.

Pulse job (keap-base plugin). Fires POST /agent/v1/lint/run (the container
runs the deterministic checks: broken refs, duplicates, deserts, substrate
drift — see nos-keap server/lint.ts) and fans the outcome into the A9
notification path — but ONLY when the run surfaced NEW findings. Standing
findings never re-alert; the full report stays queryable at
GET /agent/v1/lint and the Admin /api/lint.

Severity routing mirrors keap-base's notification block:
  new critical/high  -> high   (wing-inbox + ntfy)
  new medium         -> medium (wing-inbox)
  new low/info only  -> no notification (report-only)

Env (Pulse-rendered):
  KEAP_API_URL          default http://127.0.0.1:8091
  KEAP_AGENT_TOKEN_RW   required (lint/run is a write — it reconciles state)
  NOS_NOTIFY_BIN        path to nos-notify.sh (optional; unset = report-only)

Exit codes: 0 ran (with or without findings), 1 config error, 2 KEAP unreachable.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

KEAP_API_URL = os.environ.get("KEAP_API_URL", "http://127.0.0.1:8091").rstrip("/")
TOKEN_RW = os.environ.get("KEAP_AGENT_TOKEN_RW", "")
NOTIFY_BIN = os.environ.get("NOS_NOTIFY_BIN", "")


def notify(severity: str, title: str, body: str, channels: str) -> None:
    if not NOTIFY_BIN or not os.path.exists(NOTIFY_BIN):
        return
    # nos-notify.sh is best-effort by contract (silent no-op on missing
    # deps/secret) — never let it fail the lint run.
    subprocess.run(  # noqa: S603 — fixed argv, no shell
        [NOTIFY_BIN, severity, title, body, channels],
        check=False,
        timeout=30,
    )


def main() -> int:
    if not TOKEN_RW:
        print("keap-lint: KEAP_AGENT_TOKEN_RW not set", file=sys.stderr)
        return 1

    req = urllib.request.Request(
        f"{KEAP_API_URL}/agent/v1/lint/run",
        data=b"{}",
        method="POST",
    )
    req.add_header("content-type", "application/json")
    req.add_header("authorization", f"Bearer {TOKEN_RW}")
    req.add_header("x-keap-agent", "keap-lint")
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            report = json.loads(res.read().decode())["data"]
    except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
        print(f"keap-lint: KEAP unreachable or bad response: {exc}", file=sys.stderr)
        notify("high", "KEAP lint failed", f"lint/run unreachable: {exc}", "wing-inbox,ntfy")
        return 2

    counts = report.get("counts", {})
    new_by_sev = report.get("newBySeverity", {})
    summary = (
        f"open {report.get('open', 0)} "
        f"(crit {counts.get('critical', 0)} / high {counts.get('high', 0)} / "
        f"med {counts.get('medium', 0)} / low {counts.get('low', 0)} / info {counts.get('info', 0)}) · "
        f"new {report.get('new', 0)} · resolved {report.get('resolved', 0)}"
    )
    print(f"keap-lint: {summary}")

    new_high = new_by_sev.get("critical", 0) + new_by_sev.get("high", 0)
    new_medium = new_by_sev.get("medium", 0)
    if new_high or new_medium:
        # Lead the body with the worst NEW findings so the inbox row is useful
        # without opening the report.
        worst = [
            f"[{f['severity']}] {f['checkId']}: {f['message']}"
            for f in report.get("findings", [])
            if f["severity"] in ("critical", "high", "medium")
        ][:5]
        body = f"Knowledge lint: {summary}\n" + "\n".join(worst)
        if new_high:
            notify("high", "KEAP lint: new high findings", body, "wing-inbox,ntfy")
        else:
            notify("medium", "KEAP lint: new findings", body, "wing-inbox")
    return 0


if __name__ == "__main__":
    sys.exit(main())
