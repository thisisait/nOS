#!/usr/bin/env python3
"""nos-ops measurement harness — WHERE does the chain/tool-use boundary sit?

The ops plane (nos-ops, the client plane) wants small local models doing
extraction chains. The open question is not "does model X pass" but "at which
model SIZE does one_shot chain emission stop working", because that number is
what decides whether the ops plane ever needs a tool-use surface at all.

So this runs EVERY ARMED LOCAL binding in state/llm-backends.yml, over the
sizes that binding declares (~1B..~7B), in AgentKit `mode: one_shot`, against
a hand-labelled task family, and scores by EXACT reproduction of the label.
The oracle is this file. The model never assesses itself, and a size nobody
ran is UNKNOWN in the report — never a pass, never a blank.

Usage: tools/nos-ops-harness.py --family <dir> [--agent <name>] [--registry <yml>]
       [--out <json>] [--threshold 0.9] [--timeout 180] [--limit N]

    tools/nos-ops-harness.py --family state/ops-task-families/invoice-extract \\
                             --agent ops-extract

Reads only; exits 0 whatever it finds. Arming stays the operator's: a backend
is run only when its name is in NOS_ARMED_BACKENDS, the same law the binding
resolver applies.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import shlex
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO / "state" / "llm-backends.yml"
# tools/run-agent.sh, NOT `php bin/run-agent.php` (corrected 2026-08-30).
#
# The wrapper exists precisely to stop what calling the php directly does: its
# own first paragraph describes the symptom — an unset NOS_REPO_ROOT makes
# `getenv()` return FALSE, which is a TypeError deep in the DI container and
# names MigrationWriteTool rather than the missing variable. This harness
# bypassed the wrapper and hit exactly that, 44 times, reporting every one as
# "runner emitted no JSON summary".
#
# The wrapper also passes the running daemon's environment through and takes
# the agent mutex, both of which a measurement wants.
DEFAULT_CMD = str(REPO / "tools/run-agent.sh")
# The tier whose answer the ops plane's tool surface waits on.
TIER_B = (3.0, 7.0)


def armed_backends() -> set[str]:
    return set(os.environ.get("NOS_ARMED_BACKENDS", "").split())


def declared_bindings(registry: pathlib.Path) -> list[dict]:
    """Local rows, one entry per declared size. A row declares its sizes as
    `local: true` + `sizes_b: {1: <model-id>, 3: ..., 7: ...}`."""
    raw = yaml.safe_load(registry.read_text(encoding="utf-8")) or {}
    armed = armed_backends()
    out: list[dict] = []
    for name, row in (raw.get("backends") or {}).items():
        if not isinstance(row, dict) or not row.get("local"):
            continue
        for size, model in (row.get("sizes_b") or {}).items():
            out.append({
                "backend": name,
                "size_b": float(size),
                "model": str(model),
                "armed": name in armed,
                # The env var the RESOLVER reads for this tier, taken from the
                # row rather than guessed. ops-extract is haiku-tier (the whole
                # question is the small end), and setting anything else leaves
                # the binding refusing with "armed but <VAR> is empty".
                "model_env": (row.get("model_env") or {}).get("haiku"),
            })
    return sorted(out, key=lambda b: (b["size_b"], b["backend"]))


def load_family(family: pathlib.Path) -> tuple[dict, list[dict]]:
    meta = yaml.safe_load((family / "family.yml").read_text(encoding="utf-8")) or {}
    samples = [
        json.loads(line)
        for line in (family / "samples.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return meta, samples


def run_one(cmd: list[str], agent: str, prompt: str, binding: dict, timeout: int) -> dict:
    """One one_shot run. Returns the validated chain, or why there is none."""
    env = dict(os.environ)
    # THE VAR THE RESOLVER ACTUALLY READS. Until 2026-08-30 this set only
    # NOS_OPS_* — three variables nothing in the tree consumed — so a run
    # resolved whatever the plist had pinned, and the size column was a label
    # rather than a measurement. The registry names the var per tier; setting
    # that one is what makes the ladder real.
    env.update({
        "NOS_ARMED_BACKENDS": binding["backend"],
        "NOS_OPS_BACKEND": binding["backend"],
        "NOS_OPS_MODEL": binding["model"],
        "NOS_OPS_SIZE_B": str(binding["size_b"]),
    })
    if binding.get("model_env"):
        env[str(binding["model_env"])] = binding["model"]
    try:
        proc = subprocess.run(
            cmd + [f"--agent={agent}", f"--prompt={prompt}"],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"chain": None, "error": f"{type(exc).__name__}: {exc}"}
    try:
        summary = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"chain": None, "error": f"runner emitted no JSON summary: {proc.stderr[:200]}"}
    return {"chain": summary.get("chain"),
            # chain_error is the SCHEMA's reason; error is the session's. A
            # rejected answer has the first and not the second, and reporting
            # `detail: null` for it hid whether the model omitted a field or
            # answered in prose.
            "error": summary.get("error") or summary.get("chain_error"),
            "stop_reason": summary.get("stop_reason")}


def score(binding: dict, samples: list[dict], meta: dict, agent: str,
          cmd: list[str], timeout: int) -> dict:
    """The code oracle: exact reproduction of the hand-written label."""
    exact = invalid = wrong = errors = 0
    misses: list[dict] = []
    template = str(meta.get("prompt_template", "{input}"))
    for sample in samples:
        got = run_one(cmd, agent, template.replace("{input}", sample["input"]), binding, timeout)
        chain = got["chain"]
        if chain is None:
            # No chain at all: either the schema refused it or the run died.
            # Those are different facts and stay different in the report.
            if got.get("error") and got.get("stop_reason") is None:
                errors += 1
            else:
                invalid += 1
            misses.append({"id": sample["id"], "why": "no valid chain", "detail": got.get("error")})
        elif chain == sample["expect"]:
            exact += 1
        else:
            wrong += 1
            misses.append({"id": sample["id"], "why": "label not reproduced", "got": chain})
    attempted = len(samples) - errors
    return {
        "status": "measured" if attempted else "UNKNOWN",
        "backend": binding["backend"],
        "model": binding["model"],
        "attempted": attempted,
        "exact": exact,
        "invalid_chain": invalid,
        "wrong_labels": wrong,
        "runner_errors": errors,
        "accuracy": round(exact / attempted, 4) if attempted else None,
        "misses": misses[:10],
    }


def build_report(family: pathlib.Path, agent: str | None, registry: pathlib.Path,
                 threshold: float, cmd: list[str], timeout: int, limit: int | None) -> dict:
    meta, samples = load_family(family)
    if limit:
        samples = samples[:limit]
    bindings = declared_bindings(registry)

    by_size: dict[str, dict] = {}
    for binding in bindings:
        key = str(binding["size_b"])
        if not binding["armed"]:
            by_size[key] = {"status": "UNKNOWN", "backend": binding["backend"],
                            "model": binding["model"],
                            "reason": f"backend '{binding['backend']}' is not in NOS_ARMED_BACKENDS"}
        elif agent is None:
            by_size[key] = {"status": "UNKNOWN", "backend": binding["backend"],
                            "reason": "no --agent given: nothing to run in one_shot mode"}
        else:
            by_size[key] = score(binding, samples, meta, agent, cmd, timeout)

    measured = {float(k): v for k, v in by_size.items() if v.get("status") == "measured"}
    passing = sorted(s for s, v in measured.items() if (v["accuracy"] or 0) >= threshold)
    unmeasured = sorted(float(k) for k, v in by_size.items() if v.get("status") != "measured")
    tier_measured = [s for s in measured if TIER_B[0] <= s <= TIER_B[1]]

    return {
        "header": {
            "question": "at which model size does one_shot chain emission stop reproducing labels",
            "read_this_as": "a size nobody ran is UNKNOWN — never a pass, never green",
            "scored_by": "code oracle (exact label match); the model never assesses itself",
            "ops_plane_tool_surface": "CLOSED",
            "closed_because": (
                "no armed local binding has produced a number for the 3-7B tier"
                if not tier_measured else
                "the 3-7B tier has a number; opening a tool surface is the "
                "operator's decision, not this report's"
            ),
        },
        "family": meta.get("name", family.name),
        "samples": len(samples),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "registry": str(registry),
        "agent": agent,
        "declared_sizes_b": sorted({b["size_b"] for b in bindings}),
        "armed_backends": sorted(armed_backends()),
        "by_model_size_b": by_size,
        "boundary": {
            "threshold": threshold,
            "status": "MEASURED" if passing else "UNKNOWN",
            "chain_tier_floor_b": passing[0] if passing else None,
            "unmeasured_sizes_b": unmeasured,
            "note": (
                "no local binding is declared at any size"
                if not bindings else
                "every measured size fell below the threshold; the floor is "
                "above what was run" if measured and not passing else
                "nothing was run" if not measured else
                "smallest size at or above the threshold"
            ),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--family", required=True, type=pathlib.Path)
    ap.add_argument("--agent", help="one_shot agent to run; omitted = report what is declared only")
    ap.add_argument("--registry", type=pathlib.Path, default=DEFAULT_REGISTRY)
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--threshold", type=float, default=0.9)
    ap.add_argument("--timeout", type=int, default=180, help="seconds per sample")
    ap.add_argument("--limit", type=int, help="score only the first N samples")
    args = ap.parse_args()

    cmd = shlex.split(os.environ.get("NOS_OPS_HARNESS_CMD", DEFAULT_CMD))
    report = build_report(args.family, args.agent, args.registry,
                          args.threshold, cmd, args.timeout, args.limit)
    out = args.out or (REPO / "state" / "ops-harness" / f"{report['family']}-report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(json.dumps(report["boundary"], indent=2))
    print(f"report: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
