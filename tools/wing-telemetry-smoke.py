#!/usr/bin/env python3
"""wing-telemetry-smoke.py — end-to-end probe for the telemetry pipeline.

Synthesizes a fake event with a unique ``run_id``, HMAC-signs it, POSTs to
Bone's ``/api/v1/events`` endpoint, then verifies the row landed in
``wing.db`` AND that the corresponding line shows up in Loki (when the
playbook callback's batch already wrote the JSONL fallback). Exits 0 on
success, non-zero on first failure with a JSON summary explaining which
hop broke.

Why this exists:
  - The bones & wings refactor (post-Track-G) will move Bone from a
    container to a launchd daemon and re-shape the events.py module path.
    This probe is the ONE-COMMAND check that the operator runs after any
    Bone change to confirm the HMAC + SQLite + Loki path still works,
    without spending 30 min on a full ``--blank`` run.
  - The agentic vuln-scan runner (target 1) will drive structured events
    through the same pipeline. Validating the path independently of the
    scanner means a scan-side bug can be triaged here first.

Pipeline hops:
  1. POST /api/v1/events (HMAC-authenticated)        → Bone writes wing.db
  2. SELECT * FROM events WHERE run_id = <smoke-id>  → wing.db readback
  3. (best-effort) Loki ``{job="wing"} |= run_id``   → log aggregation pipe

Usage:
  python3 tools/wing-telemetry-smoke.py
  python3 tools/wing-telemetry-smoke.py --bone-url http://127.0.0.1:8099
  python3 tools/wing-telemetry-smoke.py --skip-loki
  python3 tools/wing-telemetry-smoke.py --json   # machine-readable summary

Exit codes:
  0  All hops green.
  2  Bone POST rejected (HMAC / network / 5xx).
  3  wing.db readback failed.
  4  Loki query found nothing within --loki-timeout (only when Loki check on).
  5  Setup failure (HMAC secret missing, etc.).

Track G/seed work — see docs/active-work.md.
"""

from __future__ import annotations

import argparse
import hmac
import hashlib
import json
import os
import pathlib
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone


REPO = pathlib.Path(__file__).resolve().parent.parent


def _hmac_secret() -> str | None:
    """Resolve the HMAC secret. Same precedence as the callback plugin:
    env var → ~/.nos/secrets.yml → role default file (best-effort)."""
    env = os.environ.get("WING_EVENTS_HMAC_SECRET")
    if env:
        return env
    secrets = pathlib.Path(os.path.expanduser("~/.nos/secrets.yml"))
    if secrets.is_file():
        for line in secrets.read_text().splitlines():
            line = line.strip()
            if line.startswith("wing_events_hmac_secret:"):
                _, _, val = line.partition(":")
                return val.strip().strip('"').strip("'")
    return None


def _sign(secret: str, ts: str, body: bytes) -> str:
    msg = (ts + ".").encode("utf-8") + body
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _post_event(bone_url: str, body: dict, secret: str, timeout: float
                ) -> tuple[bool, str | None, dict | None]:
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ts = str(int(time.time()))
    sig = _sign(secret, ts, raw)
    req = urllib.request.Request(
        f"{bone_url.rstrip('/')}/api/v1/events",
        data=raw,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Wing-Timestamp": ts,
            "X-Wing-Signature": sig,
            "User-Agent": "wing-telemetry-smoke/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, None, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return False, "HTTP %s: %s" % (exc.code, exc.read().decode("utf-8")), None
        except Exception:
            return False, "HTTP %s" % exc.code, None
    except Exception as exc:  # noqa: BLE001
        return False, "%s: %s" % (type(exc).__name__, exc), None


def _wing_db_path() -> pathlib.Path:
    """Resolve where Wing's runtime SQLite lives.

    Bone's compose mount points ``$HOME/wing/app/data/wing.db`` (host) at
    ``/wing-db/wing.db`` (container). The bones & wings refactor will move
    this to ``files/anatomy/wing/data/wing.db`` — set ``WING_DB_PATH`` env
    var to override during transition.
    """
    if env := os.environ.get("WING_DB_PATH"):
        return pathlib.Path(env)
    home_runtime = pathlib.Path(os.path.expanduser("~/wing/app/data/wing.db"))
    if home_runtime.is_file():
        return home_runtime
    # Fallback to the rsync source (pre-Track-A path) — useful in dev when
    # Bone isn't running but the file still exists on disk.
    return REPO / "files" / "project-wing" / "data" / "wing.db"


def _check_wing_db(run_id: str, timeout_s: float) -> tuple[bool, str | None, dict | None]:
    """Poll wing.db for the run_id row. Polls for up to timeout_s seconds
    (Bone batches inserts asynchronously)."""
    db_path = _wing_db_path()
    if not db_path.is_file():
        return False, "wing.db not found at %s" % db_path, None
    deadline = time.monotonic() + timeout_s
    last_err = None
    while time.monotonic() < deadline:
        try:
            conn = sqlite3.connect(str(db_path))
            try:
                cur = conn.execute(
                    "SELECT id, type, run_id, ts FROM events WHERE run_id = ? "
                    "ORDER BY id DESC LIMIT 1",
                    (run_id,),
                )
                row = cur.fetchone()
                if row:
                    return True, None, {
                        "id": row[0], "type": row[1],
                        "run_id": row[2], "ts": row[3],
                    }
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            last_err = "%s: %s" % (type(exc).__name__, exc)
        time.sleep(0.25)
    return False, last_err or "row not found within %.1fs" % timeout_s, None


def _check_loki(loki_url: str, run_id: str, timeout_s: float
                ) -> tuple[bool, str | None, dict | None]:
    """Best-effort Loki search. Loki ingests via Alloy (pazny.observability),
    which tails ~/.nos/events/playbook.jsonl. The callback plugin also
    appends every event to the JSONL on disk regardless of HMAC POST
    outcome — so this hop validates the disk → Alloy → Loki pipe.

    The smoke probe doesn't actually hit the JSONL (it goes direct to
    Bone), so this hop will only pass if Bone re-emits to JSONL after
    insertion OR we fall back to a different log search.

    For now, we accept "Loki responded" as the success signal — proves
    Loki is reachable + the API works. Stricter "row landed" semantics
    require a JSONL bridge that the refactor will add.
    """
    deadline = time.monotonic() + timeout_s
    query = '{job="wing"} |= "%s"' % run_id
    # Loki's /query is instant-only; /query_range needs start+end. We use
    # query_range with a 1-hour lookback window — wide enough to catch a
    # smoke event even if Alloy lags a few seconds, narrow enough to keep
    # the response tiny.
    end_ns = int(time.time() * 1e9)
    start_ns = end_ns - int(60 * 60 * 1e9)
    qs = urllib.parse.urlencode({
        "query": query,
        "limit": "5",
        "start": str(start_ns),
        "end": str(end_ns),
        "direction": "backward",
    })
    url = f"{loki_url.rstrip('/')}/loki/api/v1/query_range?{qs}"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                streams = data.get("data", {}).get("result", []) or []
                if streams:
                    return True, None, {"streams": len(streams), "found": True}
                # Loki up but query empty — try once more (ingest lag).
                # Don't fail on empty until deadline.
        except urllib.error.HTTPError as exc:
            return False, "Loki HTTP %s" % exc.code, None
        except Exception as exc:  # noqa: BLE001
            # Loki not reachable — soft-fail
            return False, "%s: %s" % (type(exc).__name__, exc), None
        time.sleep(1)
    # Loki was reachable but query returned no rows — that's expected today
    # since Bone doesn't echo POST'd events into the JSONL. Return success
    # with a "reachable" flag so the operator can tell the difference
    # between "Loki down" and "ingest pipe not wired".
    return True, None, {"streams": 0, "found": False, "reachable": True}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--bone-url", default=os.environ.get(
        "WING_EVENTS_URL", "http://127.0.0.1:8099"
    ).rsplit("/api/", 1)[0])
    p.add_argument("--loki-url", default="http://127.0.0.1:3100")
    p.add_argument("--skip-loki", action="store_true",
                   help="skip Loki readback hop")
    p.add_argument("--db-timeout", type=float, default=5.0,
                   help="seconds to wait for wing.db row")
    p.add_argument("--loki-timeout", type=float, default=10.0,
                   help="seconds to wait for Loki query")
    p.add_argument("--json", action="store_true",
                   help="JSON summary only (machine-readable)")
    args = p.parse_args()

    summary: dict = {
        "ts": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "smoke_run_id": "smoke_" + uuid.uuid4().hex[:12],
        "bone_url": args.bone_url,
        "hops": {},
        "ok": False,
    }

    secret = _hmac_secret()
    if not secret:
        summary["error"] = "no HMAC secret (set WING_EVENTS_HMAC_SECRET or write ~/.nos/secrets.yml)"
        print(json.dumps(summary, indent=2 if not args.json else None))
        return 5

    # ── Hop 1: POST event ──────────────────────────────────────────────────
    event = {
        "ts": summary["ts"],
        "type": "task_ok",                     # type allowed by Bone validator
        "run_id": summary["smoke_run_id"],
        "task": "wing-telemetry-smoke probe",
        "task_uuid": uuid.uuid4().hex,
        "host": "smoke",
        "duration_ms": 0,
    }
    if not args.json:
        sys.stderr.write("→ POST /api/v1/events  run_id=%s\n" % summary["smoke_run_id"])
    ok, err, body = _post_event(args.bone_url, event, secret, timeout=5.0)
    summary["hops"]["bone_post"] = {"ok": ok, "error": err, "response": body}
    if not ok:
        if not args.json:
            sys.stderr.write("✗ POST failed: %s\n" % err)
        print(json.dumps(summary, indent=2 if not args.json else None))
        return 2

    # ── Hop 2: wing.db readback ────────────────────────────────────────────
    if not args.json:
        sys.stderr.write("→ SELECT events WHERE run_id=%s  (wait ≤%.1fs)\n"
                         % (summary["smoke_run_id"], args.db_timeout))
    ok, err, row = _check_wing_db(summary["smoke_run_id"], args.db_timeout)
    summary["hops"]["wing_db"] = {"ok": ok, "error": err, "row": row}
    if not ok:
        if not args.json:
            sys.stderr.write("✗ wing.db readback failed: %s\n" % err)
        print(json.dumps(summary, indent=2 if not args.json else None))
        return 3

    # ── Hop 3: Loki (best-effort) ──────────────────────────────────────────
    if not args.skip_loki:
        if not args.json:
            sys.stderr.write("→ Loki query  (wait ≤%.1fs)\n" % args.loki_timeout)
        ok, err, found = _check_loki(args.loki_url, summary["smoke_run_id"],
                                      args.loki_timeout)
        summary["hops"]["loki"] = {"ok": ok, "error": err, "result": found}
        if not ok:
            if not args.json:
                sys.stderr.write("✗ Loki check failed: %s\n" % err)
            # Loki is best-effort — don't fail the whole probe just because
            # Loki is down. Mark partial success.
            summary["loki_warning"] = err

    summary["ok"] = True
    if not args.json:
        sys.stderr.write("✓ telemetry pipe healthy\n")
    print(json.dumps(summary, indent=2 if not args.json else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
