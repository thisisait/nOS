#!/usr/bin/env python3
"""Generate the raw-data bundle for the fable ontology-review pass.

Pulls the full taxonomy tree + typed relations from KEAP's graph API (loopback
+ forward-auth headers — NEVER host sqlite3 on the libSQL DB), then emits:
  - anchor: the L0-2 spine (id, name, level, description, childCount)
  - coverage: per top-level (L0) and L2 branch — #L3 pillars, #L4 blocks, total
    descendants, max depth, typed-relation degree  → spots "important but sparse"
  - exemplars: two fully-developed branches (physics 01.01, math 02.01.04) as the
    depth/quality bar
Writes deploy-style JSON to the path given as argv[1].
"""
import sys, json, urllib.request
from collections import defaultdict

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/fable-bundle.json"
BASE = "http://127.0.0.1:8091"

def graph():
    req = urllib.request.Request(
        BASE + "/api/graph?relations=all",
        headers={"X-Authentik-Username": "operator",
                 "X-Authentik-Groups": "nos-admins,nos-providers"})
    return json.load(urllib.request.urlopen(req))

g = graph()
# graph shape: data.nodes[], data.links[] (tree), data.relations[] (typed overlay)
d = g.get("data", g)
nodes = d["nodes"]
byid = {n["id"]: n for n in nodes}
def level(nid): return nid.count(".")            # "01"=0, "01.01"=1, ...
def top(nid): return nid.split(".")[0]
def l2(nid):
    p = nid.split("."); return ".".join(p[:3]) if len(p) >= 3 else nid

children = defaultdict(list)
for n in nodes:
    pid = n.get("parentId") or n.get("parent_id")
    if pid: children[pid].append(n["id"])

# relation degree per node
reldeg = defaultdict(int)
for r in d.get("relations", []):
    a = r.get("from") or r.get("from_id"); b = r.get("to") or r.get("to_id")
    reldeg[a] += 1; reldeg[b] += 1

def subtree_stats(root):
    l3 = l4 = tot = 0; maxd = 0; rel = 0
    stack = [(root, 0)]
    while stack:
        nid, dep = stack.pop()
        if nid != root:
            tot += 1; maxd = max(maxd, dep)
            if level(nid) == 3: l3 += 1
            if level(nid) == 4: l4 += 1
        rel += reldeg.get(nid, 0)
        for c in children.get(nid, []): stack.append((c, dep + 1))
    return dict(l3=l3, l4=l4, total=tot, maxDepth=maxd, relDegree=rel)

anchor = [dict(id=n["id"], name=n["name"], level=level(n["id"]),
              description=(n.get("description") or "")[:400],
              childCount=len(children.get(n["id"], [])))
          for n in nodes if level(n["id"]) <= 2]
anchor.sort(key=lambda x: x["id"])

# coverage: every L2 branch (the graftable level) + its top-level parent
l2_ids = sorted({l2(n["id"]) for n in nodes if level(n["id"]) >= 2})
coverage = []
for nid in l2_ids:
    n = byid.get(nid)
    if not n: continue
    s = subtree_stats(nid)
    coverage.append(dict(id=nid, name=n["name"], top=byid.get(top(nid), {}).get("name"),
                         description=(n.get("description") or "")[:200], **s))
coverage.sort(key=lambda x: (x["l4"], x["total"]))   # sparsest first

def expand(root):
    out = []
    stack = [root]
    while stack:
        nid = stack.pop()
        n = byid.get(nid)
        if n and nid != root:
            out.append(dict(id=nid, name=n["name"], level=level(nid),
                            description=(n.get("description") or "")[:300]))
        for c in children.get(nid, []): stack.append(c)
    out.sort(key=lambda x: x["id"]); return out

bundle = dict(
    meta=dict(totalNodes=len(nodes), anchorNodes=len(anchor), l2Branches=len(coverage),
              relations=len(d.get("relations", []))),
    anchor=anchor,
    coverage=coverage,
    exemplars=dict(physics_01_01=expand("01.01")[:40], math_02_01_04=expand("02.01.04")[:40]),
)
with open(OUT, "w") as f: json.dump(bundle, f, ensure_ascii=False, indent=1)
print("wrote", OUT)
print("meta:", json.dumps(bundle["meta"]))
print("sparsest 8 L2 branches (few L4 blocks):")
for c in coverage[:8]:
    print(f"  {c['id']:12} {c['name'][:34]:34} L3={c['l3']:2} L4={c['l4']:3} tot={c['total']:3} rel={c['relDegree']:3}  [{c['top']}]")
