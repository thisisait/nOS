#!/usr/bin/env python3
"""moderation-drain — PREPARE a weekly moderation batch for the operator to approve.

The nOS-side of the moderation-drain-loop (moderation-drain-contract.md is the SoT).
This reader classifies proposed briefs and drafts a git-trackable PLAN — it does NOT
approve. Apply stays the operator's session (human /api). Every applied batch must be
followed by the dump.mjs → canonical → mirror backport or the brief vanishes on converge.

  tools/moderation-drain.py                 # live: read proposed → classify → print the draft
  tools/moderation-drain.py --json          # operator draft (prefilter); apply is always empty
  tools/moderation-drain.py --json --labels PATH   # inject Sonnet low-match / attention labels

draft_prefilter is the operator-draft heart. plan_drain remains the old 9/10 domain
spot-check (offline tests); it is not what --json dumps.
Exit 0 · 2 KEAP unreadable.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
from digest_absorb import ro_token  # noqa: E402
from keap_api import proxy_header  # noqa: E402

AGENT = "http://127.0.0.1:8091/agent/v1"
READER = "GET /agent/v1/promotions?status=proposed"
SORT = {"nos": 0, "overwrite": 1, "dead-target": 2, "attention": 3, "fill-ok": 4}
LLM_LABELS = {"low-match", "attention"}


def plan_drain(items: list, threshold_frac: float = 0.9, sample_frac: float = 0.1) -> dict:
    """Pure. items: [{id, domain, is_fill, target_alive, is_nos}]. Returns the drain
    PLAN — no live calls, no approvals:
      retarget:      dead-target briefs (node 404) — reject + re-propose on the new id.
      human_review:  nos.* briefs (highest blast radius) + every overwrite. One by one.
      domains:       per domain of the remaining alive FILLS — a deterministic
                     spot-check `sample` (~sample_frac, min 1, sorted by id) the
                     operator reviews, `min_pass` (ceil(threshold_frac*sample)),
                     and `batch_candidates` (the rest) to approve IF the sample clears.
    The operator judges each domain's sample; a domain whose sample passes ≥ min_pass
    gets its batch_candidates approved. Nothing is auto-approved here."""
    retarget = sorted(i["id"] for i in items if not i.get("target_alive"))
    human = sorted(i["id"] for i in items
                   if i.get("target_alive") and (i.get("is_nos") or not i.get("is_fill")))
    fills = [i for i in items if i.get("target_alive") and i.get("is_fill") and not i.get("is_nos")]
    by_domain: dict[str, list] = {}
    for i in fills:
        by_domain.setdefault(i.get("domain") or "?", []).append(i["id"])
    domains = {}
    for dom, ids in sorted(by_domain.items()):
        ids = sorted(ids)
        k = max(1, min(len(ids), math.ceil(len(ids) * sample_frac)))
        sample = ids[:k]
        domains[dom] = {"total": len(ids), "sample": sample,
                        "min_pass": math.ceil(threshold_frac * k),
                        "batch_candidates": [x for x in ids if x not in sample]}
    return {"retarget": retarget, "human_review": human, "domains": domains}


def _node_id(it: dict) -> str:
    return it.get("nodeId") or (it.get("object") or {}).get("nodeId") or ""


def draft_prefilter(items: list, labels=()) -> dict:
    """Classify proposed briefs for the operator draft. No live calls.

    nos.* stays in ready_for_operator (top). overwrite / dead-target only when
    those fields are already on the item. --labels may inject low-match
    (dequeue, keep proposed) or attention. Everything else is fill-ok.
    apply is always empty — this tool never writes KEAP status.
    """
    extra = dict(labels) if labels else {}
    excluded, ready = [], []
    for it in items:
        iid = it.get("id")
        nid = _node_id(it)
        inj = extra.get(iid) if isinstance(extra.get(iid), dict) else None
        inj_lab = (inj or {}).get("label") if inj and inj.get("label") in LLM_LABELS else None

        if nid.startswith("nos"):
            lab = "nos"
        elif it.get("overwrite"):
            lab = "overwrite"
        elif it.get("dead-target"):
            lab = "dead-target"
        elif inj_lab == "low-match":
            excluded.append({
                "id": iid, "label": "low-match",
                "reason": inj.get("reason") or "",
                "keap_status": "proposed",
            })
            continue
        elif inj_lab == "attention":
            lab = "attention"
        else:
            lab = "fill-ok"

        row = {"id": iid, "label": lab, "sort_key": SORT[lab]}
        if nid:
            row["nodeId"] = nid
        ready.append(row)

    ready.sort(key=lambda r: (r["sort_key"], r["id"] or ""))
    return {
        "unverified": True,
        "reader": READER,
        "queue_n": len(items),
        "excluded": excluded,
        "ready_for_operator": ready,
        "apply": [],
    }


def _get(path: str, hdr: dict):
    req = urllib.request.Request(f"{AGENT}{path}", headers=hdr)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def _proposed_briefs(hdr: dict) -> list:
    d = _get("/promotions?" + urllib.parse.urlencode({"status": "proposed", "limit": 5000}), hdr)
    items = (d.get("data") or {}).get("items") or d.get("items") or []
    out = []
    for it in items:
        if it.get("kind") != "brief":
            continue
        row = {"id": it.get("id"), "nodeId": _node_id(it)}
        if it.get("overwrite"):
            row["overwrite"] = it["overwrite"]
        if it.get("dead-target"):
            row["dead-target"] = it["dead-target"]
        out.append(row)
    return out


def _load_labels(path: pathlib.Path) -> dict:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        if isinstance(v, dict) and v.get("label") in LLM_LABELS:
            out[k] = {"label": v["label"], "reason": v.get("reason") or ""}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="print the operator draft as JSON")
    ap.add_argument("--labels", type=pathlib.Path, default=None,
                    help="optional id→{label,reason} JSON (low-match|attention only)")
    args = ap.parse_args()
    hdr = {"Authorization": f"Bearer {ro_token()}", **proxy_header()}
    try:
        items = _proposed_briefs(hdr)
    except (urllib.error.URLError, OSError) as exc:
        print(f"REFUSING: KEAP moderation queue unreadable ({exc})", file=sys.stderr)
        return 2

    extra = _load_labels(args.labels) if args.labels else {}
    draft = draft_prefilter(items, extra)
    if args.json:
        print(json.dumps(draft, indent=2, ensure_ascii=False))
        return 0
    print(f"moderation drain draft — {draft['queue_n']} proposed (unverified)")
    print(f"  excluded (still proposed): {len(draft['excluded'])}")
    for e in draft["excluded"]:
        print(f"    {e['id']}  {e['label']}  {e.get('reason', '')}")
    print(f"  ready_for_operator: {len(draft['ready_for_operator'])}")
    for r in draft["ready_for_operator"]:
        print(f"    {r['sort_key']} {r['label']:12} {r['id']}  {r.get('nodeId', '')}")
    print("  apply: []  — operator session; this reader does not write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
