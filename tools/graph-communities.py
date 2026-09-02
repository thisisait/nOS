#!/usr/bin/env python3
"""graph-communities — computed communities vs the axes the estate DECLARES.

A READER over state/anatomy-graph.json (cortex-graph-borrowings item 4).
The estate declares `stack` and `layer` per node; this computes communities
from the edges alone and prints ONLY the disagreement — a community that
straddles stacks, a stack split across communities. Agreement is one line.

Label propagation, stdlib-only, DETERMINISTIC: nodes visited in sorted order,
ties broken by min label, synchronous-enough to converge on 286 edges in a
handful of sweeps. networkx/Leiden was priced and refused: the question is
"where do declared axes disagree with the wiring", and at 191 linked nodes
label propagation answers it identically without a new dependency
(decision recorded in docs/adr/0002-graphify-borrowings.md).

Exit 0 whatever it finds; a missing graph is UNKNOWN, never green (exit 3).
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter, defaultdict

REPO = pathlib.Path(__file__).resolve().parents[1]
GRAPH = REPO / "state" / "anatomy-graph.json"

# ponytail: sweeps are bounded; on this graph convergence is ~5 sweeps.
MAX_SWEEPS = 100


def communities(adj: dict[str, set[str]]) -> dict[str, list[str]]:
    """Deterministic label propagation: sorted visit order, min-label ties."""
    labels = {n: n for n in sorted(adj)}
    for _ in range(MAX_SWEEPS):
        changed = 0
        for n in sorted(adj):
            counts = Counter(labels[m] for m in adj[n])
            best = max(counts.values())
            new = min(l for l, c in counts.items() if c == best)
            if new != labels[n]:
                labels[n] = new
                changed += 1
        if not changed:
            break
    out: dict[str, list[str]] = defaultdict(list)
    for n, l in labels.items():
        out[l].append(n)
    return {l: sorted(ms) for l, ms in out.items()}


def build(drop: set[str] = frozenset()) -> dict:
    """`drop` excludes nodes (e.g. service:authentik, whose 58 SSO-gate edges
    fold half the estate into one community and mask every other axis)."""
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    nodes, edges = graph["nodes"], graph["edges"]
    adj: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        if e["from"] in drop or e["to"] in drop:
            continue
        adj[e["from"]].add(e["to"])
        adj[e["to"]].add(e["from"])
    comms = communities(adj)

    def axis(name: str) -> dict[str, str]:
        return {nid: n[name] for nid, n in nodes.items() if n.get(name)}

    report: dict = {
        "linked_nodes": len(adj),
        "communities": len(comms),
        "sizes": sorted((len(m) for m in comms.values()), reverse=True),
        "disagreements": {},
    }
    for name in ("stack", "layer"):
        declared = axis(name)
        member_of = {n: l for l, ms in comms.items() for n in ms}
        # a declared group split across communities — the wiring disagrees
        split = {}
        for value in sorted(set(declared.values())):
            homes = Counter(member_of[n] for n in sorted(declared)
                            if declared[n] == value and n in member_of)
            if len(homes) > 1:
                split[value] = {home: c for home, c in homes.most_common()}
        # a community mixing declared values — the axis disagrees with itself
        mixed = {}
        for label, members in sorted(comms.items()):
            vals = Counter(declared[n] for n in members if n in declared)
            if len(vals) > 1:
                mixed[label] = {v: c for v, c in vals.most_common()}
        report["disagreements"][name] = {"declared_split_across_communities": split,
                                         "community_mixing_declared_values": mixed}
    return report


def main() -> int:
    if not GRAPH.exists():
        print("UNKNOWN: state/anatomy-graph.json is missing — "
              "run tools/anatomy-graph-gen.py", file=sys.stderr)
        return 3
    drop = {a.split("=", 1)[1] for a in sys.argv if a.startswith("--drop=")}
    report = build(drop)
    if "--json" in sys.argv:
        print(json.dumps(report, indent=1))
        return 0
    print(f"communities — {report['communities']} over "
          f"{report['linked_nodes']} linked nodes, sizes "
          f"{report['sizes'][:10]}{'…' if len(report['sizes']) > 10 else ''}")
    for name, d in report["disagreements"].items():
        split, mixed = d["declared_split_across_communities"], d["community_mixing_declared_values"]
        if not split and not mixed:
            print(f"\n{name}: declared values and computed communities agree")
            continue
        print(f"\n{name} — where the wiring disagrees with the declaration:")
        for value, homes in split.items():
            print(f"  declared {name}={value} lands in {len(homes)} communities: "
                  + ", ".join(f"{h} ({c})" for h, c in homes.items()))
        for label, vals in mixed.items():
            print(f"  community {label} mixes: "
                  + ", ".join(f"{v} ({c})" for v, c in vals.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
