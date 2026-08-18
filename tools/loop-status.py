#!/usr/bin/env python3
"""Which weakness sources actually produce proposals, and what came of them.

WHY THIS EXISTS. `docs/hidden_fees/15` filed a lineage whose first link did not
join: `loop_proposals.weakness_id` held `w1` and `w2`, placeholders that matched
nothing in the weakness registry, so the loop's central claim — *a weakness was
detected, a proposal was raised against it, judges ruled, a verdict was sealed*
— stopped one step in. The write half closed on 2026-08-16, sideways: §4's retry
ceiling had to look the evidence sha UP rather than accept it, which made an
unresolvable `weakness_id` impossible to file. Proposals now cite `rem:REM-159`
and friends.

The half that entry named LAST is the one still open, and it is the reason for
this file:

    "Which weakness sources actually produce proposals?" is the question that
    tells you whether a detector earns its run. It is unanswerable today, so a
    source that has never once led anywhere looks exactly like one that leads
    everywhere.

Now that the ids resolve, it is answerable — but only if something reads the
join. That is this. It reports per SOURCE (the prefix of a weakness id:
`rem:`, `fee:`, `scan:`, `git:`, `corpus:`, `alert:`), because the source is the
unit a detector is judged as.

WHY A READER AND NOT A GATE. Entry 15 said it itself — "a gate belongs on the
join once real rows exist, not before" — and now that they do, a gate is still
the wrong tool for the remaining half. There is nothing to refuse: an
unresolvable id is already refused at write time by the ledger, and a source
producing no proposals is information, not a defect. Wiring that to CI would
turn a *fact about the loop's productivity* into a build failure caused by
nobody's commit. Same reasoning as `tools/rem-status.py`'s header.

WHAT IT WILL NOT DO. It does not propose, judge, seal, forget, or retry. The
ledger's whole design is that those verbs live on separate classes with separate
capabilities (`files/anatomy/bone/ledger.py`, `open_ledger(role)`); a reporter
that could also write would collapse the split its own report depends on.

Usage:
    tools/loop-status.py              # sources, proposals, verdicts
    tools/loop-status.py --unresolved # only ids that no longer join
    tools/loop-status.py --json

Exit 0 always. This reports; it does not judge.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys

WING_DB = pathlib.Path.home() / "wing" / "app" / "data" / "wing.db"

#: Weakness-id prefixes the reader emits, with what each one watches. Keep in
#: step with `files/anatomy/bone/weaknesses.py` SOURCE_ORDER — a prefix missing
#: here still counts, it just prints without its gloss.
SOURCE_GLOSS = {
    "rem": "remediation queue",
    "fee": "hidden fees",
    "scan": "security scan state",
    "git": "git working tree",
    "corpus": "cortex corpus diff",
    "alert": "prometheus alerts",
    "pulse": "pulse runs",
    "source": "a weakness source that failed to read",
}


def _connect() -> sqlite3.Connection | None:
    if not WING_DB.is_file():
        return None
    conn = sqlite3.connect(f"file:{WING_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _source_of(weakness_id: str) -> str:
    """The prefix, or the whole id when it has none.

    A bare id with no colon is what a placeholder looks like — `w1` is the
    worked example — so keeping it as its own 'source' is what makes residue
    visible rather than bucketing it under something plausible.
    """
    return weakness_id.split(":", 1)[0] if ":" in weakness_id else weakness_id


def _live_weakness_ids() -> tuple[set[str], str | None]:
    """What the reader reports RIGHT NOW, or why we could not ask.

    Imported the way the ledger imports it — lazily, and tolerantly: this tool
    must still report the ledger's contents on a host where Bone's dependencies
    are not installed. It just cannot resolve ids there, and says so instead of
    reporting every id as unresolvable.
    """
    import sys as _sys

    bone = pathlib.Path(__file__).resolve().parents[1] / "files/anatomy/bone"
    _sys.path.insert(0, str(bone))
    try:
        import weaknesses as _w  # noqa: PLC0415 — see the docstring

        return {
            w.weakness_id
            for report in _w.collect()
            for w in report.weaknesses
        }, None
    except Exception as exc:  # noqa: BLE001 — any import/read failure is the same answer
        return set(), f"{type(exc).__name__}: {exc}"
    finally:
        _sys.path.remove(str(bone))


def collect() -> dict:
    conn = _connect()
    if conn is None:
        return {"error": f"no ledger at {WING_DB}", "sources": [], "proposals": 0}

    with conn:
        proposals = [dict(r) for r in conn.execute(
            """
            SELECT p.weakness_id, p.uuid, p.intent_class, p.proposer_id,
                   p.requires_operator, p.attempt_n, p.created_at,
                   v.result AS verdict, v.created_at AS verdict_at
              FROM loop_proposals p
              LEFT JOIN loop_verdicts v ON v.proposal_id = p.id
             ORDER BY p.created_at
            """
        )]
    conn.close()

    live, resolve_error = _live_weakness_ids()

    by_source: dict[str, dict] = {}
    for row in proposals:
        wid = str(row["weakness_id"])
        src = by_source.setdefault(_source_of(wid), {
            "source": _source_of(wid),
            "gloss": SOURCE_GLOSS.get(_source_of(wid), ""),
            "proposals": 0, "weaknesses": set(),
            "pass": 0, "fail": 0, "indeterminate": 0, "unjudged": 0,
            "unresolved_ids": set(), "first": row["created_at"], "last": row["created_at"],
        })
        src["proposals"] += 1
        src["weaknesses"].add(wid)
        src["last"] = row["created_at"]
        verdict = row["verdict"]
        src[verdict if verdict in ("pass", "fail", "indeterminate") else "unjudged"] += 1
        # Only claim an id is unresolvable when we could actually ask.
        if resolve_error is None and wid not in live:
            src["unresolved_ids"].add(wid)

    for src in by_source.values():
        src["weaknesses"] = sorted(src["weaknesses"])
        src["unresolved_ids"] = sorted(src["unresolved_ids"])

    # A source the reader reports but which has NEVER produced a proposal is
    # the other half of entry 15's question, and it is invisible in the ledger
    # alone — it is an absence there.
    silent = sorted(
        {_source_of(w) for w in live} - set(by_source)
    ) if resolve_error is None else []

    return {
        "ledger": str(WING_DB),
        "proposals": len(proposals),
        "sources": sorted(by_source.values(), key=lambda s: -s["proposals"]),
        "sources_with_no_proposal": silent,
        "live_weakness_count": len(live),
        "resolve_error": resolve_error,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--unresolved", action="store_true",
                    help="only weakness ids that no longer join to a source")
    args = ap.parse_args()

    report = collect()
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True, default=list)
        sys.stdout.write("\n")
        return 0

    if report.get("error"):
        print(report["error"])
        return 0

    if args.unresolved:
        rows = [(s["source"], wid) for s in report["sources"] for wid in s["unresolved_ids"]]
        if report["resolve_error"]:
            print(f"cannot resolve — the weakness reader did not load: {report['resolve_error']}")
            print("  no id is reported as unresolvable; that would be a guess.")
            return 0
        if not rows:
            print("every weakness_id in the ledger joins to a live source")
            return 0
        print(f"{len(rows)} proposal id(s) that no source reports:")
        for src, wid in rows:
            print(f"  • {wid}  (bucketed as {src!r})")
        return 0

    print(f"{report['proposals']} proposal(s) in {report['ledger']}")
    if report["resolve_error"]:
        print(f"  weakness reader unavailable ({report['resolve_error']}) — "
              "join column omitted rather than guessed")
    for s in report["sources"]:
        gloss = f" — {s['gloss']}" if s["gloss"] else ""
        verdicts = f"{s['pass']}p/{s['fail']}f/{s['indeterminate']}i"
        if s["unjudged"]:
            verdicts += f"/{s['unjudged']}unjudged"
        unresolved = f"  UNRESOLVED×{len(s['unresolved_ids'])}" if s["unresolved_ids"] else ""
        print(f"  {s['source']:<8}{gloss:<28} {s['proposals']:>3} proposal(s), "
              f"{len(s['weaknesses']):>2} weakness(es), {verdicts}{unresolved}")
    if report["sources_with_no_proposal"]:
        print(f"\n  reporting weaknesses but never proposed against: "
              f"{', '.join(report['sources_with_no_proposal'])}")
        print("  (information, not a defect — a detector may simply be finding nothing actionable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
