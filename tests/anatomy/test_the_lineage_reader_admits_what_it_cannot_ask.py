"""`tools/loop-status.py` may not report an id as unresolvable when it could not ask.

WHAT THE READER IS FOR. `docs/hidden_fees/15` closed its write half on
2026-08-16 — `loop_proposals.weakness_id` now cites ids that join, because
`ProposalRefused("unknown-weakness")` makes anything else unfileable. The half
that entry named last stayed open: *"which weakness sources actually produce
proposals?"*, which nothing read. Run 2026-08-18, first output:

    w1                                8 proposal(s), 1p/7f/0i   UNRESOLVED×1
    rem   — remediation queue         3 proposal(s), 2p/0f/1i
    w2                                1 proposal(s), 1p/0f/0i   UNRESOLVED×1

    reporting weaknesses but never proposed against: alert, corpus, fee, git, pulse

So `rem:` is the only detector that has ever led anywhere, five sources have
never once produced a proposal, and the `w1`/`w2` residue is named as residue
rather than bucketed under something plausible.

THE PROPERTY THIS GATE HOLDS, and why it is the one worth holding. The reader
answers "does this id still join?" by importing Bone's weakness reader and
collecting live ids. That import can fail — Bone has its own dependencies and
this tool runs on hosts that lack them. On that path the set of live ids is
EMPTY, and an empty set makes every id in the ledger look unresolvable. The
report would then be a confident list of twelve broken lineages caused by a
missing import.

That is this estate's most-repeated defect wearing its other face: not absence
read as health, but absence read as failure. Both are the same error — treating
"we could not ask" as an answer — and both are worse than saying so. `complete:
false` in Bone's own weakness reader exists for exactly this reason, and the
rule is written down there: *"an empty list means nothing found; complete:false
means you may not read that as nothing being wrong."*

WHAT THIS GATE DOES NOT DO: it does not check the tallies, and it cannot — they
come from a live ledger CI has no copy of. It checks that the one inference the
reader draws is guarded by whether it was able to draw it.
"""

from __future__ import annotations

import ast
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools/loop-status.py"


def test_the_reader_this_gate_describes_exists():
    """Positive control — a renamed tool makes every check below vacuous."""
    assert TOOL.is_file(), "tools/loop-status.py is gone"
    assert TOOL.stat().st_mode & 0o111, "tools/loop-status.py is not executable"


def test_unresolvable_is_only_claimed_when_the_registry_loaded():
    src = TOOL.read_text(encoding="utf-8")
    assert "resolve_error" in src, (
        "the reader no longer distinguishes 'the registry says this id is "
        "unknown' from 'the registry would not load'. With an empty live set "
        "every proposal reads as a broken lineage."
    )
    assert "resolve_error is None and wid not in live" in src, (
        "the unresolved-id test no longer requires that the registry actually "
        "loaded. A failed import would turn into a list of broken lineages "
        "that says nothing about the ledger."
    )


def test_every_query_is_a_read():
    """Same rule as `tools/red-status.py`: the ledger's design puts propose,
    judge, seal and forget on separate classes with separate capabilities. A
    reporter that could also write would collapse the split its own report
    depends on."""
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    executed = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    assert executed, "no literal SQL found — this gate has stopped seeing the queries"
    for sql in executed:
        lowered = " ".join(sql.lower().split())
        assert lowered.startswith("select"), f"not a SELECT: {sql[:70]!r}"
        for verb in ("insert ", "update ", "delete ", "drop ", "attach "):
            assert verb not in lowered, f"executed SQL contains {verb.strip()!r}"
    assert "mode=ro" in TOOL.read_text(encoding="utf-8"), (
        "the ledger connection is no longer opened read-only"
    )


def test_a_placeholder_id_is_not_bucketed_under_a_real_source():
    """`w1` has no prefix. Splitting on ':' and defaulting to a known source
    would file the residue under something plausible and hide it — the exact
    outcome entry 15 was filed for."""
    src = TOOL.read_text(encoding="utf-8")
    assert 'if ":" in weakness_id else weakness_id' in src, (
        "an id with no prefix is no longer kept as its own bucket, so "
        "placeholder residue would be absorbed into a real source's tally."
    )


def test_it_runs_and_exits_zero():
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--json"],
        capture_output=True, text=True, cwd=REPO, timeout=120,
    )
    assert proc.returncode == 0, (
        f"loop-status.py exited {proc.returncode}; it reports, it does not "
        f"judge. stderr:\n{proc.stderr[-800:]}"
    )
    report = json.loads(proc.stdout)
    # Either it resolved, or it said why. Never silently neither.
    assert "resolve_error" in report or "error" in report
