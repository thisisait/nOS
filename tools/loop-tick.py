#!/usr/bin/env python3
"""Write one `loop-ticks` row for a loop / watch / top tick, validated against the table def.

Row loop-ticks-table, slice 2. Every field is checked against
state/keap-tables/loop-ticks.table.yml (select options and kinds read from the def),
`reason` is scrubbed (pulse redact.scrub_text) and cut to 300 printable chars, the
slug is `<role>-<YYYYMMDDTHHMMSSZ>` from now (UTC). Append-once: a slug that already
exists is refused. A role writes only its own rows (`--writer`, default the role).

    tools/loop-tick.py --role loop --phase idle --outcome idle --reason "nothing unblocked"
    tools/loop-tick.py ... --dry-run      print the row, write nothing

Without KEAP_AGENT_TOKEN_RW in the environment it is a dry run and says so.
Exit 0 written (or dry run) · 2 refused · 1 write failed / KEAP unreachable.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import keap_api  # noqa: E402

TABLE = "loop-ticks"
DEF = REPO / "state" / "keap-tables" / f"{TABLE}.table.yml"
MAX_REASON, MAX_JSON = 300, 4000
ROW = re.compile(r"-|[a-z0-9][a-z0-9-]{0,99}")
REF = re.compile(r"-|[A-Za-z0-9._/-]{1,120}@[0-9a-f]{7,40}")


class Refused(Exception):
    pass


def _scrub():
    spec = importlib.util.spec_from_file_location(
        "nos_pulse_redact", REPO / "files/anatomy/pulse/pulse/redact.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.scrub_text


scrub_text = _scrub()


def clean(text: object, limit: int = MAX_REASON) -> str:
    return "".join(ch if ch.isprintable() else " " for ch in scrub_text(str(text)))[:limit]


def _scrubbed(v):
    """Every string leaf of a json value scrubbed; keys and numbers kept."""
    if isinstance(v, str):
        return clean(v)
    if isinstance(v, list):
        return [_scrubbed(x) for x in v]
    if isinstance(v, dict):
        return {clean(k, 64): _scrubbed(x) for k, x in v.items()}
    return v


def columns() -> dict[str, dict]:
    return {c["key"]: c for c in yaml.safe_load(DEF.read_text(encoding="utf-8"))["schema"]["columns"]}


def check(row: dict, cols: dict[str, dict]) -> None:
    """Refuse a row the def would not hold: unknown key, missing required, wrong kind, bad option."""
    if extra := sorted(set(row) - set(cols)):
        raise Refused(f"not a column of {TABLE}: {extra}")
    for key, c in cols.items():
        v = row.get(key)
        if v is None:
            if c.get("required"):
                raise Refused(f"{key} is required")
            continue
        kind = c["kind"]
        ok = {"text": isinstance(v, str),
              "select": v in (c.get("options") or ()),
              "number": isinstance(v, (int, float)) and not isinstance(v, bool),
              "json": isinstance(v, (dict, list)),
              "date": isinstance(v, str) and _is_date(v)}.get(kind)
        if ok is None:
            raise Refused(f"{key}: kind {kind} has no check here")
        if not ok:
            want = f"one of {c['options']}" if kind == "select" else f"a {kind}"
            raise Refused(f"{key}={clean(v, 60)!r} is not {want}")


def _is_date(v: str) -> bool:
    try:
        return date.fromisoformat(v).isoformat() == v
    except ValueError:
        return False


def _json_arg(name: str, raw: str | None, shape: type):
    if raw is None:
        return None
    try:
        v = json.loads(raw)
    except ValueError:
        raise Refused(f"{name} is not JSON") from None
    if not isinstance(v, shape) or len(raw) > MAX_JSON:
        raise Refused(f"{name} must be a JSON {shape.__name__} of at most {MAX_JSON} chars")
    return _scrubbed(v)


def build(a, now: datetime) -> dict:
    writer = a.writer or a.role
    if writer != a.role:
        raise Refused(f"writer {clean(writer, 40)!r} may not write a {a.role!r} row (a role writes only its own)")
    if not ROW.fullmatch(a.row):
        raise Refused(f"row must be a dtt slug or '-' ({ROW.pattern})")
    if not REF.fullmatch(a.ref):
        raise Refused(f"ref must be branch@sha7 or '-' ({REF.pattern})")
    if a.next_wake is not None and not 0 <= a.next_wake <= 86400:
        raise Refused("next-wake must be 0..86400 seconds")
    lanes = _json_arg("lanes-json", a.lanes_json, list)
    if lanes is not None and not all(isinstance(x, dict) and isinstance(x.get("lane"), str)
                                     and isinstance(x.get("rc"), int) and not isinstance(x.get("rc"), bool)
                                     for x in lanes):
        raise Refused('lanes-json must be [{"lane": str, "rc": int}, ...]')
    row = {"slug": f"{a.role}-{now.strftime('%Y%m%dT%H%M%SZ')}",
           "occurred_at": now.strftime("%Y-%m-%d"),
           "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "role": a.role, "phase": a.phase, "row": a.row, "ref": a.ref, "outcome": a.outcome,
           "next_wake_s": a.next_wake, "reason": clean(a.reason),
           "inputs": _json_arg("inputs-json", a.inputs_json, dict), "lanes": lanes, "writer": writer}
    row = {k: v for k, v in row.items() if v is not None}
    check(row, columns())
    return row


def exists(slug: str) -> bool:
    """True when the slug is already a row (404 = free); anything else raises."""
    url = (f"{keap_api.agent_base()}/agent/v1/tables/{urllib.parse.quote(TABLE, safe='')}"
           f"/rows/{urllib.parse.quote(slug, safe='')}")
    req = urllib.request.Request(url, headers={"authorization": f"Bearer {keap_api.agent_token_rw()}"})
    try:
        with urllib.request.urlopen(req, timeout=15):
            return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise RuntimeError(f"HTTP {exc.code} reading {slug}") from None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--role", required=True)
    ap.add_argument("--phase", required=True)
    ap.add_argument("--outcome", required=True)
    ap.add_argument("--row", default="-")
    ap.add_argument("--ref", default="-")
    ap.add_argument("--next-wake", type=int)
    ap.add_argument("--reason", default="")
    ap.add_argument("--inputs-json")
    ap.add_argument("--lanes-json")
    ap.add_argument("--writer", help="who writes (the token subject); must equal --role")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        row = build(a, datetime.now(timezone.utc).replace(microsecond=0))
    except Refused as exc:
        print(f"loop-tick: refused: {exc}; nothing was written", file=sys.stderr)
        return 2
    dry = a.dry_run or not os.environ.get("KEAP_AGENT_TOKEN_RW", "").strip()
    if dry:
        print(json.dumps({"table": TABLE, "row": row}, indent=2))
        if not a.dry_run:
            print("loop-tick: KEAP_AGENT_TOKEN_RW is unset — dry run, nothing was written", file=sys.stderr)
        return 0
    try:
        # ponytail: read-then-write, not atomic; one writer per role and a per-second slug make a race moot.
        if exists(row["slug"]):
            print(f"loop-tick: refused: {row['slug']} exists (append-once); nothing was written", file=sys.stderr)
            return 2
        keap_api.write_row(TABLE, row)
    except (RuntimeError, OSError) as exc:   # URLError is an OSError
        print(f"loop-tick: {row['slug']} not written — {clean(exc)}", file=sys.stderr)
        return 1
    print(f"loop-tick: {row['slug']} written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
