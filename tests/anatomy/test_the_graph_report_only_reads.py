"""Anatomy CI gate — tools/graph-report.py is a reader, and reports UNKNOWN.

Same contract as tools/red-status.py, and for the same reason: a reader that can
mutate the thing it reports on is not a reader, and one that reports an
unanswerable question as either fine or broken is worse than silent.

The specific trap this file pins, MEASURED while writing the reader on
2026-09-02: the rot check resolves file:line citations out of an edge's `via`
prose and asks git when that file last changed. The first draft treated every
match as repo-relative and reported four LIVE files as deleted — `scan-state.json`
is a name in a sentence, `skills/run-tofu-drift.sh` is a path fragment six
directories deep. The second draft resolved them but still called a RUNTIME path
(`nos/cortex-corpus-diff.json`, which lives under ~/.nos) rotted evidence.

So: a citation that resolves and moved is ROTTED; one that resolves nowhere is
UNVERIFIABLE, and the two never share a bucket.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "graph-report.py"


def _body() -> str:
    return "\n".join(ln for ln in TOOL.read_text(encoding="utf-8").splitlines()
                     if not ln.lstrip().startswith("#"))


def test_it_does_not_write():
    """No writer verbs. The graph is compiled by anatomy-graph-gen.py; a second
    writer would make the artifact's producer ambiguous."""
    body = _body()
    for verb in ("write_text(", "open(", "unlink(", "mkdir(", "rename("):
        assert verb not in body, (
            f"graph-report.py calls {verb} — it is a READER. Only "
            "tools/anatomy-graph-gen.py may write state/anatomy-graph.json")
    assert "read_text(" in body, "it does not read the graph at all"


def test_git_is_only_ever_asked_to_look():
    """It shells to git for `log` and `ls-files`. Anything that moves a ref or a
    working tree does not belong in a reader."""
    body = _body()
    calls = re.findall(r'\["git",\s*"([a-z-]+)"', body)
    assert calls, "no git invocation found; the rot check cannot work without one"
    assert set(calls) <= {"log", "ls-files"}, (
        f"graph-report.py runs git {sorted(set(calls) - {'log', 'ls-files'})} — "
        "a reader looks, it never moves a ref or a tree")


def test_unverifiable_is_not_reported_as_rotted():
    """A citation naming no repo file is UNKNOWN. Filing it as rot inflates the
    count with runtime paths and teaches the reader to be ignored."""
    body = _body()
    assert "unverifiable" in body, (
        "there is no unverifiable bucket, so a citation that resolves nowhere is "
        "being called either fresh or rotted. `nos/cortex-corpus-diff.json` "
        "lives under ~/.nos and is neither")
    rot_block = body[body.index("rotted, unverifiable"):]
    assert "_resolve(" in rot_block, (
        "citations are not resolved before being judged; a path fragment like "
        "'skills/run-tofu-drift.sh' then reads as a deleted file")


def test_it_runs_and_exits_zero_on_findings():
    """Live check: a report is not a gate. Exit 1 on a finding would make the
    nightly job red for a condition that needs reading, not alarming."""
    run = subprocess.run(["python3", str(TOOL), "--json"], cwd=REPO,
                         capture_output=True, text=True, timeout=180)
    assert run.returncode == 0, (
        f"graph-report.py exited {run.returncode} without --exit-nonzero-on-rot:\n"
        f"{run.stderr[-2000:]}")
    out = json.loads(run.stdout)
    assert out["edges"] > 0 and out["nodes"] > 0, "the report found no graph"
    assert "rotted" in out and "unverifiable" in out, "the buckets are not reported"
