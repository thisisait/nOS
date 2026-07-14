#!/usr/bin/env python3
"""Transform the fable ontology-review output into per-domain import bundles.

Reads state/fable/ontology-review-output.json (fable's L3 pillars + L4 blocks
for the 8 empty core-physics branches 01.01.03-.10) and emits one
deploy/<key>-import.json per branch in the shape import-domain.mjs consumes:

    { importKey, actor, root:{id,parent,name,rootIsSeed},
      pillars:[{id,name,description,descriptionCs,
                blocks:[{slug,name,description,descriptionCs,explored,
                         brief:[{name,definition}]}]}],
      relations:[] }

Each root is an EXISTING seed L2 branch → rootIsSeed:true (pillars graft as ext
children directly under the named branch; ToE precedent proves ext-under-seed).
Pure file transformation — NO database access. Nothing is applied; the operator
reviews the bundles and runs the supervised import.

Usage: python3 tools/keap-fable-to-bundles.py [<fable-output.json>] [<app-deploy-dir>]
"""
import sys, json, os

FABLE = sys.argv[1] if len(sys.argv) > 1 else "state/fable/ontology-review-output.json"
DEPLOY = sys.argv[2] if len(sys.argv) > 2 else \
    "/Users/pazny/projects/knowledge-explorer-and-preserver/deploy"

# branch id → short import key (filename stem)
KEY = {
    "01.01.03": "phys-thermo",   "01.01.04": "phys-em",
    "01.01.05": "phys-relativity", "01.01.06": "phys-nuclear",
    "01.01.07": "phys-particle", "01.01.08": "phys-astro",
    "01.01.09": "phys-geo",      "01.01.10": "phys-biophys",
}

def branch_of(pillar_id):        # "01.01.03.01" -> "01.01.03"
    return ".".join(pillar_id.split(".")[:3])

fab = json.load(open(FABLE))
names = {d["branch_id"]: d["name"] for d in fab["priority_domains"]}
pillars_by_id = {p["id"]: p for p in fab["pillars"]}

# group pillars + blocks by branch
by_branch = {}
for p in fab["pillars"]:
    by_branch.setdefault(branch_of(p["id"]), {"pillars": {}, "blocks": {}})
    by_branch[branch_of(p["id"])]["pillars"][p["id"]] = p
for b in fab["new_blocks"]:
    br = branch_of(b["parent_pillar_id"])
    by_branch.setdefault(br, {"pillars": {}, "blocks": {}})
    by_branch[br]["blocks"].setdefault(b["parent_pillar_id"], []).append(b)

os.makedirs(DEPLOY, exist_ok=True)
summary = []
for branch, key in sorted(KEY.items()):
    grp = by_branch.get(branch, {"pillars": {}, "blocks": {}})
    pillars_out = []
    n_blocks = 0
    for pid in sorted(grp["pillars"]):          # sequential .01,.02… → index-aligned
        p = grp["pillars"][pid]
        blocks_out = []
        for b in grp["blocks"].get(pid, []):
            blocks_out.append({
                "slug": b["slug"], "name": b["name"],
                "description": b["description_en"],
                "descriptionCs": b["description_cs"],
                "explored": b.get("explored", "partially"),
                "brief": [{"name": c["name"], "definition": c["definition"]}
                          for c in b.get("brief_concepts", [])],
            })
        n_blocks += len(blocks_out)
        pillars_out.append({
            "id": pid, "name": p["name"],
            "description": p["description_en"],
            "descriptionCs": p["description_cs"],
            "blocks": blocks_out,
        })
    bundle = {
        "importKey": key,
        "actor": "agent:fable-import",
        "root": {"id": branch, "parent": "01.01",
                 "name": names.get(branch, branch), "rootIsSeed": True},
        "pillars": pillars_out,
        "relations": [],
    }
    out = os.path.join(DEPLOY, f"{key}-import.json")
    with open(out, "w") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=1)
    summary.append((key, branch, names.get(branch, branch), len(pillars_out), n_blocks))
    print(f"wrote {out}: {len(pillars_out)} pillars + {n_blocks} blocks")

tp = sum(s[3] for s in summary); tb = sum(s[4] for s in summary)
print(f"\n{len(summary)} bundles — {tp} pillars + {tb} blocks total")
print("operator run (after rc build): for each key, `docker exec iiab-keap-1 "
      "node deploy/<key>-import.json`; ONE `docker restart iiab-keap-1` at the end.")
