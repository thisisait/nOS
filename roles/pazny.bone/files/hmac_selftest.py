#!/usr/bin/env python3
"""Bone HMAC self-test — detect a callback↔Bone secret desync.

Signs a throwaway event with WING_EVENTS_HMAC_SECRET (the SAME value the
telemetry callback uses) and POSTs it to Bone's /api/v1/events. Bone verifies
the HMAC BEFORE it validates the payload, so:

  * 401  → the running Bone's env secret differs from ours → DESYNC.
           (This happens when a run rendered a new plist secret but FAILED
           before the end-of-play reload handler flushed — Bone keeps the stale
           env and every telemetry event 401s for every subsequent run.)
  * 400  → HMAC OK, payload intentionally invalid (missing fields) → secret in
           sync. This is the healthy result; we send a deliberately-invalid
           event so nothing bogus is ever inserted.
  * 200  → HMAC OK and inserted (shouldn't happen with our empty event).
  * other/exc → Bone unreachable; treat as inconclusive (exit 0, "SKIP").

Prints one token to stdout: OK | DESYNC | SKIP. Never raises; exit code is
always 0 so the playbook branches on stdout, not rc.
"""
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request

secret = os.environ.get("WING_EVENTS_HMAC_SECRET", "")
port = os.environ.get("BONE_PORT", "8099")
if not secret:
    print("SKIP")  # nothing to verify
    sys.exit(0)

# Deliberately-invalid event: HMAC will verify, validate_payload will 400.
body = json.dumps({"events": [{}]}, separators=(",", ":"),
                  sort_keys=True).encode("utf-8")
ts = str(int(time.time()))
sig = hmac.new(secret.encode("utf-8"), (ts + ".").encode("utf-8") + body,
               hashlib.sha256).hexdigest()
req = urllib.request.Request(
    "http://127.0.0.1:%s/api/v1/events" % port, data=body, method="POST",
    headers={"Content-Type": "application/json",
             "X-Wing-Timestamp": ts, "X-Wing-Signature": sig})
try:
    urllib.request.urlopen(req, timeout=5)
    print("OK")  # 2xx — HMAC accepted
except urllib.error.HTTPError as e:
    print("DESYNC" if e.code == 401 else "OK")
except Exception:
    print("SKIP")  # unreachable / inconclusive — don't reload on a fluke
sys.exit(0)
