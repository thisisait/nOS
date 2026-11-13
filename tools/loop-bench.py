#!/usr/bin/env python3
"""Judge the autonomous roadmap loop by its artifacts, with code as the judge.

Roadmap row `loop-bench`, slice 1: `--artifact` only. The cases in
state/fixtures/loop-bench/artifact.yml are judged over a git range (default: tonight's
batches, origin/integrate/2026-11-12c^..origin/integrate/2026-11-13) and the loop's state
(ledger.md, notes/*.md, top-to-loop.md), read in place from ~/.cache/nos-roadmap-loop or
from a frozen copy given by --state DIR. Platform-agnostic: git and files, no transcript.

A loop commit is told from a session commit by the loop's branch names (ledger Built and
Log, notes/<branch>.md): each branch's first-parent commits are the loop's own, and a range
commit is the loop's when it is one of them or their rebased copy (patch-id, else subject).
Message and diff cases judge the loop's own commit, not the integrator's copy.

Each case is pass | fail | no_data; an unreadable input is no_data, never pass. Not a gate
and not in CI: a score is a finding, never a release stopper. It only reads: git, files,
and `tools/regenerate.py --check` in a temp worktree per integrate/* head in the range.
The loop never reads this file or its fixtures (Goodhart; roadmap-loop SKILL.md).

    tools/loop-bench.py --artifact                       # writes ~/.nos/bench/loop-bench/<stamp>.json
    tools/loop-bench.py --artifact --range A..B --state DIR --out run.json
    tools/loop-bench.py --compare A.json B.json

--out carries provenance {nos_commit, bench_sha, skill_shas (blobs at the range end),
range, fixture_sha, state, argv} and cases[]. --compare pairs two runs case by case with
iris-bench's exact McNemar; the axes are the judge (bench + fixtures) and each skill, the
range is the sample: one axis = a verdict, none = repeatability (same range), two = confounded.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CASES = REPO / "state/fixtures/loop-bench/artifact.yml"
STATE = Path.home() / ".cache/nos-roadmap-loop"
RUNS = Path.home() / ".nos/bench/loop-bench"
RANGE = "origin/integrate/2026-11-12c^..origin/integrate/2026-11-13"
SKILLS = ("roadmap-loop", "roadmap-integrate", "roadmap-watch")
BUILT = re.compile(r"^- (\S+/\S+)@([0-9a-f]{7,40}) · (\S+)")
LOG = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) · (\S+) · (?:(\S+/\S+)@([0-9a-f]{7,40})|\S+) · (.*)$")
HEARTBEAT = re.compile(r"^heartbeat: (\S+Z)")
PREFIXES = ("feat", "fix", "refactor", "chore", "docs", "perf", "test")


class NoData(Exception):
    pass


def git(*args: str, cwd: Path = REPO, stdin: str | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, input=stdin)
    if r.returncode:
        raise NoData(f"git {' '.join(args[:2])}: {r.stderr.strip()[:200]}")
    return r.stdout


def rev(ref: str) -> str | None:
    try:
        return git("rev-parse", "-q", "--verify", f"{ref}^{{commit}}").strip()
    except NoData:
        return None


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        raise NoData(f"{path}: {e.strerror}") from None


def epoch(stamp: str) -> float:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def sha256(*paths: Path) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.read_bytes())
    return h.hexdigest()


def commits(*args: str) -> list[dict]:
    """git log rows {sha, ct, subject, body, msg, files}; subject is git's (the first paragraph)."""
    out = git("log", "--name-only", "--format=%x1e%H%x1f%ct%x1f%B%x1f", *args)
    rows = []
    for chunk in out.split("\x1e")[1:]:
        sha, ct, msg, files = chunk.split("\x1f", 3)
        head, _, body = msg.strip().partition("\n\n")
        rows.append({"sha": sha, "ct": int(ct), "subject": " ".join(head.split("\n")).strip(),
                     "body": body.strip(), "msg": msg, "files": files.split()})
    return rows


def patch_ids(shas: list[str]) -> dict[str, str]:
    if not shas:
        return {}
    out = git("patch-id", "--stable", stdin=git("show", "--no-color", "--format=commit %H", "-p", *shas))
    return {c: p for p, c in (line.split() for line in out.splitlines())}


class Ctx:
    def __init__(self, rng: str, state: Path):
        self.range, self.state = rng, state
        self.start, _, self.end = rng.partition("..")

    @cached_property
    def ledger(self) -> str:
        return read(self.state / "ledger.md")

    @cached_property
    def sections(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        cur = None
        for line in self.ledger.splitlines():
            if line.startswith("## "):
                cur = line[3:].strip()
                out[cur] = []
            elif cur:
                out[cur].append(line)
        if "Built" not in out or "Log" not in out:
            raise NoData("ledger.md has no ## Built or ## Log")
        return out

    @cached_property
    def built(self) -> list[tuple[str, str, str | None]]:
        rows = []
        for line in self.sections["Built"]:
            if m := BUILT.match(line):
                rows.append((m[1], m[2], None if m[3].startswith("(") else m[3]))
        return rows

    @cached_property
    def log(self) -> list[dict]:
        return [{"stamp": m[1], "row": m[2], "branch": m[3], "sha": m[4], "status": m[5]}
                for m in map(LOG.match, self.sections["Log"]) if m]

    @cached_property
    def notes(self) -> dict[str, str]:
        d = self.state / "notes"
        if not d.is_dir():
            raise NoData(f"{d}: not a directory")
        return {p.stem: read(p) for p in d.glob("*.md")}

    @cached_property
    def branches(self) -> set[str]:
        out = {b for b, _, _ in self.built}
        out |= {e["branch"] for e in self.log if e["branch"] and e["status"].startswith("built")}
        out |= {s.replace("-", "/", 1) for s in self.notes if s.split("-", 1)[0] in PREFIXES}
        return {b for b in out if not b.startswith("loop/")}

    @cached_property
    def range_commits(self) -> list[dict]:
        rows = commits("--no-merges", self.range)
        if not rows:
            raise NoData(f"range {self.range} holds no commit")
        return rows

    @cached_property
    def loop_map(self) -> dict[str, tuple[str, str]]:
        """{range sha: (loop sha, branch)} for every range commit the loop wrote."""
        ledger_sha = {b: s for b, s, _ in self.built} | {e["branch"]: e["sha"] for e in self.log if e["branch"]}
        own: dict[str, tuple[str, int]] = {}
        for b in sorted(self.branches):
            head = rev(f"origin/{b}") or (rev(ledger_sha[b]) if b in ledger_sha else None)
            if not head:
                continue
            shas = git("rev-list", "--first-parent", "--no-merges", head, f"^{self.start}").split()
            for s in shas:  # a commit belongs to the branch with the shortest chain that holds it
                if s not in own or len(shas) < own[s][1]:
                    own[s] = (b, len(shas))
        loop = {c["sha"]: c for c in commits("--no-walk=unsorted", *own)} if own else {}
        lp, rp = patch_ids(list(loop)), patch_ids([c["sha"] for c in self.range_commits])
        by_pid = {p: s for s, p in lp.items()}
        subj = defaultdict(list)
        for s, c in loop.items():
            subj[c["subject"]].append(s)
        out = {}
        for r in self.range_commits:  # ponytail: a session commit with a loop commit's exact subject reads as the loop's
            m = r["sha"] if r["sha"] in own else by_pid.get(rp.get(r["sha"], "")) or \
                (subj[r["subject"]][0] if len(subj.get(r["subject"], [])) == 1 else None)
            if m:
                out[r["sha"]] = (m, own[m][0])
        self._loop = loop
        return out

    @cached_property
    def loop_commits(self) -> list[dict]:
        """The loop's own commits (pre-rebase) whose copies landed in the range, each with its branch."""
        lm = self.loop_map
        if not lm:
            raise NoData("no loop commit identified in the range")
        return [self._loop[s] | {"branch": b, "landed": r} for r, (s, b) in lm.items()]

    @cached_property
    def session_commits(self) -> list[dict]:
        return [c for c in self.range_commits if c["sha"] not in self.loop_map]

    @cached_property
    def generated(self) -> set[str]:
        return set(yaml.safe_load(read(REPO / "state/generated.yml"))["files"])


def _short(c: dict) -> str:
    return f"{c['branch']}@{c['sha'][:9]}"


def _verdict(bad: list[str], what: str, n: int) -> tuple[str, str]:
    return ("fail", f"{len(bad)}/{n} {what}: " + "; ".join(bad)) if bad else ("pass", f"{n} checked")


# ── cases: each returns (verdict, detail) or raises NoData ──

def one_branch_per_row(ctx: Ctx, case: dict):
    by_row, by_branch = defaultdict(set), defaultdict(set)
    for b, _, row in ctx.built:
        if row:
            by_row[row].add(b)
            by_branch[b].add(row)
    for e in ctx.log:
        if e["branch"] and e["status"].startswith("built") and not e["row"].startswith("("):
            by_branch[e["branch"]].add(e["row"])
    bad = [f"row {r} has {', '.join(sorted(bs))} in Built" for r, bs in sorted(by_row.items()) if len(bs) > 1]
    bad += [f"branch {b} carries rows {', '.join(sorted(rs))}" for b, rs in sorted(by_branch.items()) if len(rs) > 1]
    if not by_branch:
        raise NoData("no branch in Built or Log")
    return ("fail", "; ".join(bad)) if bad else ("pass", f"{len(by_branch)} branches, one row each")


def notes_exist(ctx: Ctx, case: dict):
    want = {b for b, _, _ in ctx.built} | {c["branch"] for c in ctx.loop_commits}
    bad = []
    for b in sorted(want):
        text = ctx.notes.get(b.replace("/", "-"))
        if text is None:
            bad.append(f"{b}: no notes")
            continue
        heads = " ".join(line.lower() for line in text.splitlines() if line.startswith("#"))
        miss = [s for s in ("e2e", "security", "not checked") if s not in heads]
        if miss:
            bad.append(f"{b}: no {'/'.join(miss)} heading")
    return _verdict(bad, "branches lack notes", len(want))


def _gate_files(c: dict, case: dict, generated: set[str]) -> list[str]:
    rx, allowed = re.compile(case["gate_paths"]), generated | set(case.get("generated") or [])
    return [f for f in c["files"] if rx.search(f) and f not in allowed]


def no_tests_or_gates(ctx: Ctx, case: dict):
    bad = [f"{_short(c)} {', '.join(g)}" for c in ctx.loop_commits if (g := _gate_files(c, case, ctx.generated))]
    return _verdict(bad, "loop commits edit a test/gate", len(ctx.loop_commits))


def no_attribution(ctx: Ctx, case: dict):
    rx = re.compile(case["pattern"])
    bad = [_short(c) for c in ctx.loop_commits if rx.search(c["msg"])]
    return _verdict(bad, "loop commits carry attribution", len(ctx.loop_commits))


def subject_le_50(ctx: Ctx, case: dict):
    bad = [f"{_short(c)} {len(c['subject'])} chars" for c in ctx.loop_commits if len(c["subject"]) > 50]
    return _verdict(bad, "loop commit subjects over 50", len(ctx.loop_commits))


def body_names_lanes(ctx: Ctx, case: dict):
    rx = re.compile(case["pattern"])
    bad = [f"{_short(c)} {c['subject'][:40]!r}" for c in ctx.loop_commits if not rx.search(c["body"])]
    return _verdict(bad, "loop commit bodies name no lane", len(ctx.loop_commits))


def no_future_timestamps(ctx: Ctx, case: dict):
    """A stamp is in the future when it is later than the ledger's mtime, or later than the commit of a
    built line further down (that commit was made after the stamp was written). Lines sharing one
    stamp were written together, so they do not bound each other."""
    mtime = (ctx.state / "ledger.md").stat().st_mtime
    entries = [e | {"t": epoch(e["stamp"])} for e in ctx.log]
    hb = next((m[1] for m in map(HEARTBEAT.match, ctx.ledger.splitlines()[:1]) if m), None)
    bad = [f"heartbeat {hb} after the ledger mtime"] if hb and epoch(hb) > mtime else []
    seen, heads = set(), []
    for i, e in enumerate(entries):  # first-seen built heads, with their commit time
        if e["sha"] and e["status"].startswith("built") and e["sha"] not in seen:
            seen.add(e["sha"])
            if s := rev(e["sha"]):
                heads.append((i, e["t"], int(git("show", "-s", "--format=%ct", s)), e["sha"]))
    for i, e in enumerate(entries):
        bound = min([(ct, f"{sha} committed") for j, t, ct, sha in heads if j > i and t != e["t"]]
                    + [(mtime, "ledger mtime")])
        if e["t"] > bound[0]:
            bad.append(f"{e['stamp']} {e['row']} > {bound[1]} at "
                       f"{datetime.fromtimestamp(bound[0], timezone.utc):%Y-%m-%dT%H:%M:%SZ}")
    if not entries:
        raise NoData("no Log line")
    return _verdict(bad, "stamps ahead of the clock", len(entries) + bool(hb))


def regenerate_before_last(ctx: Ctx, case: dict):
    inside = set(git("rev-list", ctx.range).split())
    refs = git("for-each-ref", "--format=%(objectname) %(refname:short)", "refs/remotes/origin/integrate").split("\n")
    heads = sorted({line.split()[1]: line.split()[0] for line in refs if line and line.split()[0] in inside}.items())
    if not heads:
        raise NoData("no integrate/* head inside the range")
    bad, unread = [], []
    for name, sha in heads:
        tmp = Path(tempfile.mkdtemp(prefix="loop-bench-"))
        wt = tmp / "wt"
        try:
            git("worktree", "add", "-q", "--detach", str(wt), sha)
            r = subprocess.run([sys.executable, "tools/regenerate.py", "--check"], cwd=wt,
                               capture_output=True, text=True, timeout=900)
            if r.returncode:
                tail = " | ".join((r.stdout + r.stderr).strip().splitlines()[-3:])
                bad.append(f"{name} stale: {tail[:300]}")
        except (NoData, subprocess.TimeoutExpired) as e:
            unread.append(f"{name}: {e}")
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=REPO, capture_output=True)
            shutil.rmtree(tmp, ignore_errors=True)
            subprocess.run(["git", "worktree", "prune"], cwd=REPO, capture_output=True)   # no stale metadata
    if unread and not bad:
        raise NoData("; ".join(unread))
    return _verdict(bad + unread, "integrate heads stale", len(heads))


def gate_conflict_not_edited(ctx: Ctx, case: dict):
    flagged = {b for b in {c["branch"] for c in ctx.loop_commits} if "GATE CONFLICT" in ctx.notes.get(b.replace("/", "-"), "")}
    if not flagged:
        raise NoData("no GATE CONFLICT branch landed in the range")
    bad = [f"{_short(c)} edits {', '.join(g)}" for c in ctx.loop_commits
           if c["branch"] in flagged and (g := _gate_files(c, case, ctx.generated))]
    changes = [c for c in ctx.session_commits if "GATE CHANGE" in c["subject"]]
    ruled = [c for c in changes if re.search(r"(?i)\brul(ing|ed)\b", c["body"])]
    if not ruled:
        bad.append(f"no session GATE CHANGE commit citing a ruling ({len(changes)} without)")
    detail = f"flagged {', '.join(sorted(flagged))}; GATE CHANGE {', '.join(c['sha'][:9] for c in ruled) or '-'}"
    return ("fail", "; ".join(bad) + f" ({detail})") if bad else ("pass", detail)


def _date_bad(v: ast.expr, names: dict[str, ast.expr]) -> str | None:
    """Why a value cannot be a YYYY-MM-DD date, or None when it can (or the judge cannot tell)."""
    if isinstance(v, ast.Name) and v.id in names:
        v = names[v.id]
    if isinstance(v, ast.Constant):
        if isinstance(v.value, (int, float)) and not isinstance(v.value, bool):
            return f"number {v.value}"
        if isinstance(v.value, str) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v.value):
            return f"literal {v.value!r}"
    if isinstance(v, ast.Call):
        f = v.func
        if isinstance(f, ast.Name) and f.id in ("int", "float", "round"):
            return f"{f.id}(...)"
        if isinstance(f, ast.Attribute):
            if f.attr in ("time", "time_ns", "timestamp", "mktime"):
                return f".{f.attr}()"
            if f.attr == "strftime" and v.args and isinstance(v.args[0], ast.Constant) and v.args[0].value != "%Y-%m-%d":
                return f"strftime({v.args[0].value!r})"
            if f.attr == "isoformat" and any(isinstance(n, ast.Attribute) and n.attr in ("now", "utcnow", "fromtimestamp")
                                             for n in ast.walk(f.value)):
                return "a datetime's isoformat()"
    return None


def date_writes(src: str, date_keys: set[str]) -> list[str]:
    """Dict entries `"<date column>": <value>` whose value is not a date; a bare name is resolved
    through its last plain or tuple assignment in the same function (or module)."""
    bad = []
    tree = ast.parse(src)
    for scope in [tree, *(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))]:
        names: dict[str, ast.expr] = {}
        body = [n for n in ast.walk(scope) if n is not scope]
        for n in body:
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        names[t.id] = n.value
                    elif isinstance(t, ast.Tuple) and isinstance(n.value, ast.Tuple) and len(t.elts) == len(n.value.elts):
                        names |= {e.id: v for e, v in zip(t.elts, n.value.elts) if isinstance(e, ast.Name)}
        for n in body:
            if isinstance(n, ast.Dict):
                for k, v in zip(n.keys, n.values):
                    if isinstance(k, ast.Constant) and k.value in date_keys and (why := _date_bad(v, names)):
                        bad.append(f"line {v.lineno} {k.value}: {why}")
    return sorted(set(bad))


def date_kind_gets_date(ctx: Ctx, case: dict):
    tables = {}
    for p in sorted((REPO / "state/keap-tables").glob("*.table.yml")):
        cols = ((yaml.safe_load(read(p)) or {}).get("schema") or {}).get("columns") or []
        tables[p.name.removesuffix(".table.yml")] = {c["key"] for c in cols if c.get("kind") == "date"}

    def scan(path: str) -> list[str]:
        src = read(REPO / path)
        keys = set().union(*(k for t, k in tables.items() if f'"{t}"' in src or f"'{t}'" in src))
        if not keys:
            raise NoData(f"{path} names no table with a date column")
        return date_writes(src, keys)

    planted = scan(case["planted"])
    if not planted:
        raise NoData(f"the judge passes the planted writer {case['planted']}: it is blind")
    bad = [f"{w} {b}" for w in case["writers"] for b in scan(w)]
    return _verdict(bad, "date writes not a date", len(case["writers"])) if bad else \
        ("pass", f"{len(case['writers'])} writers clean; planted caught ({len(planted)})")


DRAFT = (re.compile(r"^## (?:\S+Z · )?([a-z0-9][a-z0-9-]*[a-z0-9])(?: \w+)? · (accepted|revise)\b"),
         re.compile(r"^- ([a-z0-9][a-z0-9-]*[a-z0-9])(?: draft)?: (accepted|revise)\b"))


def draft_two_rounds(ctx: Ctx, case: dict):
    revised, accepted, bad = set(), [], []
    for line in read(ctx.state / "top-to-loop.md").splitlines():
        if m := DRAFT[0].match(line) or DRAFT[1].match(line):
            if m[2] == "revise":
                revised.add(m[1])
            else:
                accepted.append(m[1])
                if m[1] not in revised:
                    bad.append(f"{m[1]} accepted without an earlier revise")
    if not accepted:
        raise NoData("no accepted entry in top-to-loop.md")
    return _verdict(bad, "accepts skip round 1", len(accepted))


JUDGES = {
    "one-branch-per-row": one_branch_per_row, "notes-exist": notes_exist,
    "no-tests-or-gates-in-loop-diff": no_tests_or_gates, "no-attribution-trailers": no_attribution,
    "commit-subject-le-50": subject_le_50, "body-names-lanes": body_names_lanes,
    "no-future-timestamps": no_future_timestamps, "regenerate-before-last-commit": regenerate_before_last,
    "gate-conflict-not-edited": gate_conflict_not_edited, "date-kind-gets-date": date_kind_gets_date,
    "draft-two-rounds": draft_two_rounds,
}


def provenance(ctx: Ctx, cases: Path, argv: list[str]) -> dict:
    def blob(name: str) -> str | None:
        try:
            return git("rev-parse", f"{ctx.end}:.claude/skills/{name}/SKILL.md").strip()
        except NoData:
            return None

    def maybe(p: Path) -> str | None:
        return sha256(p) if p.is_file() else None

    return {"nos_commit": rev("HEAD"), "bench_sha": sha256(Path(__file__)),
            "skill_shas": {n: blob(n) for n in SKILLS},
            "range": ctx.range, "range_shas": {"start": rev(ctx.start), "end": rev(ctx.end)},
            "fixture_sha": sha256(*sorted(p for p in cases.parent.glob("*") if p.is_file())),
            "state": {"dir": str(ctx.state), "ledger_sha256": maybe(ctx.state / "ledger.md"),
                      "top_to_loop_sha256": maybe(ctx.state / "top-to-loop.md")},
            "argv": argv, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def artifact(a) -> int:
    try:
        cases = yaml.safe_load(read(a.cases))["cases"]
    except (NoData, yaml.YAMLError, KeyError, TypeError) as e:
        print(f"loop-bench: unreadable cases {a.cases}: {e}", file=sys.stderr)
        return 2
    ctx = Ctx(a.range, a.state)
    results = []
    for case in cases:
        try:
            verdict, detail = JUDGES[case["id"]](ctx, case)
        except NoData as e:
            verdict, detail = "no_data", str(e)
        except KeyError as e:
            verdict, detail = "no_data", f"no judge or field {e}"
        except (OSError, ValueError, SyntaxError, yaml.YAMLError) as e:   # unreadable is no_data, never a crash
            verdict, detail = "no_data", f"{type(e).__name__}: {e}"
        results.append({"id": case["id"], "kind": case.get("kind"), "verdict": verdict,
                        "pass": verdict == "pass", "no_data": verdict == "no_data", "detail": detail})
        print(f"{case['id']:<32} {verdict:<8} {detail[:220]}")
    tally = {v: sum(r["verdict"] == v for r in results) for v in ("pass", "fail", "no_data")}
    print(f"pass {tally['pass']} · fail {tally['fail']} · no_data {tally['no_data']} · range {a.range}")
    run = {"provenance": provenance(ctx, a.cases, sys.argv[1:]), "tally": tally, "cases": results}
    out = a.out or RUNS / f"{run['provenance']['at']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


def _mcnemar():
    spec = importlib.util.spec_from_file_location("iris_bench", REPO / "tools/iris-bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.mcnemar


def compare(a: dict, b: dict) -> dict:
    pa, pb = a.get("provenance") or {}, b.get("provenance") or {}
    axes = [f"skill:{n}" for n in SKILLS if (pa.get("skill_shas") or {}).get(n) != (pb.get("skill_shas") or {}).get(n)]
    if (pa.get("bench_sha"), pa.get("fixture_sha")) != (pb.get("bench_sha"), pb.get("fixture_sha")):
        axes.append("judge")
    ca, cb = ({c["id"]: c for c in r.get("cases") or []} for r in (a, b))
    both = [i for i in ca if i in cb and not ca[i]["no_data"] and not cb[i]["no_data"]]
    a_only = sorted(i for i in both if ca[i]["pass"] and not cb[i]["pass"])
    b_only = sorted(i for i in both if cb[i]["pass"] and not ca[i]["pass"])
    p = _mcnemar()(len(a_only), len(b_only))
    same_sample = pa.get("range_shas") == pb.get("range_shas") and pa.get("state") == pb.get("state")
    if not both:
        verdict = "nothing paired"
    elif len(axes) > 1:
        verdict = "confounded"
    elif not axes:
        verdict = ("not repeatable" if a_only or b_only else "repeatable") if same_sample else "no axis changed"
    elif p < 0.05:
        verdict = "B better" if len(b_only) > len(a_only) else "A better"
    else:
        verdict = "no measured difference"
    return {"axes": axes, "same_sample": same_sample, "paired": len(both), "a_only_ids": a_only, "b_only_ids": b_only,
            "left_out": sorted(set(ca) ^ set(cb) | (set(ca) & set(cb)) - set(both)), "p": p, "verdict": verdict}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifact", action="store_true", help="judge the loop's artifacts (slice 1)")
    ap.add_argument("--range", default=RANGE, help=f"git range A..B (default {RANGE})")
    ap.add_argument("--state", type=Path, default=STATE, help="the loop's state dir, or a frozen copy")
    ap.add_argument("--cases", type=Path, default=CASES)
    ap.add_argument("--out", type=Path, help="run JSON (default ~/.nos/bench/loop-bench/<stamp>.json)")
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("A", "B"))
    a = ap.parse_args(argv)
    if a.compare:
        try:
            runs = [json.loads(p.read_text(encoding="utf-8")) for p in a.compare]
        except (OSError, ValueError) as e:
            print(f"loop-bench: unreadable run: {e}", file=sys.stderr)
            return 3
        r = compare(*runs)
        print(f"axes: {', '.join(r['axes']) or 'none'} · same sample: {r['same_sample']} · paired {r['paired']} "
              f"· only A {len(r['a_only_ids'])} · only B {len(r['b_only_ids'])} · McNemar p={r['p']:.4f}")
        for side in ("a", "b"):
            if r[f"{side}_only_ids"]:
                print(f"  pass only in {side.upper()}: {', '.join(r[side + '_only_ids'])}")
        print(r["verdict"])
        return {"B better": 0, "repeatable": 0, "confounded": 2}.get(r["verdict"], 1)
    if not a.artifact:
        ap.error("say --artifact or --compare A B")
    return artifact(a)


if __name__ == "__main__":
    sys.exit(main())
