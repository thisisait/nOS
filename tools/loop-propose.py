#!/usr/bin/env python3
"""The loop's ENTRY: hand one reported weakness to a model that may propose.

WHY THIS EXISTS. Measured 2026-08-19, the evening the operator asked "does any
loop drive development, or must I keep pushing it from a chat session?": zero
Pulse jobs referenced the loop, every real proposal had been filed by a human
or a model someone was TYPING AT, and `tools/loop-status.py --gap` reported 63
of 66 reported weaknesses never proposed against. The loop had a reader, a
ledger, judges, a driver and a reviewer — and no step that turns a weakness
into a proposal, because authoring a patch needs a model and nothing invoked
one.

WHAT IT DOES. Picks the worst weakness that (a) no proposal has ever cited,
(b) the ledger will accept (evidence committed — see the deadlock below), and
(c) belongs to a source whose fix surface the budget permits. Then it opens ONE
AgentKit session for exactly that weakness — `tools/run-agent.sh`, i.e.
`bin/run-agent.php` with the daemon's environment, the agent's own principals
and ONE slot of the Q12 agent lock (kind `agentkit`, so three may run abreast
and a claude-CLI run still meets nobody) — and reads back, from the ledger,
read-only, whether a proposal now cites it AND names that session.

WHY AGENTKIT AND NOT `claude --print` (2026-08-29). The old spawn was
`claude --print --permission-mode bypassPermissions`: an unattended run with
the operator's own session, the operator's identity in every event it wrote,
no session row, no token tally, no ceiling, and no binding — so the loop's
entry was the one step of the loop with no record of its own cost. The
proposal it produced named no author. It now runs on the ANTHROPIC adapter,
which is the only adapter that keeps tools through a binding
(state/llm-backends.yml:26-28), because a proposer with no tools cannot read
the budget it must stay inside.

WHAT IT DELIBERATELY IS NOT

  * **Not the evaluator.** This runner holds no judge scope, never reads
    `loop_judge_token`, and never triggers judgment. The proposer proposes and
    stops (docs/idea/11-agentic-loop-contract.md §3.4); the driver — `tools/loop-pr.py`, a distinct process
    with a distinct token — judges and lands. One process holding both halves
    is the loop grading its own homework.
  * **Not a recorder of its own success.** It writes nothing anywhere. Whether
    a proposal exists is the LEDGER's answer, written by the engine when the
    model's POST arrived, and read back here through a read-only connection.
  * **Not a scheduler.** Pulse owns cadence. The `loop:propose` Pulse job
    (files/anatomy/plugins/loop-base/plugin.yml) ships PAUSED, because the
    contract's §10 step 6 bar — "only after enough attended cycles to trust
    the above" — is cleared for the judged half of the loop and NOT for this
    half: as of 2026-08-19 no model-authored proposal has ever been produced
    by this path. Run it attended until that stops being true.

THE COMMITTED-EVIDENCE DEADLOCK, surfaced and refused here. The ledger only
accepts weaknesses whose evidence file matches HEAD (an uncommitted edit is a
retry-ceiling lift key the proposer could write for itself). The nightly scan
writes `docs/llm/security/*` and nobody commits it, so the proposable set
periodically collapses to `fee:` rows — which close only by writing `docs/**`,
a path every gate set's budget forbids. When that happens this runner REFUSES
(exit 3) and names the commit that unblocks, rather than spending a model run
on a proposal the engine must reject.

DRY RUN BY DEFAULT (operator doctrine):

    tools/loop-propose.py               # name the weakness it would hand over
    tools/loop-propose.py --invoke      # spawn the model for it
    tools/loop-propose.py --weakness rem:REM-155 --invoke   # exactly this one

Exit codes (fixed enum, DECISION 6a's shape): 0 a proposal now cites the
weakness (or dry run printed); 1 the model ran and no proposal appeared;
2 environment/config; 3 refused — nothing proposable, reason printed.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import pathlib
import sqlite3
import subprocess
import sys
import uuid as _uuid

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import _ledger_open  # noqa: E402 — after REPO is known

#: Sources whose findings the budget gives the loop no way to FIX: a `fee:`
#: closes only by writing docs/**, forbidden in every gate set (docs/idea/11-agentic-loop-contract.md §5.2). Handing
#: one to the proposer buys a model run and a guaranteed refusal.
UNFIXABLE_SOURCES = {
    "fee": "closes only by writing docs/**, which every gate set's budget forbids",
}

#: The AgentKit entry point, and the reason there is no mutex in this file any
#: more: run-agent.sh sources files/anatomy/scripts/agent-run-lock.sh and takes
#: ONE slot as kind `agentkit`. The Python reimplementation that used to live
#: here still did `mkdir` on the lock's PARENT directory — the N=1 contract
#: from before Q12 — so it and the shell holder could not see each other's
#: claims. Two locks with one invariant is the estate's signature defect; this
#: is now one implementation with two callers, which is the same rule.
RUNNER = pathlib.Path(os.environ.get(
    "NOS_LOOP_AGENT_RUNNER", str(REPO / "tools" / "run-agent.sh")))

#: The agent whose profile the session runs under. Configurable because this
#: runner must not hard-code a roster the roster owns.
PROPOSER_AGENT = os.environ.get("NOS_LOOP_PROPOSER_AGENT", "proposer")


def wing_db() -> pathlib.Path:
    """Resolved per call, from the SAME env the ledger reads. It used to be a
    module constant on the hard-coded home path, so a test (or a second estate)
    pointed the ledger at one database and read back from another."""
    return pathlib.Path(os.environ.get(
        "WING_DB_PATH", str(pathlib.Path.home() / "wing" / "app" / "data" / "wing.db")))


class Refused(Exception):
    """A condition this runner will not spend a model run on."""


class Unreadable(Exception):
    """The ledger could not be read, which is not the same as it being empty.

    Kept distinct from Refused on purpose: a refusal is a decision this runner
    made, and this is the absence of an answer. Collapsing them would put
    "I could not look" and "I looked and there was nothing" behind one exit
    code, which is the confusion that produced this class.
    """


def _load_status():
    spec = importlib.util.spec_from_file_location(
        "_loop_status_entry", REPO / "tools" / "loop-status.py")
    if spec is None or spec.loader is None:
        raise Refused("cannot load tools/loop-status.py — the state reader is missing")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pick(status_mod, wanted: str | None) -> dict:
    """The worst proposable, fixable, never-proposed weakness — or Refused
    with the exact reason the queue is empty, because an empty queue has
    three different owners and only one of them is 'nothing to do'."""
    live, err = status_mod.live_weaknesses()
    if err:
        raise Refused(f"the weakness reader did not load: {err}")

    report = status_mod.collect()
    proposed = {w for s in report.get("sources", []) for w in s["weaknesses"]}
    # AWAITING — attempted, and no proposal has passed. Computed by the status
    # reader (`awaiting_ids`), not re-derived here: a second opinion about what
    # the ledger already knows is how two layers come to disagree.
    #
    # NOT `unresolved_ids`, which the first draft of this reached for and which
    # means something else entirely — an id that no longer JOINS a live source,
    # i.e. dangling lineage. It excluded REM-212 precisely because that
    # weakness is still live, which is the opposite of the question here.
    awaiting = {w for s in report.get("sources", [])
                for w in (s.get("awaiting_ids") or [])}

    # A WEAKNESS WHOSE ONLY PROPOSAL WAS NEVER JUDGEABLE IS NOT DONE WITH.
    #
    # MEASURED 2026-08-31, and it is the last link in that morning's chain. The
    # loop proposed against rem:REM-212 (a CRITICAL), the diff was malformed,
    # every judge in the set refused it, and the verdict came back
    # `indeterminate`. Asking for it again then produced:
    #
    #     refused: 'rem:REM-212' is not an un-proposed reported weakness
    #
    # So the CRITICAL was permanently out of the loop's reach — not because it
    # was fixed, judged, or refused on its merits, but because a single
    # unusable artifact had been written against it once.
    #
    # The LEDGER already models retries and holds the rules for them:
    # `already-failed` (attempts exhausted with a failing verdict),
    # `content-fp-repeat` (the byte-identical patch re-offered),
    # `passed-awaiting-act` (a pass is waiting on a merge, not on another
    # proposal). Those are exactly the cases that must not be retried, and each
    # is decided where the evidence is. This picker was applying a cruder rule
    # in front of them — "proposed once, ever" — which the ledger's own retry
    # ceiling then had no way to be reached.
    #
    # Fresh weaknesses still come FIRST; unresolved ones are the fallback, so
    # an ordinary night is unchanged and only a queue with nothing new reaches
    # back for something that stalled.
    fresh = [w for w in live if w["id"] not in proposed]
    retryable = [w for w in live if w["id"] in awaiting]
    gap = fresh or retryable
    if wanted:
        # An explicit ask is a deliberate act: honour it for anything the
        # engine may still accept, and let the ledger refuse if it may not.
        gap = [w for w in (fresh + retryable) if w["id"] == wanted]
        if not gap:
            settled = wanted in proposed and wanted not in awaiting
            raise Refused(
                f"{wanted!r} is "
                + ("already resolved by a proposal — the loop is waiting on an "
                   "act outside it (merge, converge, rescan), not on another "
                   "proposal" if settled
                   else "not reported by any weakness source")
            )

    withheld = [w for w in gap if not w.get("proposable", True)]
    candidates = [w for w in gap
                  if w.get("proposable", True)
                  and status_mod._source_of(w["id"]) not in UNFIXABLE_SOURCES]
    if not candidates:
        if not gap:
            raise Refused("no reported weakness lacks a proposal — nothing to do")
        parts = []
        commit_held = [w for w in withheld if w.get("commit_unblocks", True)]
        live_held = [w for w in withheld if not w.get("commit_unblocks", True)]
        if commit_held:
            parts.append(
                f"{len(commit_held)} weakness(es) are WITHHELD — their evidence "
                f"file does not match HEAD. Commit it (`git status "
                f"docs/llm/security/` is the usual culprit) to unblock")
        if live_held:
            parts.append(
                f"{len(live_held)} carry live evidence no commit can satisfy "
                f"(alerts, pulse runs) — they clear when their source clears")
        rest = [w for w in gap if w.get("proposable", True)]
        if rest:
            srcs = sorted({status_mod._source_of(w["id"]) for w in rest})
            parts.append(
                f"the only proposable sources are {srcs} — "
                + "; ".join(UNFIXABLE_SOURCES[s] for s in srcs if s in UNFIXABLE_SOURCES))
        prefix = ("the committed-evidence deadlock: " if commit_held
                  else "nothing proposable is also fixable: ")
        raise Refused(prefix + ". ".join(parts))

    # THE VENDOR-BLOCKED SOFT FILTER IS GONE (2026-08-31), and deleting it is
    # the fix rather than a simplification of it.
    #
    # It read `"vendor_blocked" not in w["title"]` — a substring match on a
    # RENDERED SENTENCE, where the queue has a structured `status` field that
    # already says this. `_source_remediation` only emits rows whose status is
    # `pending`, and `vendor-blocked` is a DIFFERENT status (5 rows carry it
    # today), so every weakness reaching this function has already been gated
    # on exactly the property the filter re-derived.
    #
    # What it actually did, measured the morning it was removed: `REM-212`
    # (portainer) was filed as `remediation_type: vendor_blocked` back when no
    # fixed release existed. On 2026-08-27 upstream shipped 2.45.0; the scan
    # moved the row's STATUS to `pending` and confirmed the tag on Docker Hub,
    # and left the TYPE label alone — it describes how the row was filed, not
    # what is true now. So the one live effect of this filter was to
    # deprioritise the queue's only actionable CRITICAL behind a `high`,
    # because a stale label appeared inside a string.
    #
    # Reading `evidence["remediation_type"]` instead would keep the same bug
    # with better manners: the field is stale too. The status is the fact.

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    candidates.sort(key=lambda w: (order.get(w["severity"], 9), w["id"]))
    return candidates[0]


# ── the model run ────────────────────────────────────────────────────────────

def _task_prompt(weakness: dict, session_uuid: str) -> str:
    return (
        f"You are the nOS loop's PROPOSER, invoked unattended.\n"
        f"Work in the repository at {REPO}.\n\n"
        f"1. Read .claude/plugins/nos-loop/ENGINE.md — it holds the engine's "
        f"address and your token. You are the proposer; you hold "
        f"loop_propose_token and nothing else.\n"
        f"2. Follow .claude/plugins/nos-loop/skills/propose/SKILL.md for the "
        f"weakness `{weakness['id']}` ({weakness['severity']}: "
        f"{weakness['title']}). Read the budget first; author ONE bounded "
        f"patch inside it; record the proposal BEFORE editing anything.\n"
        f"3. Your POST to /loop/proposals MUST carry "
        f"\"session_uuid\": \"{session_uuid}\" — this session. A proposal that "
        f"names no session cannot be traced to what it cost.\n"
        f"4. Obey every refusal the engine returns — quote it and stop.\n"
        f"5. Do NOT judge, do NOT run nos-loop judge, do NOT commit, push, or "
        f"open a merge request. The driver holds that identity, not you.\n"
        f"6. When the proposal is recorded (201), report its uuid and stop."
    )


def _proposals_citing(weakness_id: str) -> list[dict]:
    """Every proposal row citing this weakness — id and the session it names.

    Read-only, and read from the LEDGER: what the model says it did is a claim,
    a row is a fact (the module header's own rule).
    """
    # THE SHARED OPENER, not a hand-rolled one (2026-08-31).
    #
    # This function used to call `sqlite3.connect(mode=ro)` itself and swallow
    # OperationalError into `[]`. `tools/_ledger_open.py` has existed since
    # 2026-08-20 for precisely this: wing.db is WAL, a `mode=ro` connection may
    # not create the `-shm` a WAL reader needs, and Wing does not hold the
    # database open between requests — so every quiet minute makes every
    # hand-rolled read-only open fail. Its docstring says it plainly: "not
    # intermittent; conditional, on a condition nobody controls."
    #
    # Measured that morning, this was not theory: the readback reported "the
    # run bought nothing" for a proposal that was on record, and `loop-pr.py`
    # (which also hand-rolls it) still dies on the same line with a traceback.
    conn, how = _ledger_open.open_ledger_ro(wing_db())
    if conn is None:
        raise Unreadable(how)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, uuid, session_uuid FROM loop_proposals "
            "WHERE weakness_id = ? ORDER BY id", (weakness_id,))]
    except sqlite3.OperationalError as exc:
        # A LEDGER THAT DOES NOT EXIST YET HOLDS NO PROPOSALS — a fresh estate
        # has no loop_* tables until Bone creates them, pinned by
        # test_a_run_that_proposed_nothing_is_not_success. Anything else (a
        # missing column, a damaged file) is drift the caller must not read as
        # emptiness.
        if "no such table" in str(exc):
            return []
        raise Unreadable(f"the ledger could not be read: {exc}") from exc
    finally:
        conn.close()


def runner_argv(weakness: dict, session_uuid: str) -> list[str]:
    """The spawn, as data, so a gate can read what would be run."""
    return [str(RUNNER), f"--agent={PROPOSER_AGENT}",
            f"--session-uuid={session_uuid}", "--trigger=pulse",
            f"--prompt={_task_prompt(weakness, session_uuid)}"]


def invoke(weakness: dict, log) -> int:
    if not RUNNER.is_file():
        raise Refused(f"the AgentKit runner {RUNNER} does not exist — the "
                      f"proposer runs through it, not through `claude`")
    # If this one cannot be read, the run has not started and refusing costs
    # nothing — unlike the readback above, where the model has already been paid.
    try:
        before = {p["id"] for p in _proposals_citing(weakness["id"])}
    except Unreadable as exc:
        raise Refused(f"cannot establish what the ledger already holds: {exc}") from exc
    session_uuid = str(_uuid.uuid4())
    argv = runner_argv(weakness, session_uuid)

    # No lock taken here: run-agent.sh acquires one `agentkit` slot of the Q12
    # lock and releases it on EXIT. Taking a second one around it would deadlock
    # against the CLI kind, which claims all three.
    log(f"opening an AgentKit session {session_uuid} on agent "
        f"{PROPOSER_AGENT!r} for {weakness['id']}")
    done = subprocess.run(  # noqa: S603 — fixed argv, no shell
        argv, cwd=str(REPO), text=True, capture_output=True, check=False)

    for line in (done.stdout or "").strip().splitlines()[-6:]:
        log(f"  | {line}")

    try:
        after = _proposals_citing(weakness["id"])
    except Unreadable as exc:
        # The run may well have proposed. Saying so is the honest report, and
        # exit 2 (environment) rather than 1 (the model bought nothing) keeps
        # the two apart for whatever reads this next.
        log(f"the model ran, and the ledger cannot be read to say what it "
            f"produced: {exc}. This is NOT 'no proposal' — check with "
            f"tools/loop-status.py before retrying, or a second run will pay "
            f"for the same work twice.")
        return 2
    new = [p for p in after if p["id"] not in before]
    if not new:
        log(f"no proposal citing {weakness['id']} appeared in the ledger "
            f"(runner exit {done.returncode}) — the run bought nothing; "
            f"read tools/loop-status.py --gap before retrying")
        return 1
    orphans = [p["uuid"] for p in new if p["session_uuid"] != session_uuid]
    if orphans:
        # A proposal that arrived without its session is not a success: the
        # cost of the run it came from is unattributable, which is the exact
        # defect this path was rewritten to close.
        log(f"{len(orphans)} new proposal(s) name no session (or the wrong "
            f"one): {', '.join(orphans)} — expected {session_uuid}")
        return 1
    log(f"the ledger now holds {len(new)} new proposal(s) citing "
        f"{weakness['id']}, all naming session {session_uuid} — next: "
        f"tools/loop-pr.py (the driver judges and lands)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--invoke", action="store_true",
                    help="act; without it this names the candidate and stops")
    ap.add_argument("--weakness", help="propose against exactly this weakness id")
    args = ap.parse_args()

    def log(line: str) -> None:
        print(line, flush=True)

    try:
        status_mod = _load_status()
        weakness = pick(status_mod, args.weakness)
        log(f"candidate: {weakness['id']} ({weakness['severity']}) — {weakness['title']}")
        if not args.invoke:
            log("DRY RUN — no model was invoked. Re-run with --invoke to act.")
            return 0
        return invoke(weakness, log)
    except Refused as exc:
        print(f"[loop-propose] refused: {exc}", file=sys.stderr)
        return 3
    except OSError as exc:
        print(f"[loop-propose] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
