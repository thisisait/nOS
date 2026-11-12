#!/usr/bin/env python3
"""The efferent queue: commands handed to the operator, one KEAP row each.

A row is TEXT for a human. This tool never runs `command`. A row closes only
when a reader from the closed table below saw the effect (`tick`), never
because someone copied it. Every write goes through the human door as the
operator (tools/keap_api.py human_headers), not an agent bearer.

    tools/efferent.py add --machine studio --app shell --why "push the row" \
        --command "tools/nos-push origin feat/x" --reader ls-remote-has \
        --arg origin --arg feat/x --arg 0123abc
    tools/efferent.py list [--json]    # a reader: exits 0, unreadable = UNKNOWN
    tools/efferent.py show <slug>      # the raw command, only if it is still clean
    tools/efferent.py tick             # run each open row's reader; close the seen ones

A row is data any table writer controls: `list` never emits a raw control byte,
and `show` refuses to print one (spec: row efferent-queue, 2026-11-12).
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import keap_api  # noqa: E402

TABLE = "efferent-queue"
MAX_COMMAND, MAX_WHY = 2000, 300
WORD = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")          # machine, app

# THE CLOSED READER TABLE. name -> (arg regexes, check). A row picks a name and
# gives args; each arg must match its regex and none may start with "-", so a
# row can never add a flag or choose an argv. The table def holds the same names.
SHA = r"^[0-9a-f]{7,40}$"
READERS: dict[str, tuple[str, ...]] = {
    "ls-remote-has": (r"^(origin|gitea)$", r"^[A-Za-z0-9._/-]{1,120}$", SHA),
    "estate-ref-is": (SHA,),
    "converge-recap-ok": (),
}


def _redact():
    spec = importlib.util.spec_from_file_location(
        "nos_pulse_redact", REPO / "files/anatomy/pulse/pulse/redact.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.scrub_text


scrub_text = _redact()


# ── pure checks (the trust boundary) ─────────────────────────────────────────
def unprintable(s: str) -> tuple[int, str] | None:
    """(1-based col, char) of the first char that is not printable text, else None.
    Catches C0/C1, DEL, ESC, CR, LF, tab, U+2028 and the bidi/zero-width Cf set."""
    for i, c in enumerate(s):
        if not c.isprintable():
            return i + 1, c
    return None


def shown(v) -> str:
    """A value safe to put on a terminal: every unprintable char as \\xNN/\\uNNNN text."""
    s = "" if v is None else str(v)
    return "".join(c if c.isprintable() else c.encode("unicode_escape").decode("ascii") for c in s)


def text_refusal(field: str, value: str, limit: int) -> str | None:
    """Why `value` may not be stored as `field`, or None. Never echoes the value."""
    if not value:
        return f"{field} is empty"
    if len(value) > limit:
        return f"{field} is {len(value)} chars (limit {limit})"
    bad = unprintable(value)
    if bad:
        return f"{field} holds U+{ord(bad[1]):04X} at col {bad[0]} (not printable)"
    if scrub_text(value) != value:
        return (f"{field} holds a secret-shaped value (scrub_text changed it) — pass the "
                f'secret by reference (e.g. "from credentials.yml") not by value')
    return None


def seen_why(why: str) -> str:
    """A reader's reason as stored text: scrubbed, every unprintable char escaped, <= MAX_WHY.
    The reason can quote row data (a remote's ref, a timestamp), so it is data, never markup."""
    return shown(scrub_text(str(why)))[:MAX_WHY]


def args_refusal(reader: str, args: list[str]) -> str | None:
    """Why this reader + args may not run, or None."""
    if reader not in READERS:
        return f"reader {shown(reader)!r} is not in the allow-list ({', '.join(READERS)})"
    want = READERS[reader]
    if len(args) != len(want):
        return f"reader {reader} takes {len(want)} args, the row gives {len(args)}"
    for i, (a, rx) in enumerate(zip(args, want)):
        if a.startswith("-") or not re.fullmatch(rx, a) or ".." in a:
            return f"reader {reader} arg {i + 1} does not match {rx}"
    return None


def row_problem(v: dict) -> str | None:
    """A stored row re-checked (a writer may have bypassed `add`): None when clean."""
    for f, lim in (("command", MAX_COMMAND), ("why", MAX_WHY)):
        why = text_refusal(f, str(v.get(f) or ""), lim)
        if why:
            return why
    return args_refusal(str(v.get("reader") or ""), str(v.get("reader_args") or "").split())


# ── readers: ("done" | "open" | "unknown", why). They only read. ─────────────
def _git(argv: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=20, cwd=REPO)
    except (OSError, subprocess.SubprocessError) as e:
        return -1, type(e).__name__
    return p.returncode, p.stdout


def read_ls_remote_has(row: dict, remote: str, ref: str, sha: str):
    rc, out = _git(["git", "ls-remote", remote, f"refs/heads/{ref}"])
    if rc != 0:
        return "unknown", f"git ls-remote {remote} exited {rc}"
    hit = [ln.split()[0] for ln in out.splitlines()
           if ln.split()[1:] == [f"refs/heads/{ref}"]]
    if not hit:
        return "unknown", f"{remote} has no refs/heads/{ref}"
    if hit[0].startswith(sha):
        return "done", f"{remote} {ref} is at {hit[0][:12]}"
    return "open", f"{remote} {ref} is at {hit[0][:12]}, not {sha}"


def read_estate_ref_is(row: dict, sha: str):
    import nos_identity
    clone = nos_identity.estate_dir()
    if not (clone / ".git").exists():
        return "unknown", f"no estate clone at {clone}"
    rc, out = _git(["git", "-C", str(clone), "rev-parse", "HEAD"])
    if rc != 0:
        return "unknown", f"git rev-parse in the estate clone exited {rc}"
    head = out.strip()
    return ("done" if head.startswith(sha) else "open"), f"estate HEAD is {head[:12]}"


def read_converge_recap_ok(row: dict):
    """last_run is written in post_tasks (tasks/state-report.yml), which a failed host
    never reaches; its `at` is the run's fact time, i.e. when it STARTED."""
    import nos_identity
    r = nos_identity.ran()
    if r.source != "state.yml":
        return "unknown", f"state.yml: {r.provenance()}"
    at = str((r.state.get("last_run") or {}).get("at") or "")
    try:
        ran_at = dt.datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return "unknown", f"last_run.at {shown(at)!r} is not a timestamp"
    handed = _epoch(row.get("occurred_at"))
    if handed is None:
        return "unknown", "occurred_at is not a timestamp"
    if ran_at > handed:
        return "done", f"a converge started {at} and wrote its recap"
    return "open", f"last recap {at} predates the row"


CHECKS = {"ls-remote-has": read_ls_remote_has, "estate-ref-is": read_estate_ref_is,
          "converge-recap-ok": read_converge_recap_ok}


def judge(row: dict):
    """Run the row's reader, never anything the row names beyond the allow-list."""
    why = row_problem(row)
    if why:
        return "unknown", why
    return CHECKS[row["reader"]](row, *str(row.get("reader_args") or "").split())


# ── the human door (as the operator) ─────────────────────────────────────────
def _req(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{keap_api.human_base()}{path}", data=data,
                               headers=keap_api.human_headers(), method=method)
    with urllib.request.urlopen(r, timeout=30) as x:
        return json.loads(x.read() or b"{}")


def rows() -> list[dict]:
    """[{slug, ...values}] — raises on an unreadable table (the caller says UNKNOWN)."""
    got = keap_api.paged(lambda p: _req("GET", p), f"/api/tables/{TABLE}/rows")
    return [{**(r.get("values") or {}), "slug": r.get("id")} for r in got["data"]["rows"]]


def write(slug: str, values: dict) -> None:
    _req("POST", f"/api/tables/{TABLE}/rows", {"id": slug, "values": values})


def _new_slug() -> str:
    # Random, not a read-then-write counter: the write is an upsert, so two adds that picked one
    # slug silently replaced the first row's command (review 2026-11-12). 32 bits per add.
    return f"e-{secrets.token_hex(4)}"


def _epoch(v) -> float | None:
    """occurred_at as written by add (ISO-8601 UTC) or an older epoch int; None if neither."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ── verbs ────────────────────────────────────────────────────────────────────
def cmd_add(a) -> int:
    args = list(a.arg or [])
    why = (None if WORD.fullmatch(a.machine) else "machine must match " + WORD.pattern) \
        or (None if WORD.fullmatch(a.app) else "app must match " + WORD.pattern) \
        or text_refusal("why", a.why, MAX_WHY) or text_refusal("command", a.command, MAX_COMMAND) \
        or args_refusal(a.reader, args) \
        or next(filter(None, (text_refusal("arg", x, 120) for x in args)), None)
    if why:
        print(f"refused: {why}; nothing was written", file=sys.stderr)
        return 2
    slug = _new_slug()
    write(slug, {"slug": slug, "occurred_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "machine": a.machine, "app": a.app,
                 "why": a.why, "command": a.command, "reader": a.reader,
                 "reader_args": " ".join(args), "status": "open"})
    print(f"{slug}  copy: tools/efferent.py show {slug}")
    return 0


def listing() -> dict:
    """The reader's answer: every field shown-escaped, never a raw byte."""
    try:
        got = rows()
    except (OSError, urllib.error.URLError, ValueError, KeyError) as e:
        return {"ok": False, "unknown": f"{TABLE} unreadable: {type(e).__name__}", "rows": []}
    out = []
    for r in sorted(got, key=lambda r: _epoch(r.get("occurred_at")) or 0.0):
        problem = row_problem(r)
        # scrub too: a row written past `add` may hold a secret; list never shows it
        out.append({k: shown(scrub_text(str(r.get(k) or ""))) for k in
                    ("slug", "status", "machine", "app", "why", "command", "reader", "reader_args",
                     "seen_why")}
                   | {"occurred_at": r.get("occurred_at"), "seen_at": r.get("seen_at"),
                      "clean": problem is None, "problem": shown(problem or "")})
    return {"ok": True, "unknown": None, "rows": out}


def cmd_list(a) -> int:
    data = listing()
    if a.json:
        print(json.dumps(data))
    elif not data["ok"]:
        print(f"UNKNOWN — {data['unknown']}")
    else:
        for r in data["rows"]:
            flag = "" if r["clean"] else f"   !! {r['problem']}"
            print(f"{r['slug']:6} {r['status']:10} {r['machine']:8} {r['why']}{flag}")
    return 0


def cmd_show(a) -> int:
    try:
        row = next((r for r in rows() if r.get("slug") == a.slug), None)
    except (OSError, urllib.error.URLError, ValueError, KeyError) as e:
        print(f"UNKNOWN — {TABLE} unreadable: {type(e).__name__}", file=sys.stderr)
        return 1
    if row is None:
        print(f"no row {shown(a.slug)}", file=sys.stderr)
        return 1
    cmd = str(row.get("command") or "")
    problem = text_refusal("command", cmd, MAX_COMMAND)
    if problem:
        # The value is shown escaped only when it is not secret-shaped.
        safe = "" if "secret" in problem else f"\n  {shown(cmd)}"
        print(f"not printed raw: row {a.slug}: {problem}; it was not written by efferent.py{safe}",
              file=sys.stderr)
        return 2
    sys.stdout.write(cmd + "\n")
    return 0


def cmd_tick(a) -> int:
    try:
        got = rows()
    except (OSError, urllib.error.URLError, ValueError, KeyError) as e:
        print(f"UNKNOWN — {TABLE} unreadable: {type(e).__name__}", file=sys.stderr)
        return 1
    for r in got:
        if r.get("status") not in ("open", "copied", "unknown"):
            continue
        verdict, why = judge(r)
        # The only fields tick writes; `command` is never touched.
        if verdict == "done":
            write(r["slug"], {"status": "done-seen", "seen_at": dt.date.today().isoformat(), "seen_why": ""})
        elif verdict == "unknown":
            write(r["slug"], {"status": "unknown", "seen_why": seen_why(why)})
        elif r.get("status") == "unknown":   # judgeable again: back on the open list
            write(r["slug"], {"status": "open", "seen_why": ""})
        print(f"{shown(r['slug']):6} {verdict:8} {shown(why)}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="verb")
    ad = sub.add_parser("add")
    for f in ("machine", "app", "why", "command", "reader"):
        ad.add_argument(f"--{f}", required=True)
    ad.add_argument("--arg", action="append")
    sub.add_parser("list").add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    sh = sub.add_parser("show")
    sh.add_argument("slug")
    sub.add_parser("tick")
    a = p.parse_args(argv)
    return {"add": cmd_add, "show": cmd_show, "tick": cmd_tick}.get(a.verb, cmd_list)(a)


if __name__ == "__main__":
    sys.exit(main())
