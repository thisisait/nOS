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

THE EXIT HALF (`--awaiting`, added 2026-08-19). The paragraphs above are about
what enters the loop. Nothing was reading what leaves it, and the cost was
measured the day this was written:

    Two proposals passed every judge on 2026-08-16 — `rem:REM-204` (wordpress
    7.0.2 → 7.0.4) and `rem:REM-159` (gitlab 18.11.7 → 18.11.9). Three days
    later neither patch was in the tree, both queue rows still read `pending`,
    and no reader said so. `loop-status` reported "1p/7f" and "2p/0f/1i" — both
    true, and both silent about the only fact worth acting on.

Not applying is by DESIGN — docs/idea/11-agentic-loop-contract.md §7 non-goal 5
says application is an operator act or a forge MR, and nothing merges on a green
verdict. What was not designed is that the waiting had no surface. That is `docs/hidden_fees/08` one
storey up: absence reading as success. A green verdict nobody can see is
indistinguishable from no verdict at all.

AND A VERDICT DECAYS. Both verdicts were sealed against a `tree_sha` whose
`default.config.yml` has since changed. The judges ruled on a tree that no
longer exists, so applying either patch to HEAD today would be an act no judge
has blessed. `--awaiting` reports that as its own state rather than folding it
into "ready" — the whole point of the ledger is that a verdict names the tree it
covers, and a reader that drops the tree hands back the claim the ledger exists
to replace.

HOW THE STATE IS DERIVED — git decides, not a regex. Each state comes from
`git apply --check` against the working tree, forward and reversed, which is the
only oracle that cannot disagree with what would actually happen:

    landed     the reverse patch applies    → the change is in the tree
    ready      the patch applies, and no target path moved since the verdict
    re-judge   the patch applies, but a target path moved → the verdict is on
               another tree; a judge must rule on THIS one before it can land
    conflict   git parsed it and it fits neither way — the tree moved under it
    unusable   git cannot parse the patch at all (measured: proposal 074dec8a
               is a corrupt hunk the ledger accepted; it drew `indeterminate`,
               correctly, and would have been reported as a mere mismatch by any
               reader that only asked "does it apply?")
    no-diff    the row carries no patch (the 2026-08-02 fixtures)

Usage:
    tools/loop-status.py              # sources, proposals, verdicts
    tools/loop-status.py --unresolved # only ids that no longer join
    tools/loop-status.py --gap        # weaknesses nobody has proposed against
    tools/loop-status.py --awaiting   # passed verdicts and what became of them
    tools/loop-status.py --json

Exit 0 always. This reports; it does not judge.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import subprocess
import sys

WING_DB = pathlib.Path.home() / "wing" / "app" / "data" / "wing.db"
REPO = pathlib.Path(__file__).resolve().parents[1]

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


def live_weaknesses() -> tuple[list[dict], str | None]:
    """Every weakness reported RIGHT NOW, with what it says about itself.

    THE GAP THIS EXISTS TO SHOW. Measured 2026-08-18: seven sources report 67
    weaknesses; `loop_proposals` holds three rows, all against `rem:`. So the
    loop has a reader, a ledger, judges and a verdict chain — and NO STEP THAT
    TURNS A REPORTED WEAKNESS INTO A PROPOSAL. The three real proposals were
    filed by agents that happened to be pointed at remediation work
    (`proposer_id` reads `agent:claude-opus-5`, `agent:librarian`); nothing
    walks the list.

    That missing step is `loop-driver` on the roadmap and it is not built. Until
    it is, the cheapest honest thing is to make the gap COUNTABLE and NAMED,
    because "six detectors are silent" is a shrug and "here are the 64 findings
    nobody has proposed against, worst first" is a queue.
    """
    import sys as _sys

    bone = pathlib.Path(__file__).resolve().parents[1] / "files/anatomy/bone"
    _sys.path.insert(0, str(bone))
    try:
        import weaknesses as _w  # noqa: PLC0415

        out = []
        for report in _w.collect():
            for weakness in report.weaknesses:
                out.append({
                    "id": weakness.weakness_id,
                    "source": report.name,
                    "severity": str(getattr(weakness, "severity", "") or "").lower(),
                    "title": str(getattr(weakness, "title", "") or "")[:96],
                })
        return out, None
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"
    finally:
        _sys.path.remove(str(bone))


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


def _git(*argv: str, stdin: str | None = None) -> tuple[int, str]:
    """Run git in the repo and hand back (rc, stderr). Never raises.

    A reader that dies on a host without git would report nothing where it
    should report UNKNOWN, so every failure path here funnels into a returncode
    the caller can classify.
    """
    try:
        done = subprocess.run(  # noqa: S603 — fixed argv, no shell
            ["git", *argv], cwd=REPO, input=stdin, text=True,
            capture_output=True, check=False,
        )
    except OSError as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return done.returncode, done.stderr.strip()


def _apply_state(diff_text: str) -> tuple[str, str]:
    """Ask git whether this patch is in the tree, fits it, or neither.

    Returns (state, detail). The two probes are deliberately BOTH run: a patch
    that neither applies nor reverse-applies is a conflict, and one that git
    refuses to parse (rc 128) is a different defect with a different owner —
    the proposer wrote something malformed, not something stale.
    """
    fwd_rc, fwd_err = _git("apply", "--check", "-", stdin=diff_text)
    if fwd_rc == 127:
        return "unknown", fwd_err
    rev_rc, _ = _git("apply", "--check", "-R", "-", stdin=diff_text)
    if rev_rc == 0:
        return "landed", ""
    if fwd_rc == 0:
        return "applies", ""
    if fwd_rc >= 128:
        return "unusable", fwd_err.splitlines()[0] if fwd_err else "git could not parse the patch"
    return "conflict", fwd_err.splitlines()[0] if fwd_err else ""


def _paths_moved_since(tree_sha: str | None, paths: list[str]) -> tuple[list[str], str | None]:
    """Which target paths changed between the judged tree and HEAD.

    This is what makes a verdict transferable or not. `git diff --quiet A HEAD --
    <path>` exits 1 when the path differs; anything else (an unknown sha, a
    detached object) is reported as an inability to ask rather than as "no
    drift", because a silent "no drift" is how a stale verdict would read as
    fresh.
    """
    if not tree_sha:
        return [], "the proposal records no tree_sha"
    rc, err = _git("cat-file", "-e", f"{tree_sha}^{{commit}}")
    if rc != 0:
        return [], f"the judged tree {tree_sha[:8]} is not in this clone"
    moved = []
    for path in paths:
        rc, err = _git("diff", "--quiet", tree_sha, "HEAD", "--", path)
        if rc == 1:
            moved.append(path)
        elif rc != 0:
            return [], f"cannot compare {path}: {err or f'git exited {rc}'}"
    return moved, None


def _dirty(paths: list[str]) -> list[str]:
    """Target paths with uncommitted edits — the apply probe ran against these."""
    rc, _ = _git("rev-parse", "--git-dir")
    if rc != 0:
        return []
    out = []
    for path in paths:
        rc, _ = _git("diff", "--quiet", "--", path)
        if rc == 1:
            out.append(path)
    return out


def awaiting() -> dict:
    """Every proposal a judge passed, and what became of it.

    Only `pass` rows. A failed proposal waiting for nothing is not a queue, and
    an `indeterminate` one is the loop correctly declining to answer — neither
    is an item on anybody's desk. A passed one that has not landed IS.
    """
    conn = _connect()
    if conn is None:
        return {"error": f"no ledger at {WING_DB}", "rows": []}

    with conn:
        rows = [dict(r) for r in conn.execute(
            """
            SELECT p.uuid, p.weakness_id, p.intent_class, p.proposer_id,
                   p.target_paths, p.tree_sha, p.diff_text,
                   v.result AS verdict, v.created_at AS verdict_at
              FROM loop_proposals p
              JOIN loop_verdicts v ON v.proposal_id = p.id
             WHERE v.result = 'pass'
             ORDER BY v.created_at
            """
        )]
        # A verdict can be sealed with no proposal attached — `POST /loop/judge`
        # takes an optional `proposal_uuid`, so a bare gate-set run against the
        # working tree seals a real row with `proposal_id IS NULL`. The JOIN
        # above drops those, which is right (there is no patch to apply) and
        # would be dishonest to leave uncounted: a header reading "4 passed"
        # when the chain holds 6 is the same shape of quiet arithmetic this
        # whole file exists to complain about.
        bare = conn.execute(
            "SELECT COUNT(*) FROM loop_verdicts "
            " WHERE result = 'pass' AND proposal_id IS NULL"
        ).fetchone()[0]
    conn.close()

    out = []
    for row in rows:
        try:
            paths = json.loads(row["target_paths"] or "[]")
        except (TypeError, ValueError):
            paths = []
        diff = row["diff_text"]
        if not diff:
            state, detail = "no-diff", "the ledger row carries no patch"
            moved, drift_error = [], None
        else:
            state, detail = _apply_state(diff)
            moved, drift_error = _paths_moved_since(row["tree_sha"], paths)
            # Only a patch that still applies can be described as ready or not;
            # for the other states the drift is not the operative fact.
            if state == "applies":
                if drift_error:
                    state = "re-judge"
                    detail = drift_error
                elif moved:
                    state = "re-judge"
                    detail = f"{', '.join(moved)} changed since the judged tree"
                else:
                    state = "ready"
        out.append({
            "uuid": row["uuid"],
            "weakness_id": row["weakness_id"],
            "intent_class": row["intent_class"],
            "proposer_id": row["proposer_id"],
            "verdict_at": row["verdict_at"],
            "tree_sha": row["tree_sha"],
            "target_paths": paths,
            "state": state,
            "detail": detail,
            "moved_paths": moved,
            "dirty_paths": _dirty(paths),
        })

    head_rc, _ = _git("rev-parse", "HEAD")
    return {
        "rows": out,
        "head": None if head_rc != 0 else _git_head(),
        "unlanded": [r for r in out if r["state"] in ("ready", "re-judge")],
        "passed_without_proposal": bare,
    }


def _git_head() -> str | None:
    try:
        done = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True,
            capture_output=True, check=False,
        )
    except OSError:
        return None
    return done.stdout.strip() or None


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


#: What each state means for the reader, in the words they need to act on. The
#: order is the order to act in — a ready patch is a minute's work, a conflicted
#: one is a re-proposal.
STATE_GLOSS = {
    "ready": "applies to HEAD, and no target path moved since the judges ruled",
    "re-judge": "still applies, but the judged tree is gone — no judge has ruled on THIS one",
    "conflict": "the tree moved under the patch; it fits neither forward nor reversed",
    "unusable": "git cannot parse the patch — the proposer wrote it malformed",
    "landed": "the change is in the tree",
    "no-diff": "the ledger row carries no patch",
    "unknown": "could not ask git, so this is UNKNOWN and not 'landed'",
}
_STATE_ORDER = ["ready", "re-judge", "conflict", "unusable", "unknown", "no-diff", "landed"]


def _print_awaiting(report: dict, *, as_json: bool) -> int:
    if as_json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True, default=str)
        sys.stdout.write("\n")
        return 0

    if report.get("error"):
        print(report["error"])
        return 0

    rows = report["rows"]
    if not rows:
        print("no proposal has ever been passed by the judges")
        return 0

    pending = report["unlanded"]
    print(f"{len(rows)} passed verdict(s) against a proposal; "
          f"{len(pending)} have not reached the tree")
    bare = report.get("passed_without_proposal") or 0
    if bare:
        print(f"  (+{bare} passed with no proposal attached — bare gate-set runs, "
              f"nothing to apply)")
    if report.get("head"):
        print(f"  measured against HEAD {report['head'][:8]} by `git apply --check`\n")

    rows = sorted(rows, key=lambda r: (_STATE_ORDER.index(r["state"])
                                       if r["state"] in _STATE_ORDER else 99,
                                       str(r["verdict_at"])))
    for row in rows:
        print(f"  {row['state']:<9} {row['weakness_id']:<20} {row['uuid'][:8]}  "
              f"{row['intent_class']}  by {row['proposer_id']}")
        gloss = STATE_GLOSS.get(row["state"], "")
        print(f"      {gloss}")
        if row["detail"] and row["detail"] != gloss:
            print(f"      {row['detail']}")
        if row["dirty_paths"]:
            print(f"      NOTE uncommitted edits in {', '.join(row['dirty_paths'])} — "
                  f"the probe ran against the tree as it stands")
    if pending:
        print("\n  Nothing lands on a green verdict by design: application is an"
              "\n  operator act or a forge MR. This is the list that act works "
              "from."
              "\n  (docs/idea/11-agentic-loop-contract.md §7 non-goal 5)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--unresolved", action="store_true",
                    help="only weakness ids that no longer join to a source")
    ap.add_argument("--gap", action="store_true",
                    help="reported weaknesses that no proposal has ever cited")
    ap.add_argument("--awaiting", action="store_true",
                    help="passed verdicts and whether the patch reached the tree")
    args = ap.parse_args()

    if args.awaiting:
        return _print_awaiting(awaiting(), as_json=args.json)

    report = collect()

    if args.gap:
        live, err = live_weaknesses()
        if err:
            print(f"cannot list weaknesses — the reader did not load: {err}")
            print("  no gap is reported; an empty list here would be a guess.")
            return 0
        proposed = {w for s in report.get("sources", []) for w in s["weaknesses"]}
        gap = [w for w in live if w["id"] not in proposed]
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        gap.sort(key=lambda w: (order.get(w["severity"], 9), w["id"]))

        if args.json:
            json.dump({"reported": len(live), "proposed_against": len(live) - len(gap),
                       "gap": gap}, sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
            return 0

        print(f"{len(gap)} of {len(live)} reported weaknesses have never been "
              f"proposed against")
        print("  (there is no step that turns a finding into a proposal — "
              "`loop-driver` is not built. This is the queue it would read.)\n")
        for w in gap[:25]:
            sev = (w["severity"] or "-")[:8]
            print(f"  {sev:<9} {w['id']:<34} {w['title'][:58]}")
        if len(gap) > 25:
            print(f"\n  … and {len(gap) - 25} more")
        return 0

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
