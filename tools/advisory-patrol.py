#!/usr/bin/env python3
"""Nightly advisory patrol: run tools/advisory-status.py, keep the report, exit with the verdict.

Pulse job advisory-patrol:nightly (files/anatomy/plugins/advisory-patrol). The
report lands in ~/.nos/advisory/last.json (0600) for tools/red-status.py, with the
exit code in one word under `patrol` (verdict/why/counts) for tools/morning-verdict.py.

  exit 0   every source read, no unjudged HIGH / CRITICAL / KEV match
  exit 10  an unjudged serious match (state/genome/advisory-judgements.yml)
  exit 11  nothing serious found, but a source was unreadable: NOT clean
  (1 and 2 are a crash's and argparse's codes: a finding must not look like either; gates.md, findings 10)

GitHub allows 60 unauthenticated calls an hour and one run makes ~800, so a
missing GITHUB_TOKEN falls back to `gh auth token`; the token is never printed.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

REPO = pathlib.Path(__file__).resolve().parents[1]
EXIT_FINDINGS = 10   # an unjudged serious match
EXIT_BLIND = 11      # nothing serious found, a source unreadable: not clean
SNAPSHOT = pathlib.Path(os.environ.get("NOS_ADVISORY_SNAPSHOT") or pathlib.Path.home() / ".nos" / "advisory" / "last.json")

_spec = importlib.util.spec_from_file_location("advisory_status", REPO / "tools" / "advisory-status.py")
adv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adv)


def _github_token() -> str | None:
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def patrol_verdict(bad: list[dict], blind: list[str]) -> dict:
    """The exit code in one word, kept in the report (row morning-verdict): 10 RED, 11 UNKNOWN, 0 OK.
    Its own key: the report's `verdict` is advisory-status's AFFECTED/CLEAR, which counts judged
    matches too."""
    counts = {"unjudged_serious": len(bad), "blind_sources": len(blind)}
    if bad:
        u = bad[0]
        return {"verdict": "RED", "why": f"{len(bad)} unjudged serious: {u['subject']} {u['version']} {u['id']}",
                "counts": counts}
    if blind:
        return {"verdict": "UNKNOWN", "why": f"source(s) unreadable: {', '.join(blind)} — not clean",
                "counts": counts}
    return {"verdict": "OK", "why": "every source read, no unjudged HIGH / CRITICAL / KEV match",
            "counts": counts}


def main(argv: list[str] | None = None) -> int:
    if not (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")):
        token = _github_token()
        if token:
            os.environ["GITHUB_TOKEN"] = token
    adv.use_cache(SNAPSHOT.parent / "cache")
    rep = adv.collect(fetch=adv.fetch)
    rep["at"] = datetime.now(timezone.utc).isoformat()
    bad = adv.unjudged(rep, adv.judgements(), datetime.now(timezone.utc).date())
    blind = [n for n, s in rep["sources"].items() if s["state"] == "UNKNOWN"]
    rep["patrol"] = patrol_verdict(bad, blind)

    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = SNAPSHOT.with_suffix(".tmp")
    tmp.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, SNAPSHOT)

    for u in bad:
        print(f"UNJUDGED {u['subject']} {u['version']} {u['id']} severity {u['severity']} fixed {u['fixed'] or 'none'}")
    if blind:
        print(f"UNKNOWN source(s): {', '.join(blind)} — not clean")
    print(f"advisory patrol: {rep['verdict']}, {len(bad)} unjudged serious, {rep.get('calls', '?')} calls -> {SNAPSHOT}")
    return EXIT_FINDINGS if bad else EXIT_BLIND if blind else 0


if __name__ == "__main__":
    sys.exit(main())
