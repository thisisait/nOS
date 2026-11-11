#!/usr/bin/env python3
"""The immune drill: plant known, inert samples, run the estate's own detector, record caught / missed.

Row immune-drill-known-samples (operator 2026-11-11). Defensive: it measures whether the detectors
fire. Scope, enforced here: only a temp tree this run creates (never the live estate's data, config or
repo), no network, no exploit code, no third-party target; the samples are removed on exit whatever
happens. A MISSED sample is the finding; a sample with no detector is said so, never counted as caught.

Slice 1 drills one sample end to end and names the rest honestly:
  secret-canary   a GitHub-PAT-shaped string built at RUN time (never in the repo) in a temp file,
                  scanned by gitleaks with THIS repo's .gitleaks.toml — the estate's real config and
                  allowlist, so an allowlist entry that swallowed a real-looking secret would show as missed
  eicar           not drilled: no anti-malware detector is declared in state/immune/indicators.yml
  advisory-pin    not drilled offline: the advisory match needs OSV/GitHub (network)
  exposed-port    not drilled yet: the rendered-compose check is the next slice

    tools/immune-drill.py            # run, print, write ~/.nos/immune/drill/<stamp>.json
    tools/immune-drill.py --json     # the record on stdout only
Exit 0 always (a drill reports). Refused inside an agent run (NOS_AGENT_NAME set): the operator drills.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("NOS_IMMUNE_DRILL_DIR") or Path.home() / ".nos" / "immune" / "drill")


def _canary() -> str:
    """A GitHub classic PAT shape (ghp_ + 36 alnum), assembled now so no literal ever sits in a file."""
    alnum = string.ascii_letters + string.digits
    return "gh" + "p_" + "".join(secrets.choice(alnum) for _ in range(36))


def drill_secret(tmp: Path) -> dict:
    gl = shutil.which("gitleaks")
    if not gl:
        return {"sample": "secret-canary", "result": "UNKNOWN", "why": "gitleaks not on PATH"}
    (tmp / "settings.env").write_text(f"GITHUB_TOKEN={_canary()}\n")
    report = tmp / "report.json"
    t0 = time.monotonic()
    try:
        subprocess.run([gl, "dir", str(tmp), "--config", str(REPO / ".gitleaks.toml"), "--no-banner",
                        "--redact", "--exit-code", "0", "--report-format", "json", "--report-path", str(report)],
                       capture_output=True, text=True, timeout=120, check=False)
        hits = json.loads(report.read_text() or "[]") if report.exists() else None
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {"sample": "secret-canary", "result": "UNKNOWN", "why": f"gitleaks did not answer: {type(exc).__name__}"}
    secs = round(time.monotonic() - t0, 2)
    if hits is None:
        return {"sample": "secret-canary", "result": "UNKNOWN", "why": "gitleaks wrote no report"}
    caught = [h for h in hits if str(h.get("File", "")).endswith("settings.env")]
    return {"sample": "secret-canary", "result": "caught" if caught else "missed", "detector": "gitleaks",
            "rule": caught[0].get("RuleID") if caught else None, "seconds": secs}


NOT_DRILLED = [
    {"sample": "eicar", "result": "no detector", "why": "no anti-malware indicator in state/immune/indicators.yml"},
    {"sample": "advisory-pin", "result": "not drilled", "why": "the advisory match needs the network (OSV/GitHub)"},
    {"sample": "exposed-port", "result": "not drilled", "why": "rendered-compose check is the next slice"},
]


def run() -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="nos-immune-drill-"))
    try:
        rows = [drill_secret(tmp)] + NOT_DRILLED
    finally:
        shutil.rmtree(tmp, ignore_errors=True)   # every sample goes, whatever happened
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "samples": rows,
            "missed": [r["sample"] for r in rows if r["result"] == "missed"], "cleaned": not tmp.exists()}


def main() -> int:
    if os.environ.get("NOS_AGENT_NAME"):
        print("immune-drill: refused inside an agent run — the operator drills (Tier 1)")
        return 0
    rec = run()
    if "--json" in sys.argv:
        print(json.dumps(rec, indent=2))
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / (rec["at"].replace(":", "") + ".json")
    path.write_text(json.dumps(rec, indent=2) + "\n")
    for r in rec["samples"]:
        print(f"  {r['sample']:<14} {r['result']:<12} {r.get('rule') or r.get('why') or ''}")
    print(f"immune-drill: {len(rec['missed'])} missed · samples removed: {rec['cleaned']} · {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
