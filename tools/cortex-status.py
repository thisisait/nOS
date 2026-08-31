#!/usr/bin/env python3
"""What the cortex organ is, all of it — not just the part KEAP serves.

WHY THIS EXISTS. Asked "how is the cortex", this estate could answer about
KEAP (`tools/cortex-drift.py`, the corpus diff, the taxonomy counts) and about
nothing else, because KEAP is the half with a UI. The organ is bigger than its
UI and it is split across two runtimes:

    validate   files/anatomy/cortex/  (Node, :8098)  tokenise, parse, analyse
    execute    files/anatomy/wing/    (PHP,  :9000)  7 opcode handlers
    knowledge  KEAP                   (Docker)       taxonomy, relations, objects

The operator's framing, 2026-08-31: "Cortex is not just KEAP; the whole organ
should be in nOS, KEAP only as UI + general knowledge." This reader is the
first thing that treats it that way — one question, three halves, one answer.

THE LOAD-BEARING CHECK IS THE SEAM. Both halves publish an
`opcodeRegistryHash` / `registry_hash`, and they are supposed to be the same
string: the validator accepts a chain the executor can run, and refuses one it
cannot. Nothing compared them until this file. If they diverge, the estate is
in the worst available state — every chain validates and some fail at
execution, which reads as a model problem and is not one.

WHAT THIS DOES NOT DO. It does not re-implement `tools/cortex-drift.py`
(vendored organ vs ~/keap/src); it points at it. Two readers, two questions.

Reads only. Exit 0 when every half answered, 2 when one could not — an
unreachable half is UNKNOWN, never green.

Usage:
    tools/cortex-status.py            # the three halves and the seam
    tools/cortex-status.py --json     # for a caller (the cc pane)
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sqlite3
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import _ledger_open  # noqa: E402 — after REPO is known

ORGAN_URL = os.environ.get("NOS_CORTEX_URL", "http://127.0.0.1:8098")
WING_URL = os.environ.get("NOS_WING_URL", "http://127.0.0.1:9000")


def _secret(name: str) -> str:
    """From the operator's store, the way every other reader here does it."""
    try:
        import yaml
        store = yaml.safe_load(
            (pathlib.Path.home() / ".nos" / "secrets.yml").read_text()) or {}
        return str(store.get(name) or "")
    except Exception:                                     # noqa: BLE001
        return ""


def _get(url: str, headers: dict[str, str] | None = None) -> tuple[dict | None, str]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            return json.loads(resp.read().decode("utf-8")), ""
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def validate_half() -> dict:
    body, err = _get(f"{ORGAN_URL}/agent/v1/health")
    if body is None:
        return {"reachable": False, "detail": err}
    data = body.get("data") or body
    binding = data.get("binding") or {}
    store = data.get("store") or {}
    return {
        "reachable": True,
        "version": data.get("version"),
        "surface": data.get("surface"),
        "registry_hash": binding.get("opcodeRegistryHash"),
        "ontology": binding.get("ontologyVersion"),
        "store_path": store.get("path"),
        "spine_in_sync": store.get("spineInSync"),
    }


def execute_half() -> dict:
    headers = {
        "Authorization": "Bearer " + _secret("cortex_executor_token"),
        "X-Wing-Edge-Token": _secret("wing_edge_token"),
    }
    body, err = _get(f"{WING_URL}/api/v1/cortex/opcodes", headers)
    if body is None:
        return {"reachable": False, "detail": err}
    return {
        "reachable": True,
        "handlers": body.get("handlers") or [],
        "registry_hash": body.get("registry_hash"),
        "covers_keap": body.get("covers_keap"),
        "uncovered": body.get("uncovered") or [],
        # WHERE IT RUNS is the point of this row, not decoration: the executor
        # lives inside Wing, which is the split this reader exists to show.
        "runtime": "wing (php)",
    }


def traffic() -> dict:
    """Who actually speaks the language, from the ledger.

    Measured 2026-08-31: every chain in the last three days came from the smoke
    catalog. A language whose only speaker is its own smoke test is a fact the
    organ's health should carry, because both halves are green while it is
    true."""
    conn, how = _ledger_open.open_ledger_ro()
    if conn is None:
        return {"readable": False, "detail": how}
    try:
        rows = conn.execute(
            "SELECT COUNT(*) n, COUNT(DISTINCT actor_action_id) chains "
            "FROM events WHERE type='cortex_stage_begin' "
            "AND ts > date('now','-7 days')").fetchone()
        lengths = conn.execute(
            "SELECT n, COUNT(*) c FROM (SELECT COUNT(*) n FROM events "
            "WHERE type='cortex_stage_begin' AND ts > date('now','-7 days') "
            "GROUP BY actor_action_id) GROUP BY n ORDER BY n").fetchall()
        return {
            "readable": True,
            "stages_7d": rows["n"],
            "chains_7d": rows["chains"],
            "by_length": {str(r["n"]): r["c"] for r in lengths},
        }
    except sqlite3.OperationalError as exc:
        return {"readable": False, "detail": str(exc)}
    finally:
        conn.close()


def report() -> dict:
    v, e, t = validate_half(), execute_half(), traffic()
    seam = {"agree": None, "detail": "one half did not answer"}
    if v.get("reachable") and e.get("reachable"):
        same = bool(v.get("registry_hash")) and v["registry_hash"] == e["registry_hash"]
        seam = {
            "agree": same,
            "validate": v.get("registry_hash"),
            "execute": e.get("registry_hash"),
            "detail": "the validator and the executor agree on the opcode registry"
            if same else
            "THE HALVES DISAGREE: a chain may validate and then fail to execute, "
            "which reads as a model defect and is not one",
        }
    return {"organ": "cortex", "validate": v, "execute": e,
            "seam": seam, "traffic": t,
            "vendor_drift": "ask tools/cortex-drift.py — a separate question"}


def render(r: dict) -> int:
    v, e, s, t = r["validate"], r["execute"], r["seam"], r["traffic"]
    print("cortex — one organ, three halves\n")

    if v.get("reachable"):
        print(f"  validate   node :8098   v{v['version']}  surface={v['surface']}  "
              f"spine={'in sync' if v.get('spine_in_sync') else 'OUT OF SYNC'}")
        print(f"             ontology {v.get('ontology')}")
    else:
        print(f"  validate   UNREACHABLE — {v.get('detail','')[:70]}")

    if e.get("reachable"):
        cover = "covers KEAP" if e.get("covers_keap") else \
            f"UNCOVERED: {', '.join(e.get('uncovered') or [])}"
        print(f"  execute    {e['runtime']:<11} {len(e['handlers'])} handler(s)  {cover}")
        print(f"             {' '.join(e['handlers'])}")
    else:
        print(f"  execute    UNREACHABLE — {e.get('detail','')[:70]}")

    mark = {True: "agree", False: "DISAGREE", None: "UNKNOWN"}[s["agree"]]
    print(f"\n  seam       {mark}  {s.get('validate') or '?'}")
    if s["agree"] is False:
        print(f"             executor says {s.get('execute')}")
    if s["agree"] is not True:
        print(f"             {s['detail']}")

    if t.get("readable"):
        shape = ", ".join(f"{n}-stage×{c}" for n, c in sorted(t["by_length"].items()))
        print(f"\n  traffic    {t['stages_7d']} stage(s) in {t['chains_7d']} chain(s), 7d"
              f"{'  (' + shape + ')' if shape else ''}")
    else:
        print(f"\n  traffic    UNKNOWN — {t.get('detail','')[:70]}")

    print(f"\n  vendor     {r['vendor_drift']}")
    return 0 if (v.get("reachable") and e.get("reachable")) else 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = report()
    if args.json:
        print(json.dumps(r, indent=1, default=str))
        return 0 if (r["validate"].get("reachable")
                     and r["execute"].get("reachable")) else 2
    return render(r)


if __name__ == "__main__":
    sys.exit(main())
