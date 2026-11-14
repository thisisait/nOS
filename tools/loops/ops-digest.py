#!/usr/bin/env python3
"""ops-digest runner — one operator report per run from five readers (files/anatomy/loops/ops-digest.loop.yml).

Asks red-status, rem-status, loop-status --awaiting, estate-status --no-fetch and agent-status for --json,
copies each one's `verdict`, `why` and `counts` under the reader's own field names (and names a list by
its length: len(reds), len(unlanded)), writes ~/.nos/loops/ops-digest/<UTC stamp>.json and .md, and posts
ONE A9 note when the set of red indicators differs from the last comparable digest. A reader that is
missing, times out or prints no JSON is UNKNOWN in the digest and holds the note back, as does a
red-status that could not read one of its sources. No model, no table write. Exit 0 always: this reports,
and a reader's own exit code is carried in the digest, never escalated.

    tools/loops/ops-digest.py            # run once
    tools/loops/ops-digest.py --dry      # the Markdown to stdout; no file, no note
    tools/loops/ops-digest.py --trend    # the kept digests as a series
    tools/loops/ops-digest.py --selftest # offline, no estate

Env: BONE_API_URL, WING_EVENTS_HMAC_SECRET (the note), OPS_DIGEST_DIR (default ~/.nos/loops/ops-digest),
OPS_DIGEST_KEEP_DAYS (default 30: older digests are pruned after each run, the newest never).
"""

from __future__ import annotations

import calendar
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DIR = Path(os.environ.get("OPS_DIGEST_DIR") or Path.home() / ".nos" / "loops" / "ops-digest")
KEEP_DAYS = int(os.environ.get("OPS_DIGEST_KEEP_DAYS") or 30)
STAMP = "%Y-%m-%dT%H%M%SZ"
TIMEOUT_S = 60

#: The manifest's step id → the reader's argv under tools/, and the list fields the digest names by length.
#: estate-status runs --no-fetch: a fetch writes into the checkout, and this loop writes its digest only.
READERS = (
    ("red-status", ("red-status.py", "--json"), ("reds", "sources_missing")),
    ("rem-status", ("rem-status.py", "--json"), ()),
    ("loop-status", ("loop-status.py", "--awaiting", "--json"), ("rows", "unlanded")),
    ("estate-status", ("estate-status.py", "--no-fetch", "--json"), ()),
    ("agent-status", ("agent-status.py", "--json"), ()),
)


def ask(argv: tuple[str, ...], tools: Path = REPO / "tools", timeout: int = TIMEOUT_S) -> dict:
    """One reader's reply: {"state": "OK", "exit_code", "doc"} or {"state": "UNKNOWN", "error"}."""
    try:
        r = subprocess.run([sys.executable, str(tools / argv[0]), *argv[1:]], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"state": "UNKNOWN", "error": f"no answer in {timeout} s"}
    except OSError as exc:
        return {"state": "UNKNOWN", "error": type(exc).__name__}
    try:
        doc = json.loads(r.stdout)
    except ValueError:
        doc = None
    if not isinstance(doc, dict):
        return {"state": "UNKNOWN", "exit_code": r.returncode, "error": "no JSON object on stdout"}
    return {"state": "OK", "exit_code": r.returncode, "doc": doc}


def red_keys(lines: list) -> list[str]:
    """One stable key per red line: its subject, numbers masked.
    ponytail: red-status has no id per red, and its lines carry ages ("(3 h)") that move every run. The subject
    before the first " (" with digits masked is the heuristic; a count that changes inside one subject is not a
    new red. Upgrade: red-status emits an id per red."""
    return sorted({re.sub(r"\d+", "#", str(line).split(" (")[0]).strip() for line in lines})


def digest(now: str, replies: dict, prev: dict | None) -> dict:
    readers, unknown = {}, []
    for rid, argv, lists in READERS:
        rep = replies.get(rid) or {"state": "UNKNOWN", "error": "not asked"}
        entry = {"reader": "tools/" + " ".join(argv), "state": rep["state"],
                 **{k: rep[k] for k in ("exit_code", "error") if k in rep}}
        doc = rep.get("doc")
        if isinstance(doc, dict):
            entry.update({k: doc[k] for k in ("verdict", "why", "error") if k in doc})
            if isinstance(doc.get("counts"), dict):
                entry["counts"] = doc["counts"]
            entry["len"] = {f: len(doc[f]) for f in lists if isinstance(doc.get(f), list)}
        else:
            unknown.append(rid)
        readers[rid] = entry
    d = {"at": now, "previous_at": (prev or {}).get("at"), "readers": readers, "unknown": unknown, "changed": False}
    red = (replies.get("red-status") or {}).get("doc") or {}
    if isinstance(red.get("reds"), list):
        missing = red.get("sources_missing") if isinstance(red.get("sources_missing"), list) else []
        # red-status lists its unreadable sources last in `reds`; they are UNKNOWN, not red (its own verdict()).
        d["reds"] = red["reds"][:len(red["reds"]) - len(missing)] if missing else red["reds"]
        d["unreadable_sources"] = missing
        d["red_keys"] = red_keys(d["reds"])
    before = (prev or {}).get("red_keys")
    if unknown:
        d["no_comparison"] = f"UNKNOWN reader(s): {', '.join(unknown)}"
    elif d.get("unreadable_sources"):
        d["no_comparison"] = f"red-status could not read {len(d['unreadable_sources'])} source(s)"
    elif not isinstance(before, list):
        d["no_comparison"] = "no earlier comparable digest"
    else:
        d["started"] = sorted(set(d["red_keys"]) - set(before))
        d["stopped"] = sorted(set(before) - set(d["red_keys"]))
        d["changed"] = bool(d["started"] or d["stopped"])
    return d


def markdown(d: dict) -> str:
    """The digest for a person. Every number sits on a line that names the reader's field it was copied from."""
    out = [f"# ops-digest {d['at']}", "", f"previous comparable digest: {d['previous_at'] or 'none'}"]
    if "no_comparison" in d:
        out.append(f"red set: not compared ({d['no_comparison']}); no note")
    else:
        out.append(f"red set: +{len(d['started'])} / -{len(d['stopped'])} since the previous digest"
                   + ("" if d["changed"] else " (unchanged; no note)"))
        out += [f"- started: {k}" for k in d["started"]] + [f"- stopped: {k}" for k in d["stopped"]]
    for rid, e in d["readers"].items():
        out += ["", f"## {rid}", f"reader: {e['reader']}" + (f" (exit {e['exit_code']})" if "exit_code" in e else "")]
        if e["state"] == "UNKNOWN":
            out.append(f"UNKNOWN: {e.get('error', 'no answer')}")
            continue
        out.append(f"verdict: {e.get('verdict', '(the reader gives none)')}" + (f" — {e['why']}" if e.get("why") else ""))
        if e.get("error"):
            out.append(f"error: {e['error']}")
        out += [f"counts.{k}: {v}" for k, v in (e.get("counts") or {}).items()]
        out += [f"len({k}): {v}" for k, v in (e.get("len") or {}).items()]
        if rid == "red-status" and d.get("reds"):
            out += ["reds:"] + [f"- {line}" for line in d["reds"]]
    return "\n".join(out) + "\n"


def note(d: dict) -> bool:
    """One A9 note through grafana-check's signed post. It carries the masked subjects, never a raw red line."""
    spec = importlib.util.spec_from_file_location("grafana_check", Path(__file__).with_name("grafana-check.py"))
    gc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gc)
    verdicts = ", ".join(f"{rid} {e.get('verdict', '?')}" for rid, e in d["readers"].items())
    body = "\n".join([f"started: {'; '.join(d['started']) or '-'}", f"stopped: {'; '.join(d['stopped']) or '-'}",
                      f"readers: {verdicts}", f"digest: {DIR / (d['at'] + '.md')}"])
    return gc.post({"severity": "medium" if d["started"] else "info",
                    "title": f"Estate: {len(d['red_keys'])} red — +{len(d['started'])} / -{len(d['stopped'])} since the last digest",
                    "body": body, "origin_plugin": "loop:ops-digest", "actor_id": "pulse:loop:ops-digest",
                    "supersede_key": "ops-digest", "metadata": {"started": d["started"], "stopped": d["stopped"]}})


def _stamped(d: Path) -> list[tuple[float, Path]]:
    """(epoch, file) of each digest named by its UTC stamp, oldest first; another name is not ours."""
    out = []
    for f in d.glob("*.json") if d.is_dir() else []:
        try:
            out.append((calendar.timegm(time.strptime(f.stem, STAMP)), f))
        except ValueError:
            continue
    return sorted(out)


def _read(f: Path) -> dict | None:
    try:
        doc = json.loads(f.read_text())
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def previous(d: Path) -> dict | None:
    """The newest digest that holds a red set to compare with: an UNKNOWN run in between is stepped over."""
    for _, f in reversed(_stamped(d)):
        doc = _read(f)
        if doc and isinstance(doc.get("red_keys"), list) and not doc.get("unknown") and not doc.get("unreadable_sources"):
            return doc
    return None


def prune(d: Path, now: float, keep_days: int = KEEP_DAYS) -> int:
    """Deletes stamped digests (.json and its .md) older than keep_days; the newest stays whatever its age."""
    old = [f for t, f in _stamped(d)[:-1] if now - t > keep_days * 86400]
    for f in old:
        f.unlink(missing_ok=True)
        f.with_suffix(".md").unlink(missing_ok=True)
    return len(old)


def print_trend(d: Path) -> None:
    rows = [doc for _, f in _stamped(d) if (doc := _read(f))]
    if not rows:
        print(f"ops-digest: no digests in {d}")
    for g in rows:
        keys = g.get("red_keys")
        red = "?" if not isinstance(keys, list) else len(keys)
        unknown = f"  UNKNOWN {', '.join(g['unknown'])}" if g.get("unknown") else ""
        new = f"  +{'; '.join(g['started'])}" if g.get("started") else ""
        print(f"{g.get('at')}  red {red:>3}{unknown}{new}")


def selftest() -> int:
    import tempfile
    ok = lambda doc, code=0: {"state": "OK", "exit_code": code, "doc": doc}  # noqa: E731
    reds = ["pulse:x failing rc=1 (3 h) — boom", "audit chain BROKEN — 3 unsigned of 500 (verified 2 h)"]
    base = {
        "red-status": ok({"verdict": "RED", "why": "2 red", "counts": {"red": 2, "unreadable": 0, "holds": 1}, "reds": reds, "sources_missing": []}),
        "rem-status": ok({"verdict": "RED", "why": "w", "counts": {"act_now": 2, "regrade": 0, "blocked_severe": 1, "pending": 7}}),
        "loop-status": ok({"rows": [{}, {}, {}], "unlanded": [{}], "fixture_rows": []}),
        "estate-status": ok({"verdict": "UNKNOWN", "why": "w", "counts": {"lines": 9, "disagree": 0, "unreadable": 1, "uncomparable": 2}}, 2),
        "agent-status": ok({"verdict": "OK", "why": "w", "counts": {"running": 0, "hung": 0, "runs_14d": 12}}),
    }
    first = digest("t1", base, None)
    assert first["changed"] is False and first["no_comparison"] == "no earlier comparable digest", first   # first run: quiet
    assert first["readers"]["rem-status"]["counts"] == {"act_now": 2, "regrade": 0, "blocked_severe": 1, "pending": 7}
    assert first["readers"]["loop-status"]["len"] == {"rows": 3, "unlanded": 1} and first["readers"]["estate-status"]["exit_code"] == 2
    md = markdown(first)
    for line in ("counts.act_now: 2", "counts.red: 2", "len(unlanded): 1", "len(reds): 2", "reader: tools/estate-status.py --no-fetch --json (exit 2)",
                 "verdict: (the reader gives none)", f"- {reds[0]}"):
        assert line in md, (line, md)
    # the same reds an hour later (ages and counts moved): the same set, no note
    aged = dict(base, **{"red-status": ok({"reds": ["pulse:x failing rc=1 (4 h) — boom again", "audit chain BROKEN — 9 unsigned of 512 (verified 1 min)"], "sources_missing": []})})
    same = digest("t2", aged, first)
    assert same["changed"] is False and same["started"] == same["stopped"] == [], same
    moved = dict(base, **{"red-status": ok({"reds": [reds[0], "restic repository unreachable (since 2 d)"], "sources_missing": []})})
    m = digest("t3", moved, first)
    assert m["changed"] and m["started"] == ["restic repository unreachable"] and m["stopped"] == ["audit chain BROKEN — # unsigned of #"], m
    # a reader that did not answer is UNKNOWN and holds the note back, whatever the reds say
    down = dict(moved, **{"agent-status": {"state": "UNKNOWN", "error": "no answer in 60 s"}})
    u = digest("t3", down, first)
    assert u["changed"] is False and u["unknown"] == ["agent-status"] and "UNKNOWN: no answer in 60 s" in markdown(u), u
    assert digest("t3", {k: v for k, v in moved.items() if k != "rem-status"}, first)["unknown"] == ["rem-status"]
    # red-status with an unreadable source: its trailing lines are not red, and nothing is compared
    blind = dict(base, **{"red-status": ok({"reds": [reds[0], "wing.db unreadable"], "sources_missing": ["wing.db unreadable"]})})
    b = digest("t3", blind, first)
    assert b["reds"] == [reds[0]] and b["changed"] is False and "could not read 1 source" in b["no_comparison"], b
    with tempfile.TemporaryDirectory() as t:
        tools, d, now = Path(t) / "tools", Path(t) / "digests", time.time()
        tools.mkdir()
        (tools / "codes.py").write_text('import json, sys\nprint(json.dumps({"verdict": "RED", "counts": {"n": 1}}))\nsys.exit(2)\n')
        (tools / "noise.py").write_text('print("not json")\n')
        (tools / "list.py").write_text('print("[1, 2]")\n')
        (tools / "slow.py").write_text("import time\ntime.sleep(5)\n")
        got = ask(("codes.py",), tools)
        assert got["state"] == "OK" and got["exit_code"] == 2 and got["doc"]["counts"] == {"n": 1}, got   # a code is carried, not escalated
        assert ask(("noise.py",), tools)["state"] == "UNKNOWN" and ask(("list.py",), tools)["state"] == "UNKNOWN"
        assert ask(("absent.py",), tools)["state"] == "UNKNOWN" and ask(("slow.py",), tools, timeout=1)["error"] == "no answer in 1 s"
        d.mkdir()
        for age, doc in ((40, first), (10, u), (0, m)):
            stamp = time.strftime(STAMP, time.gmtime(now - age * 86400))
            (d / f"{stamp}.json").write_text(json.dumps(dict(doc, at=stamp)))
            (d / f"{stamp}.md").write_text("x")
        (d / "notes.json").write_text("{}")   # not a stamped digest: never touched
        assert previous(d)["red_keys"] == m["red_keys"]
        (sorted(d.glob("2*.json"))[-1]).unlink()                 # without the newest, the UNKNOWN run is stepped over
        assert previous(d)["red_keys"] == first["red_keys"]
        assert prune(d, now, 30) == 1 and len(_stamped(d)) == 1 and len(list(d.glob("*.md"))) == 2 and (d / "notes.json").exists()
        assert prune(d, now + 400 * 86400, 30) == 0 and len(_stamped(d)) == 1   # the newest always stays
    print("selftest OK: fields copied by name, ages do not move the set, UNKNOWN and unreadable sources hold the note, "
          "first run quiet, exit codes carried, prune keeps the newest")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--trend" in sys.argv:
        print_trend(DIR)
        return 0
    now = time.strftime(STAMP, time.gmtime())
    with ThreadPoolExecutor(len(READERS)) as pool:   # side by side: five 60 s timeouts fit the job's 300 s
        replies = dict(zip((r[0] for r in READERS), pool.map(lambda r: ask(r[1]), READERS)))
    d = digest(now, replies, previous(DIR))
    if "--dry" in sys.argv:
        sys.stdout.write(markdown(d))
        return 0
    DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    for suffix, text in ((".json", json.dumps(d, indent=2) + "\n"), (".md", markdown(d))):
        f = DIR / f"{now}{suffix}"
        f.touch(mode=0o600)   # a red line can quote a job's last output line
        f.write_text(text)
    sent = note(d) if d["changed"] else None
    pruned = prune(DIR, time.time())
    print(f"ops-digest: red={len(d.get('red_keys') or [])} unknown={','.join(d['unknown']) or '-'} changed={d['changed']} "
          f"note={'sent' if sent else 'not sent' if sent is False else 'none'} pruned={pruned}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
