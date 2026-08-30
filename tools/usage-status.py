#!/usr/bin/env python3
"""usage-status — how much of each AI subscription this host has already spent.

    tools/usage-status.py
    tools/usage-status.py --json
    tools/usage-status.py --self-check

WHAT IT MEASURES, AND WHAT IT CANNOT. The tokens are counted from the local
transcripts each CLI writes — that is a MEASUREMENT, taken from the same
artifacts the vendor's own client wrote. The LIMIT is not on this host: no
Claude/Codex/MiniMax client persists the subscription's remaining quota
anywhere a reader can find it. So a limit is reported only when the operator
declares one in `~/.nos/usage-limits.yml`:

    claude:  {"5h": 30000000, "7d": 150000000}

and until then `pct` is blank rather than a guess. A percentage of an invented
denominator is the fabricated-freshness defect this estate has paid for twice.

ABSENT IS UNKNOWN, NEVER ZERO. A provider whose transcript directory does not
exist reports UNKNOWN with the path it looked at — the alternative reads as
"you have used nothing", which is the one wrong answer.

ADDING A PROVIDER is adding one entry to PROVIDERS below: where its transcripts
live and how to turn one JSONL line into (timestamp, tokens). Reader only —
changes nothing, exits 0 whatever it finds.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LIMITS = Path.home() / ".nos/usage-limits.yml"
WINDOWS = (("5h", 5 * 3600), ("7d", 7 * 86400))


def _ts(value) -> float | None:
    """ISO-8601 (either spelling) or epoch seconds -> epoch, else None."""
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def claude_record(d: dict):
    """One assistant turn from ~/.claude/projects/*/*.jsonl."""
    if d.get("type") != "assistant":
        return None
    u = (d.get("message") or {}).get("usage") or {}
    t = _ts(d.get("timestamp"))
    if t is None or not u:
        return None
    return t, d.get("requestId"), {
        "input": u.get("input_tokens", 0),
        "output": u.get("output_tokens", 0),
        "cache": u.get("cache_read_input_tokens", 0)
        + u.get("cache_creation_input_tokens", 0),
    }


def codex_record(d: dict):
    """Codex CLI rollout line: an event carrying a cumulative token_count."""
    payload = d.get("payload") or d
    if payload.get("type") != "token_count":
        return None
    info = (payload.get("info") or {}).get("last_token_usage") or {}
    t = _ts(d.get("timestamp") or payload.get("timestamp"))
    if t is None or not info:
        return None
    return t, None, {
        "input": info.get("input_tokens", 0),
        "output": info.get("output_tokens", 0),
        "cache": info.get("cached_input_tokens", 0),
    }


# Each entry: where the transcripts are, the glob under it, and the line
# reader. `note` is what a reader should know when the source is absent.
PROVIDERS = [
    {"id": "claude", "root": Path.home() / ".claude/projects",
     "glob": "*/*.jsonl", "record": claude_record,
     "note": "Claude Code writes one JSONL per session"},
    {"id": "codex", "root": Path.home() / ".codex/sessions",
     "glob": "**/*.jsonl", "record": codex_record,
     "note": "Codex CLI not installed on this host"},
    {"id": "minimax", "root": None, "glob": "", "record": None,
     "note": "no local transcript artifact known — add a root + record() here"},
]


def _limits() -> dict:
    if not LIMITS.is_file():
        return {}
    try:
        import yaml

        return yaml.safe_load(LIMITS.read_text()) or {}
    except Exception:
        return {}


def scan(provider: dict, now: float) -> dict:
    root, oldest = provider["root"], now - max(w for _, w in WINDOWS)
    out = {"provider": provider["id"], "source": str(root or "-"),
           "note": provider["note"]}
    if root is None or not root.is_dir():
        return {**out, "state": "UNKNOWN", "windows": [], "last_activity": None}

    seen: set[str] = set()
    hits: list[tuple[float, dict]] = []
    for path in root.glob(provider["glob"]):
        # A file untouched since before the widest window holds nothing we
        # count; skipping it is what keeps this cheap on a year of sessions.
        try:
            if path.stat().st_mtime < oldest:
                continue
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            if '"usage"' not in line and '"token_count"' not in line:
                continue
            try:
                rec = provider["record"](json.loads(line))
            except Exception:  # noqa: BLE001 — a bad line is not a bad run
                continue
            if rec is None:
                continue
            t, key, toks = rec
            if t < oldest or (key and key in seen):
                continue
            if key:
                seen.add(key)
            hits.append((t, toks))

    windows = []
    for label, span in WINDOWS:
        rows = [t for t in hits if t[0] >= now - span]
        tot = sum(sum(v.values()) for _, v in rows)
        limit = (_limits().get(provider["id"]) or {}).get(label)
        windows.append({
            "window": label, "messages": len(rows), "total": tot,
            "output": sum(v["output"] for _, v in rows),
            "input": sum(v["input"] for _, v in rows),
            "cache": sum(v["cache"] for _, v in rows),
            "limit": limit,
            "pct": round(100 * tot / limit, 1) if limit else None,
        })
    last = max((t for t, _ in hits), default=None)
    return {**out, "state": "ok", "windows": windows,
            "last_activity": datetime.fromtimestamp(last, timezone.utc).isoformat()
            if last else None}


def collect() -> dict:
    now = time.time()
    return {"generated_at": datetime.now(timezone.utc).isoformat(),
            "limits_file": str(LIMITS), "limits_declared": bool(_limits()),
            "providers": [scan(p, now) for p in PROVIDERS]}


def _self_check() -> None:
    now = time.time()
    iso = datetime.fromtimestamp(now, timezone.utc).isoformat()
    r = claude_record({"type": "assistant", "timestamp": iso, "requestId": "r1",
                       "message": {"usage": {"input_tokens": 1, "output_tokens": 2,
                                             "cache_read_input_tokens": 3,
                                             "cache_creation_input_tokens": 4}}})
    assert r and r[1] == "r1" and r[2] == {"input": 1, "output": 2, "cache": 7}, r
    assert claude_record({"type": "user"}) is None
    assert codex_record({"payload": {"type": "token_count", "timestamp": iso,
                                     "info": {"last_token_usage": {"output_tokens": 5}}}})[2]["output"] == 5
    absent = scan({"id": "x", "root": Path("/nope"), "glob": "*", "record": None,
                   "note": "n"}, now)
    assert absent["state"] == "UNKNOWN" and absent["windows"] == [], absent
    assert _ts("2026-08-30T12:23:22.661Z") and _ts("2026-08-30T12:23:22+02:00")
    print("self-check ok")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()
    if args.self_check:
        _self_check()
        return 0

    data = collect()
    if args.json:
        json.dump(data, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0
    for p in data["providers"]:
        if p["state"] != "ok":
            print(f"{p['provider']:<9} UNKNOWN  {p['note']} ({p['source']})")
            continue
        for w in p["windows"]:
            pct = f"{w['pct']}%" if w["pct"] is not None else "limit not declared"
            print(f"{p['provider']:<9} {w['window']:<3} {w['total']:>12,} tok "
                  f"({w['output']:,} out, {w['messages']} msgs)  {pct}")
    if not data["limits_declared"]:
        print(f"\nno limits declared — write {LIMITS} to get a percentage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
