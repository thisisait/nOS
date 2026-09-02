#!/usr/bin/env python3
"""Read state/anatomy-graph.json and say what its SHAPE implies.

A graph you only ever query node-by-node never tells you what it knows in
aggregate. Borrowed from Graphify's GRAPH_REPORT.md (Apache-2.0), which reports
god nodes and surprising connections rather than leaving them to be noticed.

Four questions, all of which found something the first time they were asked
(2026-09-02, 256 nodes / 286 edges):

  god nodes        service:authentik carries 58 edges, 55 of them outbound.
  isolated nodes   65 of 256 have no edge at all — every host daemon but pulse.
                   Bone<->Wing is named as a VEIN in CLAUDE.md and is not an edge,
                   so the graph knows the estate's services and not its organs.
  evidence split   236 derived / 50 measured. A derived edge is recomputed from a
                   declaration every run and cannot go stale. A measured one is a
                   human who read code on a date.
  rotted evidence  ...and that is the one that rots. This resolves the file:line
                   citations in a measured edge's `via` and asks git whether that
                   file has changed since the measurement. Nothing else does.

READER, not a writer. Exits 0 on any finding — a report is not a gate, and the
estate has been bitten before by a detector that reported by failing. Use
`--exit-nonzero-on-rot` if you want it in a job that should go red.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
GRAPH = REPO / "state" / "anatomy-graph.json"

#: A citation inside `via`, e.g. "tools/scan-state-snapshot.py:90". The `/` is
#: required: a bare `scan-state.json` in prose is a NAME, not a path, and
#: treating it as one reported four files as deleted that were never cited.
CITE = re.compile(r"\b([A-Za-z0-9_][\w.-]*(?:/[\w.-]+)+\.(?:py|yml|yaml|sh|php|ts|mjs|js|j2|json))\b")


def _index() -> dict[str, list[str]]:
    """Repo files by basename, so a citation can be resolved as a SUFFIX.

    `via` prose cites paths at whatever depth reads well — "skills/run-tofu-drift.sh"
    for a file six directories down. Treating those as repo-relative reported
    live files as deleted.
    """
    out: dict[str, list[str]] = {}
    for f in subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True,
                            text=True, timeout=60).stdout.splitlines():
        out.setdefault(f.rsplit("/", 1)[-1], []).append(f)
    return out


def _resolve(cited: str, index: dict[str, list[str]]) -> str | None:
    """The one repo file this citation names, or None if none or many."""
    if (REPO / cited).is_file():
        return cited
    hits = [f for f in index.get(cited.rsplit("/", 1)[-1], [])
            if f == cited or f.endswith("/" + cited)]
    return hits[0] if len(hits) == 1 else None


def _last_change(path: str) -> str | None:
    """Committer date of the last commit touching `path`, ISO-8601, or None."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", path],
            cwd=REPO, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--top", type=int, default=10, help="god nodes to list")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    ap.add_argument("--exit-nonzero-on-rot", action="store_true",
                    help="exit 1 when a measured edge cites a file changed since")
    args = ap.parse_args()

    if not GRAPH.is_file():
        print(f"UNKNOWN: {GRAPH} is missing — run tools/anatomy-graph-gen.py")
        return 0
    g = json.loads(GRAPH.read_text(encoding="utf-8"))
    nodes, edges = g["nodes"], g["edges"]

    ind, outd = collections.Counter(), collections.Counter()
    for e in edges:
        outd[e["from"]] += 1
        ind[e["to"]] += 1
    deg = collections.Counter({k: ind[k] + outd[k] for k in set(ind) | set(outd)})
    isolated = sorted(k for k in nodes if deg[k] == 0)
    evidence = collections.Counter(e.get("evidence", "—") for e in edges)

    # Rot: a measured edge whose cited file moved after the measurement.
    rotted, unverifiable = [], []
    index = _index()
    for e in edges:
        if e.get("evidence") != "measured":
            continue
        when = str(e.get("measured", ""))
        for cited in dict.fromkeys(CITE.findall(str(e.get("via", "")))):
            real = _resolve(cited, index)
            if real is None:
                # Not necessarily rot: `via` also cites RUNTIME paths
                # (~/.nos/cortex-corpus-diff.json), which this cannot check.
                # Unknown is neither fresh nor rotted, and saying so is the
                # whole point of keeping the buckets apart.
                unverifiable.append((e, cited, "names no single repo file"))
                continue
            changed = _last_change(real)
            if changed and changed[:10] > when[:10]:
                rotted.append((e, cited, f"changed {changed[:10]}, measured {when[:10]}"))

    if args.json:
        print(json.dumps({
            "nodes": len(nodes), "edges": len(edges),
            "god_nodes": [{"id": k, "degree": v, "in": ind[k], "out": outd[k]}
                          for k, v in deg.most_common(args.top)],
            "isolated": isolated,
            "isolated_by_kind": dict(collections.Counter(
                nodes[k].get("kind", "?") for k in isolated)),
            "evidence": dict(evidence),
            "rotted": [{"from": e["from"], "to": e["to"], "file": f, "why": w}
                       for e, f, w in rotted],
            "unverifiable": [{"from": e["from"], "to": e["to"], "file": f, "why": w}
                             for e, f, w in unverifiable],
        }, indent=2))
    else:
        print(f"anatomy graph — {len(nodes)} nodes, {len(edges)} edges\n")
        print(f"god nodes (top {args.top}) — what the estate cannot lose:")
        for k, v in deg.most_common(args.top):
            print(f"  {v:3d}  ({ind[k]:>2} in /{outd[k]:>2} out)  {k}")
        by_kind = collections.Counter(nodes[k].get("kind", "?") for k in isolated)
        print(f"\nisolated — {len(isolated)} of {len(nodes)} nodes carry no edge:")
        for kind, n in by_kind.most_common():
            print(f"  {n:3d}  {kind}")
        print("  (a node with no edge is not known to relate to anything; for a "
              "daemon\n   that means the graph cannot answer what breaks when it "
              "stops)")
        print("\nevidence — how each edge is attested:")
        for k, v in evidence.most_common():
            print(f"  {v:3d}  {k}")
        n_meas = evidence.get("measured", 0)
        print(f"\nrotted evidence — {len(rotted)} of {n_meas} measured edges cite "
              "a file that moved since:")
        for e, f, why in rotted[:8]:
            print(f"  {e['from']} -> {e['to']}\n      {f}: {why}")
        if len(rotted) > 8:
            print(f"  … and {len(rotted) - 8} more")
        if rotted:
            print("  A measured edge is a human reading code on a date; it cannot\n"
                  "   re-verify itself. The fix for a rotting one is to DERIVE it.")
        if not rotted:
            print("  none — every measured edge's citations predate their files' "
                  "last change")
        if unverifiable:
            print(f"\nunverifiable — {len(unverifiable)} citation(s) name no single "
                  "repo file\n  (runtime paths, or a rename this cannot follow — "
                  "neither fresh nor rotted):")
            for e, f, why in unverifiable[:5]:
                print(f"  {e['from']} -> {e['to']}: {f}")

    return 1 if (rotted and args.exit_nonzero_on_rot) else 0


if __name__ == "__main__":
    sys.exit(main())
