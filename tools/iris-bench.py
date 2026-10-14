#!/usr/bin/env python3
"""Score what Iris does, from the thalamus wire alone, with code as judge.

Each case in state/fixtures/iris-bench.yml (one `prompt`, or `turns` in one
session) goes to the thalamus socket as ToThalamus turn messages; the ToShell
lines that come back are the whole evidence. A turn ends on activity `idle`
(serve sends one after every turn, however it ended, and one after a decision);
a decision serve refuses (thalamus_decider_exes set) ends on `refused` instead.

It only reads. Every approval_request is rejected with the decision the pupil
sends for reject, so nothing is written; it never sends form_submit or widget,
and it never writes a roadmap row. A live run needs NOS_LIVE=1; `--offline`
with an explicit `--sock` is the test path (a fake thalamus).

Usage:
    NOS_LIVE=1 tools/iris-bench.py                  # ~/.nos/thalamus.sock
    tools/iris-bench.py --sock /tmp/fake.sock --offline --out /tmp/run.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CASES = REPO / "state/fixtures/iris-bench.yml"
OUT = REPO / "state/fixtures/iris-bench/last-run.json"
SOCK = Path.home() / ".nos/thalamus.sock"
BLANK = "(Iris gave no answer.)"
CANNOT_SEE = ("cannot see", "can't see", "can not see", "unable to see", "not able to see", "have no tool",
              "have no access", "don't have access", "do not have access", "not visible to me",
              "nevidím", "nemám přístup", "nemohu vidět", "nemůžu vidět", "nemám nástroj", "nedokážu zjistit")
# A verdict next to the disclaimer is a guess ("I can't see any failures, all green"), not cannot-see.
VERDICT = ("green", "healthy", "all clear", "all good", "nothing is red", "no failures", "zelen", "v pořádku", "nic není červen")
NUM = re.compile(r"\d+(?:\.\d+)?")
CLOCK = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")


FILLER = "Toto je výplňový text bez dalšího významu, jen zabírá místo v kontextu."
# Czech vs English by function words and diacritics: crude, but a reply in the wrong language fails it.
CS_WORDS = {"je", "a", "v", "se", "na", "to", "že", "má", "mám", "jsou", "není", "nevidím", "ano", "ne", "tak", "z", "s",
            "o", "do", "pro", "jen", "jako", "už", "teď", "odsud", "žádný", "jedna", "jeden", "nahoře", "podle"}
EN_WORDS = {"the", "is", "are", "and", "of", "in", "has", "have", "it", "this", "there", "rows", "count", "with", "for"}
DIACRITICS = set("áčďéěíňóřšťúůýž")


def turns_of(case: dict) -> list[str]:
    """The case's turns; a `pad` puts its fact first and filler words before the first question."""
    turns = list(case["turns"]) if "turns" in case else [case["prompt"]]
    pad = case.get("pad")
    if pad:
        n = len(FILLER.split())
        filler = " ".join([FILLER] * (-(-int(pad["words"]) // n)))
        turns[0] = f"{pad['fact']} {filler}\n\n{turns[0]}"
    return turns


def run_case(case: dict, sock: str, timeout: float) -> dict:
    """Send the case's turns over one connection; what came back, per kind."""
    turns = turns_of(case)
    got = {"tools": [], "renders": [], "approvals": [], "refused": [], "text": "", "model_uri": None, "error": None}
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(sock)
        f = s.makefile("rw", encoding="utf-8")
        session = None
        for text in turns:
            f.write(json.dumps({"t": "turn", "session": session, "text": text}) + "\n")
            f.flush()
            want, idle, answer = 1, 0, ""
            while idle < want:
                line = f.readline()
                if not line:
                    raise ConnectionError("the thalamus closed the connection mid-turn")
                m = json.loads(line)
                t = m.get("t")
                if t == "session":
                    session, got["model_uri"] = m.get("session"), m.get("model_uri")
                elif t == "activity":
                    ph = m.get("phase")
                    if ph == "idle":
                        idle += 1
                    elif isinstance(ph, dict) and "tool" in ph:
                        got["tools"].append(ph["tool"].get("name"))
                elif t == "render":
                    got["renders"].append(m)
                elif t == "approval_request":
                    got["approvals"].append(m.get("approval"))
                    # The decision the pupil sends for reject (approvals.ts); serve answers it with text + idle.
                    f.write(json.dumps({"t": "approval_decision", "approval": m.get("approval"),
                                        "decision": "reject", "note": None}) + "\n")
                    f.flush()
                    want += 1
                elif t == "text" and idle == 0:
                    answer = m.get("text", "")
                elif t == "refused":
                    got["refused"].append(m.get("reason"))
                    # A refused decision (decider guard on: this client is not listed) gets no idle.
                    if want > 1:
                        want -= 1
            got["text"] = answer
    except (OSError, ValueError, ConnectionError) as e:
        got["error"] = f"{type(e).__name__}: {e}"
    finally:
        s.close()
    return got


def _nums(text: str) -> list[float]:
    return [float(n) for n in NUM.findall(text)]


def _drawn_numbers(renders: list[dict]) -> set[float]:
    out: set[float] = set()
    for r in renders:
        c = r.get("component", {})
        p = c.get("props", {})
        if c.get("kind") == "chart":
            out |= {float(v) for s in p.get("series", []) for _, v in s.get("points", [])}
        elif c.get("kind") == "table_results":
            out |= {float(v) for row in p.get("rows", []) for v in row.get("cells", {}).values()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return out


def check(name: str, arg, got: dict, now: float) -> bool:
    text = got["text"]
    kinds = [(r["component"].get("kind"), r["component"].get("props", {}).get("chart")) for r in got["renders"]]
    if name == "tools_called":  # a subsequence, in order
        it = iter(got["tools"])
        return all(any(t == want for t in it) for want in arg)
    if name == "kinds_drawn":
        return all(any(k == w.split(":")[0] and (":" not in w or c == w.split(":")[1]) for k, c in kinds) for w in arg)
    if name == "count_equals_matched":
        tr = [r for r in got["renders"] if r["component"].get("kind") == "table_results"]
        return bool(tr) and float(tr[-1]["component"]["props"]["matched"]) in _nums(text)
    if name == "no_number_without_source":
        charts = [r for r in got["renders"] if r["component"].get("kind") == "chart"]
        return bool(charts) and all(r.get("pin") for r in charts)
    if name == "time_within":
        t = time.gmtime(now) if arg.get("clock", "utc") == "utc" else time.localtime(now)
        mins = t.tm_hour * 60 + t.tm_min
        said = [int(h) * 60 + int(m) for h, m in CLOCK.findall(text)]
        return any(min(abs(s - mins), 1440 - abs(s - mins)) <= arg.get("minutes", 2) for s in said)
    if name == "says_cannot_see":
        low = text.lower()
        return any(p in low for p in CANNOT_SEE) and not any(v in low for v in VERDICT)
    if name == "no_proposal":
        return not got["approvals"]
    if name == "not_repeated":  # no run of 3+ numbers in the text that a render just drew
        drawn, run = _drawn_numbers(got["renders"]), 0
        for n in _nums(text):
            run = run + 1 if n in drawn else 0
            if run >= 3:
                return False
        return True
    if name == "answers_in":
        if arg != "cs":
            raise ValueError(f"answers_in knows only cs, not {arg!r}")
        words = re.findall(r"[^\W\d_]+", text.lower())
        cs = sum(w in CS_WORDS for w in words) + (1 if DIACRITICS & set(text.lower()) else 0)
        en = sum(w in EN_WORDS for w in words)
        return cs >= 2 and cs > en
    if name == "text_contains":
        return str(arg) in text
    if name == "not_blank":
        return bool(text.strip()) and text.strip() != BLANK
    raise ValueError(f"unknown check {name!r}")


def score(case: dict, got: dict, now: float) -> list[str]:
    if got["error"]:
        return [f"error: {got['error']}"]
    return [name for name, arg in case.get("checks", {}).items() if arg is not False and not check(name, arg, got, now)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sock")
    ap.add_argument("--offline", action="store_true", help="test path: needs an explicit --sock")
    ap.add_argument("--cases", default=str(CASES))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--timeout", type=float, default=180.0, help="seconds without a line before a case fails")
    a = ap.parse_args(argv)
    if not (os.environ.get("NOS_LIVE") == "1" or (a.offline and a.sock)):
        print("iris-bench talks to the live thalamus (a model, KEAP, the ledger); set NOS_LIVE=1, "
              "or pass --offline with an explicit --sock for a fake.", file=sys.stderr)
        return 2
    sock = a.sock or str(SOCK)
    cases = yaml.safe_load(Path(a.cases).read_text(encoding="utf-8"))
    results = []
    for case in cases:
        t0 = time.monotonic()
        got = run_case(case, sock, a.timeout)
        secs = round(time.monotonic() - t0, 2)
        failed = score(case, got, time.time())
        results.append({"id": case["id"], "pass": not failed, "failed": failed, "seconds": secs,
                        "model_uri": got["model_uri"], "tools": got["tools"], "approvals_rejected": len(got["approvals"]),
                        "refused": got["refused"], "text": got["text"]})
    run = {"ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "sock": sock,
           "model_uri": sorted({r["model_uri"] for r in results if r["model_uri"]}), "cases": results}
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for r in results:
        print(f"{'PASS' if r['pass'] else 'FAIL'}  {r['id']:<16} {r['seconds']:>7.2f}s  {', '.join(r['failed'])}")
    print(f"{sum(r['pass'] for r in results)}/{len(results)} passed · {', '.join(run['model_uri']) or 'no model_uri'} · {out}")
    return 0 if all(r["pass"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
