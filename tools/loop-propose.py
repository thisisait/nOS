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
(c) belongs to a source whose fix surface the budget permits. Then it spawns
ONE `claude` run pointed at the nos-loop `propose` skill for exactly that
weakness, serialised through the estate's one agent mutex, and reads back —
from the ledger, read-only — whether a proposal now cites it.

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

REPO = pathlib.Path(__file__).resolve().parents[1]

#: Sources whose findings the budget gives the loop no way to FIX: a `fee:`
#: closes only by writing docs/**, forbidden in every gate set (docs/idea/11-agentic-loop-contract.md §5.2). Handing
#: one to the proposer buys a model run and a guaranteed refusal.
UNFIXABLE_SOURCES = {
    "fee": "closes only by writing docs/**, which every gate set's budget forbids",
}

#: The one mutex every claude-CLI spawn on this host goes through — same path
#: as files/anatomy/scripts/agent-run-lock.sh, because two locks with one
#: invariant is the estate's signature defect (that file's own header).
LOCK_DIR = pathlib.Path(os.environ.get("NOS_AGENT_LOCK_DIR",
                                       str(pathlib.Path.home() / ".nos" / "agent-run.lock")))

WING_DB = pathlib.Path.home() / "wing" / "app" / "data" / "wing.db"


class Refused(Exception):
    """A condition this runner will not spend a model run on."""


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

    gap = [w for w in live if w["id"] not in proposed]
    if wanted:
        gap = [w for w in gap if w["id"] == wanted]
        if not gap:
            raise Refused(f"{wanted!r} is not an un-proposed reported weakness "
                          f"(already proposed against, or not reported)")

    withheld = [w for w in gap if not w.get("proposable", True)]
    candidates = [w for w in gap
                  if w.get("proposable", True)
                  and status_mod._source_of(w["id"]) not in UNFIXABLE_SOURCES]
    if not candidates:
        if not gap:
            raise Refused("no reported weakness lacks a proposal — nothing to do")
        parts = []
        if withheld:
            parts.append(
                f"{len(withheld)} weakness(es) are WITHHELD — their evidence "
                f"file does not match HEAD. Commit it (`git status "
                f"docs/llm/security/` is the usual culprit) to unblock")
        rest = [w for w in gap if w.get("proposable", True)]
        if rest:
            srcs = sorted({status_mod._source_of(w["id"]) for w in rest})
            parts.append(
                f"the only proposable sources are {srcs} — "
                + "; ".join(UNFIXABLE_SOURCES[s] for s in srcs if s in UNFIXABLE_SOURCES))
        prefix = ("the committed-evidence deadlock: " if withheld
                  else "nothing proposable is also fixable: ")
        raise Refused(prefix + ". ".join(parts))

    # A vendor_blocked row has no upstream fix to propose (CLAUDE.md names
    # FreePBX + Ollama as accepted-risk for exactly this reason) — a model run
    # against one buys a well-written refusal. Soft filter: deprioritised,
    # not hidden, so an all-blocked queue still surfaces its worst row.
    actionable = [w for w in candidates if "vendor_blocked" not in w["title"]]
    if actionable:
        candidates = actionable

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    candidates.sort(key=lambda w: (order.get(w["severity"], 9), w["id"]))
    return candidates[0]


# ── the mutex ────────────────────────────────────────────────────────────────

def _acquire_lock() -> None:
    """Atomic mkdir, PID-liveness reclaim — the agent-run-lock.sh contract in
    Python, on the same path, so both callers demonstrably share one law."""
    LOCK_DIR.parent.mkdir(parents=True, exist_ok=True)
    try:
        LOCK_DIR.mkdir()
    except FileExistsError:
        owner = LOCK_DIR / "owner"
        try:
            pid = int(owner.read_text().split()[0])
            os.kill(pid, 0)
            raise Refused(f"another agent run holds {LOCK_DIR} (pid {pid}) — "
                          f"refusing to run two claude agents at once") from None
        except (OSError, ValueError, IndexError):
            # Stale: the recorded owner is dead or unreadable. Reclaim.
            try:
                owner.unlink(missing_ok=True)
                LOCK_DIR.rmdir()
                LOCK_DIR.mkdir()
            except OSError as exc:
                raise Refused(f"could not reclaim stale lock {LOCK_DIR}: {exc}") from None
    (LOCK_DIR / "owner").write_text(f"{os.getpid()} loop-propose\n", encoding="utf-8")


def _release_lock() -> None:
    try:
        (LOCK_DIR / "owner").unlink(missing_ok=True)
        LOCK_DIR.rmdir()
    except OSError:
        pass


# ── the model run ────────────────────────────────────────────────────────────

def _task_prompt(weakness: dict) -> str:
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
        f"3. Obey every refusal the engine returns — quote it and stop.\n"
        f"4. Do NOT judge, do NOT run nos-loop judge, do NOT commit, push, or "
        f"open a merge request. The driver holds that identity, not you.\n"
        f"5. When the proposal is recorded (201), report its uuid and stop."
    )


def _proposals_citing(weakness_id: str) -> int:
    if not WING_DB.is_file():
        return 0
    conn = sqlite3.connect(f"file:{WING_DB}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM loop_proposals WHERE weakness_id = ?",
            (weakness_id,)).fetchone()[0]
    finally:
        conn.close()


def invoke(weakness: dict, log) -> int:
    before = _proposals_citing(weakness["id"])
    model = os.environ.get("NOS_AGENT_MODEL", "opus")
    argv = ["claude", "--print", "--permission-mode", "bypassPermissions",
            "--model", model, _task_prompt(weakness)]

    _acquire_lock()
    try:
        log(f"invoking claude ({model}) for {weakness['id']} — serialised on {LOCK_DIR}")
        done = subprocess.run(  # noqa: S603 — fixed argv, no shell
            argv, cwd=str(REPO), text=True, capture_output=True, check=False)
    finally:
        _release_lock()

    tail = (done.stdout or "").strip().splitlines()[-6:]
    for line in tail:
        log(f"  | {line}")

    # NOT self-reported: the ledger is the engine's record of what arrived,
    # read back read-only. The model saying "done" is a claim; a row is a fact.
    after = _proposals_citing(weakness["id"])
    if after > before:
        log(f"the ledger now holds {after - before} new proposal(s) citing "
            f"{weakness['id']} — next: tools/loop-pr.py (the driver judges and lands)")
        return 0
    log(f"no proposal citing {weakness['id']} appeared in the ledger "
        f"(claude exit {done.returncode}) — the run bought nothing; "
        f"read tools/loop-status.py --gap before retrying")
    return 1


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
