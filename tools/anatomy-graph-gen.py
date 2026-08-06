#!/usr/bin/env python3
"""Compile the anatomy graph — every declared actor and edge, one address space.

WHAT THIS IS
------------
The estate's automated actors (pulse jobs, judges, gate sets, weakness
sources, host daemons, services, mutex resources) and the edges between them
(`depends_on` in the pulse-job manifests) compiled into ONE artifact:
`state/anatomy-graph.json`. Design + measurement:
docs/archive/nos-anatomy-graph.md; the address space is §2(b), the refusals
the gate enforces are §2(c).

This is the estate's regenerate-and-diff pattern (genome-codegen,
tofu-authentik-gen-registry, gdpr-dpa-register --check) pointed at a new
source — not new machinery. The committed JSON is byte-stable: no timestamps,
sorted keys, sorted edges. CI goes red on drift via
tests/anatomy/test_anatomy_graph_is_sound.py, which imports build() from here.

ONE DIVERGENCE FROM THE SURVEY'S EDGE SHAPE (§2a): the edge field is
`upstream:`, not `on:`. PyYAML implements YAML 1.1, where a bare `on` key is
the BOOLEAN True — `yaml.safe_load("on: x")` returns `{True: "x"}` — so the
surveyed spelling silently loses the field name in every reader in the estate.
Same trap class as the Norway problem; refused rather than accommodated.

ADDRESS SPACE (kind-prefixed, local ids verbatim — §2b)
-------------------------------------------------------
    pulse:<owner>:<job>     owner = plugin name minus -base, or agent_id
                            (matches wing.db pulse_jobs id, e.g. keap:keap-lint)
    judge:<name>            state/judge-sets.yml key
    gateset:<name>          state/judge-sets.yml gate_sets key
    weakness:<id>           files/anatomy/bone/weaknesses.py SOURCE_ORDER
    daemon:<launchd label>  eu.thisisait.nos.* labels from role defaults
    service:<manifest id>   state/manifest.yml services[].id
    resource:<name>         mutex/capability resources (claims + requires)

WHAT IS DERIVED, NOT DECLARED
-----------------------------
  * mutex pairs — from `claims:` on nodes (pairwise edges are REFUSED as
    declarations, §2a: with N claimants they take N(N-1)/2 edges to stay true)
  * the agent-run-lock claim — any job whose command runs pulse-run-agent.sh
    or scan-runner.sh takes ~/.nos/agent-run.lock via agent-run-lock.sh
    (one law, one implementation — commit ba7a9471)
  * daemon:eu.thisisait.nos.pulse → job dispatch edges (structural: the
    daemon fires every unpaused job; pulse/daemon.py list_due_jobs)
  * judge capability edges — judge-sets `requires:` become data edges from
    resource:* nodes (satisfied or not, never exclusive)
  * temporal debt — for every temporal edge, the worst-case DECLARED margin
    (cron gap − upstream jitter − upstream max_runtime) and whether the
    declared budgets already permit inversion (§1.4 col 4)

Usage:
    python3 tools/anatomy-graph-gen.py            # write state/anatomy-graph.json
    python3 tools/anatomy-graph-gen.py --check    # exit 1 if the artifact is stale
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
TARGET = REPO / "state" / "anatomy-graph.json"

JOB_SOURCES = ("files/anatomy/plugins/*/plugin.yml", "files/anatomy/agents/*.yml")
JUDGE_SETS = REPO / "state" / "judge-sets.yml"
WEAKNESSES = REPO / "files" / "anatomy" / "bone" / "weaknesses.py"
MANIFEST = REPO / "state" / "manifest.yml"

#: Commands that spawn a claude CLI go through the one mkdir mutex
#: (files/anatomy/scripts/agent-run-lock.sh). Derived, not declared: the claim
#: is a fact about the code, and the code has exactly two spawn sites.
AGENT_LOCK_COMMANDS = ("pulse-run-agent.sh", "scan-runner.sh")
AGENT_LOCK_RESOURCE = "agent-run-lock"

EDGE_KINDS = ("data", "trigger", "temporal")


def _die(msg: str) -> None:
    print(f"anatomy-graph-gen: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _iso(v) -> str | None:
    """yaml gives `measured: 2026-08-06` as a date object; normalise to str."""
    if v is None:
        return None
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return str(v)


# ── harvest: pulse jobs ───────────────────────────────────────────────────


def _owner(doc: dict, path: Path) -> str:
    return re.sub(r"-base$", "", str(doc.get("name") or doc.get("agent_id") or path.stem))


def harvest_pulse(nodes: dict, raw_edges: list) -> None:
    for pattern in JOB_SOURCES:
        for path in sorted(REPO.glob(pattern)):
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if not isinstance(doc, dict):
                continue
            owner = _owner(doc, path)
            for job in (doc.get("pulse") or {}).get("jobs") or []:
                if not (isinstance(job, dict) and job.get("name")):
                    continue
                nid = f"pulse:{owner}:{job['name']}"
                claims = sorted(set(job.get("claims") or []))
                cmd = str(job.get("command") or "")
                if any(cmd.endswith(s) for s in AGENT_LOCK_COMMANDS):
                    claims = sorted(set(claims) | {AGENT_LOCK_RESOURCE})
                nodes[nid] = {
                    "kind": "pulse",
                    "source": str(path.relative_to(REPO)),
                    "schedule": job.get("schedule"),
                    "jitter_min": job.get("jitter_min", 0),
                    "max_runtime_s": job.get("max_runtime_s", 300),
                    "category": job.get("category"),
                    "paused": bool(job.get("paused", False)),
                    "findings_exit_codes": job.get("findings_exit_codes"),
                    "claims": claims,
                }
                for dep in job.get("depends_on") or []:
                    raw_edges.append((nid, dep, str(path.relative_to(REPO))))


# ── harvest: judges + gate sets ───────────────────────────────────────────


def harvest_judges(nodes: dict, edges: list) -> None:
    doc = yaml.safe_load(JUDGE_SETS.read_text(encoding="utf-8"))
    for name, j in (doc.get("judges") or {}).items():
        claims = [j["exclusive_resource"]] if j.get("exclusive_resource") else []
        nodes[f"judge:{name}"] = {
            "kind": "judge",
            "source": "state/judge-sets.yml",
            "deterministic": j.get("deterministic"),
            "mutates_worktree": j.get("mutates_worktree"),
            "min_work": j.get("min_work"),
            "claims": claims,
            "requires": list(j.get("requires") or []),
        }
        for cap in j.get("requires") or []:
            edges.append({
                "from": f"resource:{cap}",
                "to": f"judge:{name}",
                "kind": "data",
                "via": "capability requirement (judge-sets requires:) — satisfied or not, never exclusive",
                "derived": "judge-sets.requires",
            })
    for name, gs in (doc.get("gate_sets") or {}).items():
        nodes[f"gateset:{name}"] = {
            "kind": "gateset",
            "source": "state/judge-sets.yml",
            "judges": list(gs.get("judges") or []),
            "unattended": bool(gs.get("unattended", False)),
        }


# ── harvest: weakness sources (regex over the reader — it declares its own
#    order and this must not import a FastAPI app to read a tuple) ─────────


def harvest_weaknesses(nodes: dict) -> None:
    text = WEAKNESSES.read_text(encoding="utf-8")
    m = re.search(r"SOURCE_ORDER:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\((.*?)\)", text, re.S)
    if not m:
        _die("weaknesses.py SOURCE_ORDER not found — the reader moved, update the harvest")
    names = re.findall(r'"([a-z\-]+)"', m.group(1))
    req = re.search(r"SOURCE_REQUIRED:\s*dict\[str,\s*bool\]\s*=\s*\{(.*?)\}", text, re.S)
    required = dict(re.findall(r'"([a-z\-]+)":\s*(True|False)', req.group(1))) if req else {}
    for name in names:
        nodes[f"weakness:{name}"] = {
            "kind": "weakness",
            "source": "files/anatomy/bone/weaknesses.py",
            "required": required.get(name) == "True",
        }


# ── harvest: daemons (launchd labels are declared as role-default values;
#    the resume plist is the one template with a literal filename) ─────────


def harvest_daemons(nodes: dict) -> None:
    labels: set[str] = set()
    for pattern in ("roles/*/defaults/main.yml", "default.config.yml"):
        for path in sorted(REPO.glob(pattern)):
            for line in path.read_text(encoding="utf-8").splitlines():
                lm = re.match(r'(\w+):\s*"(eu\.thisisait\.nos\.[a-z.\-]+)"', line.strip())
                if lm and "legacy" not in lm.group(1):
                    labels.add(lm.group(2))
    for path in sorted(REPO.glob("templates/eu.thisisait.nos.*.plist.j2")):
        labels.add(path.name.removesuffix(".plist.j2"))
    for label in sorted(labels):
        nodes[f"daemon:{label}"] = {"kind": "daemon", "source": "launchd label (role defaults)"}


# ── harvest: services ─────────────────────────────────────────────────────


def harvest_services(nodes: dict) -> None:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    for svc in doc.get("services") or []:
        if isinstance(svc, dict) and svc.get("id"):
            nodes[f"service:{svc['id']}"] = {
                "kind": "service",
                "source": "state/manifest.yml",
                "stack": svc.get("stack"),
                "category": svc.get("category"),
                "install_flag": svc.get("install_flag"),
            }


# ── edges: validate declarations, derive structure ────────────────────────


def _cron_minute(schedule: str | None) -> int | None:
    parts = (schedule or "").split()
    if len(parts) != 5 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    return int(parts[1]) * 60 + int(parts[0])


def compile_declared(raw_edges: list, nodes: dict) -> list[dict]:
    edges = []
    for consumer, dep, src in raw_edges:
        if not isinstance(dep, dict):
            _die(f"{consumer} ({src}): depends_on entry is not a mapping: {dep!r}")
        if True in dep or "on" in dep:
            # YAML 1.1: a bare `on:` key parses as boolean True. The field is
            # `upstream:` for exactly this reason — refuse the trap loudly.
            _die(f"{consumer} ({src}): depends_on uses `on:` — YAML 1.1 parses that "
                 f"key as boolean True; the field is `upstream:`")
        on = dep.get("upstream")
        kind = dep.get("kind")
        if kind == "mutex":
            _die(f"{consumer} ({src}): kind: mutex is refused on depends_on — "
                 f"declare `claims:` on the node; the graph derives the pairs (§2a)")
        if kind not in EDGE_KINDS:
            _die(f"{consumer} ({src}): unknown edge kind {kind!r} (allowed: {EDGE_KINDS})")
        if on not in nodes:
            _die(f"{consumer} ({src}): depends_on names {on!r}, which resolves to no "
                 f"declared node — a graph lying at birth")
        edge = {
            "from": on,
            "to": consumer,
            "kind": kind,
            "measured": _iso(dep.get("measured")),
        }
        if kind in ("data", "trigger"):
            via = str(dep.get("via") or "").strip()
            if kind == "data" and not via:
                _die(f"{consumer} ({src}): data edge from {on} names no artifact (via:) — "
                     f"schedule adjacency with better clothes")
            edge["via"] = via or None
        if kind == "data":
            edge["expects"] = dep.get("expects", "succeeded")
            up = nodes[on]
            if (edge["expects"] == "succeeded" and up.get("findings_exit_codes")
                    and "on_findings" not in dep):
                _die(f"{consumer} ({src}): upstream {on} declares findings_exit_codes "
                     f"{up['findings_exit_codes']} — the edge must say whether a findings "
                     f"exit satisfies it (on_findings: proceed|block)")
            if "on_findings" in dep:
                edge["on_findings"] = dep["on_findings"]
        if kind == "temporal":
            if dep.get("margin_min") is None:
                _die(f"{consumer} ({src}): temporal edge from {on} carries no margin_min — "
                     f"run tools/anatomy-measure-margins.py")
            schedules = dep.get("schedules")
            expect = [nodes[on].get("schedule"), nodes[consumer].get("schedule")]
            if schedules != expect:
                _die(f"{consumer} ({src}): temporal edge schedules {schedules!r} != current "
                     f"cron pair {expect!r} — a schedule changed without re-measuring; "
                     f"run tools/anatomy-measure-margins.py --stamp")
            edge["margin_min"] = dep["margin_min"]
            edge["schedules"] = schedules
            # temporal debt (§1.4 col 4): what the DECLARED budgets permit
            um, dm = _cron_minute(expect[0]), _cron_minute(expect[1])
            if um is not None and dm is not None:
                gap = (dm - um) % 1440
                up = nodes[on]
                declared_margin = gap - (up.get("jitter_min") or 0) \
                    - (up.get("max_runtime_s") or 0) / 60.0
                edge["gap_min"] = gap
                edge["declared_margin_min"] = round(declared_margin, 1)
                edge["can_invert"] = declared_margin <= 0
        edges.append(edge)
    return edges


def derive_structural(nodes: dict) -> list[dict]:
    edges = []
    pulse_daemon = "daemon:eu.thisisait.nos.pulse"
    if pulse_daemon in nodes:
        for nid, n in nodes.items():
            if n["kind"] == "pulse" and not n["paused"]:
                edges.append({
                    "from": pulse_daemon,
                    "to": nid,
                    "kind": "trigger",
                    "via": "list_due_jobs dispatch (files/anatomy/pulse/pulse/daemon.py)",
                    "derived": "daemon-dispatch",
                })
    return edges


def derive_mutex(nodes: dict) -> list[dict]:
    by_resource: dict[str, list[str]] = {}
    for nid, n in nodes.items():
        for c in n.get("claims") or []:
            by_resource.setdefault(c, []).append(nid)
    edges = []
    for resource, members in sorted(by_resource.items()):
        rid = f"resource:{resource}"
        nodes.setdefault(rid, {"kind": "resource", "source": "derived from claims"})
        members.sort()
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                edges.append({
                    "from": a, "to": b, "kind": "mutex",
                    "resource": resource, "derived": "claims",
                })
    return edges


def ensure_capability_resources(nodes: dict, edges: list[dict]) -> None:
    for e in edges:
        for end in ("from", "to"):
            nid = e[end]
            if nid.startswith("resource:") and nid not in nodes:
                nodes[nid] = {"kind": "resource", "source": "derived from judge-sets requires"}


# ── cycles ────────────────────────────────────────────────────────────────


def find_cycle(edges: list[dict], kinds: set[str]) -> list[str] | None:
    adj: dict[str, list[str]] = {}
    for e in edges:
        if e["kind"] in kinds:
            adj.setdefault(e["from"], []).append(e["to"])
    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[str, int] = {}
    stack_path: list[str] = []

    def dfs(u: str) -> list[str] | None:
        colour[u] = GREY
        stack_path.append(u)
        for v in adj.get(u, []):
            if colour.get(v, WHITE) == GREY:
                return stack_path[stack_path.index(v):] + [v]
            if colour.get(v, WHITE) == WHITE:
                got = dfs(v)
                if got:
                    return got
        stack_path.pop()
        colour[u] = BLACK
        return None

    for u in sorted(adj):
        if colour.get(u, WHITE) == WHITE:
            got = dfs(u)
            if got:
                return got
    return None


# ── build ─────────────────────────────────────────────────────────────────


def build() -> dict:
    nodes: dict[str, dict] = {}
    raw: list = []
    harvest_pulse(nodes, raw)
    harvest_judges(nodes, edges := [])
    harvest_weaknesses(nodes)
    harvest_daemons(nodes)
    harvest_services(nodes)

    declared = compile_declared(raw, nodes)
    structural = derive_structural(nodes)
    mutex = derive_mutex(nodes)
    ensure_capability_resources(nodes, edges)
    all_edges = declared + edges + structural + mutex

    # Per-kind cycles are a compile error (§2c-2): there is no legitimate
    # same-night cycle in a cron estate.
    for kind in EDGE_KINDS:
        cyc = find_cycle(all_edges, {kind})
        if cyc:
            _die(f"cycle through {kind} edges: {' -> '.join(cyc)}")

    # A union-kind cycle is a real feedback loop crossing a night boundary
    # (e.g. the corpus-diff halt). Flagged for human eyes, never auto-refused.
    warnings = []
    union = find_cycle([e for e in all_edges if e["kind"] != "mutex"], set(EDGE_KINDS))
    if union:
        warnings.append("union-kind cycle (feedback loop, review-not-refuse): "
                        + " -> ".join(union))

    all_edges.sort(key=lambda e: (e["kind"], e["from"], e["to"]))
    counts = {"nodes": len(nodes), "edges": len(all_edges)}
    for k in ("pulse", "judge", "gateset", "weakness", "daemon", "service", "resource"):
        counts[f"nodes_{k}"] = sum(1 for n in nodes.values() if n["kind"] == k)
    for k in EDGE_KINDS + ("mutex",):
        counts[f"edges_{k}"] = sum(1 for e in all_edges if e["kind"] == k)

    return {
        "version": 1,
        "generated_by": "tools/anatomy-graph-gen.py",
        "doctrine": "docs/archive/nos-anatomy-graph.md",
        "counts": counts,
        "warnings": warnings,
        "nodes": {k: nodes[k] for k in sorted(nodes)},
        "edges": all_edges,
    }


def render(graph: dict) -> str:
    return json.dumps(graph, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="compile state/anatomy-graph.json")
    ap.add_argument("--check", action="store_true", help="exit 1 if the artifact is stale")
    args = ap.parse_args()
    text = render(build())
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print("anatomy-graph: STALE — regenerate with tools/anatomy-graph-gen.py",
                  file=sys.stderr)
            return 1
        print(f"anatomy-graph current ({json.loads(text)['counts']['nodes']} nodes, "
              f"{json.loads(text)['counts']['edges']} edges)")
        return 0
    TARGET.write_text(text, encoding="utf-8")
    c = json.loads(text)["counts"]
    print(f"wrote {TARGET.relative_to(REPO)} ({c['nodes']} nodes, {c['edges']} edges)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
