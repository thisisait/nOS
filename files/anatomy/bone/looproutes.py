"""HTTP surface for the loop engine's judge, ledger and budget.

The three modules beside this one were built and tested as pure Python and had
no way to be called. This file is the wire, and deliberately nothing else: every
decision lives in `judges.py` / `ledger.py` / `budget.py`, so a route can be read
in full without learning what a verdict means.

WHAT IS NOT HERE, ON PURPOSE
----------------------------
`POST /api/v1/loop/verdicts` does not exist and will not. Contract §3.1: the
guarantee is not that a verdict-writing endpoint checks who is calling — it is
that **there is no endpoint that accepts a verdict**. A `CHECK` on an actor
column is a lock whose key is a header; removing the input surface removes the
class. A verdict is produced by `seal_verdict`, from judge runs the caller did
not select, or it is not produced at all.

ROLES, NOT ROUTES, ARE THE BOUNDARY
-----------------------------------
`agent:proposer` holds `read`+`propose`; `engine:evaluator` holds `read`+`judge`.
They are separate tokens, minted random (never prefix-derived), and the ledger
opens under the caller's role — so a proposer's connection physically cannot
write to `loop_verdicts`. Constraint A is enforced twice: once by scope here,
once by the SQLite authorizer there.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import budget
import judges
import ledger
from loopauth import require_loop_scope

router = APIRouter(prefix="/api/v1/loop", tags=["loop"])


# ── In-flight judge runs ────────────────────────────────────────────────────
# A gate set can take minutes (pytest-anatomy measured at ~190 s), so POST is
# 202 + a job id and the result is collected later.
#
# HONEST LIMITATION, stated rather than papered over: this map is in-process.
# A Bone restart loses the fact that a run was IN FLIGHT — it does NOT lose the
# verdict, which is sealed into the ledger, nor the judge runs, which are rows.
# A job that vanishes therefore reads as "unknown", never as "passed"; that is
# the safe direction, and `sweep_crashed()` reconciles the rows. A durable job
# table is the correct fix and is deliberately not invented here.
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


class ProposalIn(BaseModel):
    weakness_id: str = Field(..., min_length=1)
    target_paths: list[str] = Field(..., min_length=1)
    intent_class: str = Field(..., min_length=1)
    gate_set: str = Field(..., min_length=1)
    tree_sha: str = Field(..., min_length=7)
    proposer_id: str = Field(..., min_length=1)
    diff_text: str | None = None
    proposer_model: str | None = None


class JudgeIn(BaseModel):
    gate_set: str = Field(..., min_length=1)
    # A proposal to attach the verdict to. Optional: a gate set may be run to
    # establish a baseline with nothing proposed.
    proposal_uuid: str | None = None


@router.get("/budget")
def get_budget(gate_set: str = Query(..., min_length=1),
               _caller=Depends(require_loop_scope("read"))) -> dict[str, Any]:
    """What a proposal judged by `gate_set` may touch.

    A function of the SET, not a constant: the paths a judge reads to form its
    verdict are that judge's oracle, and a proposal may not edit the thing that
    grades it.
    """
    try:
        b = budget.budget_for(gate_set)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"unknown gate set: {exc}") from exc
    return {
        "gate_set": gate_set,
        "allowed_roots": sorted(b.allowed_roots),
        "denied": sorted(b.denied),
        "oracle_paths": sorted(b.oracle_paths),
        "max_files": b.max_files,
        "max_diff_lines": b.max_diff_lines,
    }


@router.post("/proposals", status_code=201)
def post_proposal(body: ProposalIn,
                  _caller=Depends(require_loop_scope("propose"))) -> dict[str, Any]:
    """Record an intent. Nothing here says whether it is any good.

    409 on refusal, and the refusal is the point: a fingerprint that already
    failed is rejected WITHOUT running the judges, which is what stops the loop
    re-proposing the same change forever.
    """
    led = ledger.open_ledger("agent:proposer")
    try:
        return led.record_proposal(
            weakness_id=body.weakness_id,
            target_paths=body.target_paths,
            intent_class=body.intent_class,
            gate_set=body.gate_set,
            tree_sha=body.tree_sha,
            proposer_id=body.proposer_id,
            diff_text=body.diff_text,
            proposer_model=body.proposer_model,
        )
    except ledger.ProposalRefused as exc:
        raise HTTPException(status_code=409, detail={
            "reason": exc.reason, "detail": exc.detail,
            "prior": list(getattr(exc, "prior", ()) or ()),
        }) from exc
    finally:
        led.close()


@router.get("/history")
def get_history(fingerprint: str = Query(..., min_length=8),
                _caller=Depends(require_loop_scope("read"))) -> dict[str, Any]:
    """Has this been tried, and what happened?"""
    led = ledger.open_ledger("agent:proposer")
    try:
        return {"fingerprint": fingerprint, "attempts": led.history(fingerprint)}
    finally:
        led.close()


def _execute(job_id: str, gate_set: str, proposal_uuid: str | None) -> None:
    """Run the set, record every judge run, seal. Evaluator role throughout."""
    # CONSTRAINT B, AND THE ONE PLACE IT IS ONLY PARTLY HONOURED.
    #
    # `begin_judge_run` is documented as written BEFORE the subprocess starts.
    # It is — inside `judges.py`, where a `JudgeRun` is constructed with
    # status="running" and completed by the code that reads the exit; the judge
    # never writes its own result. That discipline holds regardless of when the
    # row reaches SQLite, which is why persisting after the set returns does not
    # let a judge grade itself.
    #
    # What it DOES lose: if Bone dies mid-set, no rows exist at all, and
    # `sweep_crashed()` cannot sweep a row that was never written. The failure
    # is in the safe direction — a lost run reads as absent, never as passed —
    # but it is a real gap and `run_gate_set` has no ledger seam to close it
    # without threading persistence through the judge runner. Recorded here
    # rather than papered over.
    led = ledger.open_ledger("engine:evaluator")
    try:
        verdict = judges.run_gate_set(gate_set)
        for run in verdict.runs:
            run_uuid = led.begin_judge_run(
                gate_set=gate_set, judge_name=run.judge_name,
                argv=list(run.argv), proposal_uuid=proposal_uuid,
            )
            led.finish_judge_run(run_uuid, run=run)
        sealed = led.seal_verdict(gate_set=gate_set, proposal_uuid=proposal_uuid)
        with _JOBS_LOCK:
            _JOBS[job_id] = {"state": "done", "verdict": sealed}
    except Exception as exc:  # noqa: BLE001 — a crashed run must be legible
        # A failure to REACH a verdict is not a verdict. It is recorded as an
        # error so a reader cannot mistake it for a pass — the whole defect
        # class this engine exists to remove.
        with _JOBS_LOCK:
            _JOBS[job_id] = {"state": "error", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        led.close()


@router.post("/judge", status_code=202)
def post_judge(body: JudgeIn,
               _caller=Depends(require_loop_scope("judge"))) -> dict[str, Any]:
    """202 + a job id. The set may take minutes; nothing here blocks on it.

    The ONLY input that selects work is the gate-set NAME. There is no parameter
    that supplies, hints at, or overrides a result.
    """
    try:
        judges.load_registry().gate_set(body.gate_set)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"unknown gate set: {exc}") from exc

    job_id = str(uuid.uuid4())
    with _JOBS_LOCK:
        _JOBS[job_id] = {"state": "running", "gate_set": body.gate_set,
                         "started_at": time.time()}
    threading.Thread(target=_execute, args=(job_id, body.gate_set, body.proposal_uuid),
                     daemon=True, name=f"loop-judge-{job_id[:8]}").start()
    return {"job_id": job_id, "gate_set": body.gate_set, "state": "running"}


@router.get("/judge/{job_id}")
def get_judge(job_id: str,
              _caller=Depends(require_loop_scope("read"))) -> dict[str, Any]:
    """running | done + the sealed verdict | error | unknown.

    `unknown` after a restart is deliberate and is NOT `passed`. See the note on
    `_JOBS`.
    """
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={
            "state": "unknown",
            "detail": "no such job in this process — a Bone restart loses "
                      "in-flight jobs but never a sealed verdict; query the "
                      "ledger by proposal instead",
        })
    return {"job_id": job_id, **job}
