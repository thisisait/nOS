#!/usr/bin/env python3
"""cortex-fs-sync — the thing that actually runs the organ's mirror pass.

Pulse job (cortex-base), scheduled BETWEEN the consolidator (04:15) and
keap-embed-sync (04:45), so a file that arrived during the day is mirrored
before the vectors are built and long before the agreement harness reads
either corpus at 05:30.

── Why this exists at all ───────────────────────────────────────────────
`cortex_fs_sync_interval_s` is 0 by design: the pass should be a DECISION,
not a coincidence of when the daemon last restarted, and §5.3's "halt the
organ's fs-sync" needs something haltable. The design said that and then
shipped nothing that decides — `startFsSync()` installs no interval, no
job POSTed `/agent/v1/fs/sync`, and the role restarts the daemon only when
the plist template changes. So the organ's ONLY pass was its boot pass:
the mirror was frozen at the last converge that changed the build, while
KEAP re-walked every 300 s and was kicked on every converge.

That is not merely stale. Every file created since the organ last booted
is `only_in_keap`, the organ's last pass reads CLEAN (it was clean — just
old), and the harness's fs-ids clause fails every single night, so the
3-night agreement clock can never reach NIGHTS_REQUIRED. The harness's
staleness guard now tells the truth about WHY; this job is what makes the
truth stop being "the organ was never asked to look".

── What it does, and what it refuses to do ──────────────────────────────
One POST to /agent/v1/fs/sync (rw tier — a pass WRITES the corpus), then
it reports the pass counters. It is a TRIGGER, not a second implementation
of the pass: every guard, the mount sentinel and the five prune refusals
live in the daemon, where the walk is.

409 (a pass already in flight) is SUCCESS, not a failure: the pass this
job wanted is running. 500 means the daemon REFUSED the pass — the mount
sentinel, most likely — and that is a real, notifiable fault, because a
refused pass is exactly the state that must never look like a quiet night.

── The halt, which until 2026-08-06 was three sentences and no code ─────
The docstring above says this job "needs something haltable", the harness
announced "The cortex organ's fs-sync is stopped", and `weaknesses.py`
raised a CRITICAL saying the same — while the only mechanism, an optional
`--halt-cmd`, was never set by the production job. Three claims, one
effect, zero occurrences: the halt had never once been able to fire.

It is real now, and it reads the flag the harness ALREADY writes rather
than inventing a second one: `halted` in the night ledger
(`cortex-corpus-diff.py:1652`). One fact, one place, and the harness's
`--no-ledger` mode still cannot halt anything, which is what keeps it
usable as a judge.

Nothing clears the flag by itself — that is the point of a removal-shaped
halt. `cortex-corpus-diff.py --clear-halt` is the one blessed way out, and
both notifications name it.

Env:
  CORTEX_API_URL          default http://127.0.0.1:8098
  CORTEX_AGENT_TOKEN_RW   required (a pass writes)
  CORTEX_DIFF_STATE       the night ledger read for `halted`
  NOS_NOTIFY_BIN          nos-notify.sh (optional)

Exit: 0 the pass ran (or one was already in flight), 1 config error,
2 the organ was unreachable, 3 the organ REFUSED the pass,
4 HALTED — the harness stopped this job and it refused to walk.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("CORTEX_API_URL", "http://127.0.0.1:8098").rstrip("/")
TOKEN = os.environ.get("CORTEX_AGENT_TOKEN_RW", "").strip()
NOTIFY_BIN = os.environ.get("NOS_NOTIFY_BIN", "")
TIMEOUT_S = int(os.environ.get("CORTEX_FS_SYNC_TIMEOUT_S", "600"))

#: The harness's night ledger. This default is a COPY of the one in
#: `cortex-corpus-diff.py` (its `--state` argument), and two copies of a path
#: is how a halt quietly stops being read: the writer would flag one file and
#: the reader would check another, and both would look fine. The copies are
#: compared to each other by `test_the_halt_can_actually_halt.py`, so this line
#: cannot drift away from the writer's in silence.
LEDGER = Path(os.environ.get("CORTEX_DIFF_STATE", str(Path.home() / ".nos" / "cortex-corpus-diff.json")))


def notify(severity: str, title: str, body: str) -> None:
    if NOTIFY_BIN and os.path.exists(NOTIFY_BIN):
        subprocess.run([NOTIFY_BIN, severity, title, body, "wing-inbox"], check=False, timeout=30)


def halted() -> bool:
    """True when the harness recorded a removal-shaped halt.

    A ledger that is missing, empty or unparseable is NOT a halt. That is
    deliberate and it is the safe direction here: the flag's absence is the
    estate's normal state (it has never once been set), so treating an
    unreadable file as "stopped" would take the mirror pass down on the first
    disk hiccup. The opposite risk — a halt missed because the file broke — is
    covered by the harness re-raising it every night it re-runs.
    """
    try:
        return bool((json.loads(LEDGER.read_text(encoding="utf-8")) or {}).get("halted"))
    except (OSError, ValueError):
        return False


def main() -> int:
    if not TOKEN:
        print("cortex-fs-sync: CORTEX_AGENT_TOKEN_RW not set", file=sys.stderr)
        return 1

    if halted():
        print(f"cortex-fs-sync: HALTED by {LEDGER} — refusing the pass", file=sys.stderr)
        notify("high", "cortex-fs-sync: refusing the pass — the harness HALTED it",
               "A removal-shaped disagreement stopped the organ's mirror pass, and it stays stopped until a human "
               "looks: removals are the only irreversible direction. Read the night in the ledger, then clear it "
               "with `cortex-corpus-diff.py --clear-halt`. The diff keeps running meanwhile — refusing to walk is "
               "safe, refusing to observe is not.")
        return 4

    req = urllib.request.Request(f"{BASE}/agent/v1/fs/sync", data=b"{}", method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("authorization", f"Bearer {TOKEN}")
    req.add_header("x-keap-agent", "cortex-fs-sync")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:
            data = (json.loads(res.read().decode()) or {}).get("data") or {}
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            # Another trigger (a converge kick) is mid-pass. The pass this job
            # exists to cause is happening; saying otherwise would train the
            # operator to ignore this job's failures.
            print("cortex-fs-sync: a pass is already in flight — nothing to do")
            return 0
        body = ""
        try:
            body = exc.read().decode()[:300]
        except OSError:
            pass
        print(f"cortex-fs-sync: the organ REFUSED the pass (HTTP {exc.code}): {body}", file=sys.stderr)
        notify("high", "Cortex fs-sync: the organ refused its pass",
               f"POST /agent/v1/fs/sync answered {exc.code}. Nothing was walked and nothing was pruned — "
               f"most likely the mount sentinel (a removable volume). {body}")
        return 3
    except (urllib.error.URLError, OSError) as exc:
        print(f"cortex-fs-sync: the organ is unreachable: {exc}", file=sys.stderr)
        return 2

    # Report the counters the nightly diff reads, so a pass that ran and a pass
    # that ran BADLY are different lines in the Pulse log rather than one.
    print(
        "cortex-fs-sync: scanned {scanned} · upserted {upserted} · unchanged {unchanged} · removed {removed} · "
        "sentinel {sentinel}".format(
            scanned=data.get("scanned", "?"), upserted=data.get("upserted", "?"),
            unchanged=data.get("unchanged", "?"), removed=data.get("removed", "?"),
            sentinel=data.get("sentinel", "n/a"),
        )
    )
    degraded = []
    if data.get("pruneRefused"):
        degraded.append("the prune was refused (found-set not trusted)")
    if data.get("rootsMissing"):
        degraded.append(f"configured roots absent: {data['rootsMissing']}")
    if data.get("emptyBodies"):
        degraded.append(f"{data['emptyBodies']} text file(s) read back EMPTY")
    if data.get("rootCollisions"):
        degraded.append(f"{data['rootCollisions']} id collision(s) between roots")
    if degraded:
        print("cortex-fs-sync: " + "; ".join(degraded), file=sys.stderr)
        notify("medium", "Cortex fs-sync: the pass ran degraded",
               "; ".join(degraded) + ". The nightly corpus diff will read this as a degraded pass and will "
               "NOT attribute a missing id to the organ's reader.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
