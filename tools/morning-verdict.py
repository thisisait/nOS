#!/usr/bin/env python3
"""Each morning, what each reader said: one `morning-verdict` row per reader.

Row morning-verdict (spec accepted 2026-11-12). Not a second judge: a row's
verdict is the reader's own `verdict` key (OK | RED | UNKNOWN) and its `why`,
copied. A reader that gives no such key, no JSON, or no answer in 60 s is
UNKNOWN with the reason, never OK. advisory-status is not re-run (~800 calls):
its row is the 03:50 patrol's own verdict (`patrol` in the report red-status reads).

    tools/morning-verdict.py            the six verdicts, as text; writes nothing
    tools/morning-verdict.py --json     the six would-be rows; writes nothing
    tools/morning-verdict.py --write    the same, then one upsert per row (Pulse, 07:10 UTC)

--write exits like advisory-patrol: 0 all OK · 10 any RED · 11 no RED but an
UNKNOWN (nothing red is not clean) · 1 a KEAP write failed. Slug = <UTC date>-<reader>,
so a re-run the same day overwrites that day's rows.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import keap_api  # noqa: E402

TABLE = "morning-verdict"
RUN = ("red-status", "rem-status", "agent-status", "loop-status", "estate-status")
ADVISORY = "advisory-status"
TIMEOUT_S, MAX_WHY = 60, 300
VERDICTS = ("OK", "RED", "UNKNOWN")
ADVISORY_SNAPSHOT = Path(os.environ.get("NOS_ADVISORY_SNAPSHOT")
                         or Path.home() / ".nos" / "advisory" / "last.json")
ADVISORY_STALE_AFTER = timedelta(hours=36)   # red-status's own bound


def _scrub():
    spec = importlib.util.spec_from_file_location(
        "nos_pulse_redact", REPO / "files/anatomy/pulse/pulse/redact.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.scrub_text


scrub_text = _scrub()


def clean(text: str) -> str:
    """Reader text as stored: secret-shaped values redacted, control bytes gone, 300 chars."""
    return "".join(ch if ch.isprintable() else " " for ch in scrub_text(str(text)))[:MAX_WHY]


def judged(rep: object) -> tuple[str, str, dict]:
    """(verdict, why, counts) from a reader's --json; anything off is UNKNOWN, with the reason."""
    if not isinstance(rep, dict):
        return "UNKNOWN", "the reader's JSON is not an object", {}
    v = rep.get("verdict")
    if v not in VERDICTS:
        return "UNKNOWN", ("no verdict key" if v is None else
                           f"verdict {clean(v)[:40]!r} is not OK|RED|UNKNOWN"), {}
    raw = rep.get("counts")
    # Numbers only: counts are what the check counted, never free text.
    counts = {clean(k)[:64]: n for k, n in (raw.items() if isinstance(raw, dict) else ())
              if isinstance(n, (int, float)) and not isinstance(n, bool)}
    return v, clean(rep.get("why") or ""), counts


def run(name: str) -> tuple[str, str, dict]:
    try:
        p = subprocess.run([sys.executable, str(REPO / "tools" / f"{name}.py"), "--json"],
                           capture_output=True, text=True, timeout=TIMEOUT_S, cwd=REPO)
    except subprocess.TimeoutExpired:
        return "UNKNOWN", f"no answer in {TIMEOUT_S} s", {}
    except OSError as exc:
        return "UNKNOWN", clean(f"did not start: {type(exc).__name__}"), {}
    try:
        rep = json.loads(p.stdout)
    except ValueError:
        return "UNKNOWN", f"no JSON on stdout (exit {p.returncode})", {}
    return judged(rep)   # a non-zero exit (estate-status 1/2) is data; the verdict key decides


def advisory(now: datetime) -> tuple[str, str, dict]:
    try:
        rep = json.loads(ADVISORY_SNAPSHOT.read_text(encoding="utf-8"))
        at = datetime.fromisoformat(str(rep["at"]))
    except FileNotFoundError:
        return "UNKNOWN", "advisory report absent (the 03:50 patrol has not written one)", {}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return "UNKNOWN", f"advisory report unreadable: {type(exc).__name__}", {}
    if at.tzinfo is None or now - at > ADVISORY_STALE_AFTER:
        return "UNKNOWN", f"advisory report stale ({clean(rep['at'])[:40]})", {}
    if "patrol" not in rep:
        return "UNKNOWN", "advisory report holds no patrol verdict (written by an older patrol)", {}
    return judged(rep["patrol"])   # the patrol's judgement; rep["verdict"] is AFFECTED/CLEAR


def rows(now: datetime) -> list[dict]:
    day, epoch = now.strftime("%Y-%m-%d"), int(now.timestamp())
    said = {n: run(n) for n in RUN} | {ADVISORY: advisory(now)}
    return [{"slug": f"{day}-{n}", "occurred_at": epoch, "reader": n,
             "verdict": v, "why": why, "counts": counts}
            for n, (v, why, counts) in said.items()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    out = rows(datetime.now(timezone.utc).replace(microsecond=0))
    if args.json:
        print(json.dumps({"table": TABLE, "rows": out}, indent=2))
        return 0
    for r in out:
        print(f"{r['reader']:<16} {r['verdict']:<8} {r['why']}")
    if not args.write:
        return 0
    failed = 0
    for r in out:
        try:
            keap_api.write_row(TABLE, r)
        except (RuntimeError, OSError) as exc:   # URLError is an OSError
            failed += 1
            print(f"morning-verdict: {r['slug']} not written — {clean(exc)}", file=sys.stderr)
    if failed:
        return 1
    verdicts = {r["verdict"] for r in out}
    return 10 if "RED" in verdicts else 11 if "UNKNOWN" in verdicts else 0


if __name__ == "__main__":
    sys.exit(main())
