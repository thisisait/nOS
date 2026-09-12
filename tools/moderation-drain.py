#!/usr/bin/env python3
"""moderation-drain — PREPARE a weekly moderation batch for the operator to approve.

The nOS-side of the moderation-drain-loop (moderation-drain-contract.md is the SoT).
KEAP's ModerationPanel has a zero-consumer backlog of librarian node-briefs; this
reader classifies the proposed items and drafts a git-trackable PLAN — it does NOT
approve. Apply stays the operator's, under his session (human /api decide-brief-bulk),
because moderation is a human decision; and every applied batch must be followed by
the dump.mjs → canonical → mirror backport or the brief vanishes on the next converge.

  tools/moderation-drain.py                 # live: read proposed → classify → print the plan
  tools/moderation-drain.py --json          # the plan as JSON (feeds the operator's apply step)

plan_drain (below) is the pure heart, tested offline. The live reader + per-node
fill/overwrite/dead enrichment need KEAP (and the pinned bulk endpoint for apply).
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


# ── live enrichment (KEAP; the pinned interface) ─────────────────────────────
def _get(path: str, hdr: dict):
    req = urllib.request.Request(f"{AGENT}{path}", headers=hdr)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def _enrich(hdr: dict) -> list:
    """Read proposed briefs and resolve each one's domain / fill-vs-overwrite / dead
    target against the live taxonomy (moderation-drain-contract §reader)."""
    d = _get("/promotions?" + urllib.parse.urlencode({"status": "proposed", "limit": 5000}), hdr)
    items = (d.get("data") or {}).get("items") or d.get("items") or []
    out = []
    for it in items:
        if it.get("kind") != "brief":
            continue
        node_id = (it.get("object") or {}).get("nodeId") or ""
        alive, is_fill = True, True
        try:
            node = _get(f"/taxonomy/node/{urllib.parse.quote(node_id)}", hdr)
            curated = (node.get("data") or node).get("curated") or {}
            is_fill = not curated.get("brief")           # brief present ⇒ overwrite
        except urllib.error.HTTPError as e:
            if e.code == 404:
                alive = False                            # dead target
            else:
                raise
        out.append({"id": it.get("id"), "domain": (node_id.split(".")[0] or "?"),
                    "is_fill": is_fill, "target_alive": alive, "is_nos": node_id.startswith("nos")})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="print the plan as JSON")
    args = ap.parse_args()
    hdr = {"Authorization": f"Bearer {ro_token()}", **proxy_header()}
    try:
        items = _enrich(hdr)
    except (urllib.error.URLError, OSError) as exc:
        print(f"REFUSING: KEAP moderation queue unreadable ({exc})", file=sys.stderr)
        return 2

    plan = plan_drain(items)
    if args.json:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return 0
    print(f"moderation drain plan — {len(items)} proposed brief(s)")
    print(f"  retarget (dead target):   {len(plan['retarget'])}  → reject + re-propose")
    print(f"  human-review (nos.*/overwrite): {len(plan['human_review'])}  → one by one")
    print(f"  batchable fills across {len(plan['domains'])} domain(s):")
    for dom, d in plan["domains"].items():
        print(f"    {dom:6} total {d['total']:4}  · spot-check {len(d['sample'])} "
              f"(need ≥{d['min_pass']} pass) → then batch {len(d['batch_candidates'])}")
    print("\napply is the operator's (human /api decide-brief-bulk) + the dump.mjs backport.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
