#!/usr/bin/env python3
"""Convert a fable branches-authoring JSON (structured pillars+blocks for empty
seed L2 branches — the physics-style fill) into canonical ext-node records, and
merge them into the target canonical L1 file. Reusable for Earth Sciences,
Astronomy, and any future clean (no-catch-all) branch fill.

Input JSON shape:
  { "branches": [ { "branch_id": "01.04.01", "name": "Geology",
      "pillars": [ { "name": "...", "en": "...", "cs": "...",
        "blocks": [ { "name": "...", "en": "...", "cs": "...", "explored": "well",
                      "brief_concepts": [ {"name": "...", "definition": "..."} ] } ] } ] } ] }

Emits ext nodes under each seed branch: pillars 01.04.NN.MM (L3), blocks
01.04.NN.MM.KK (L4). Ordinals are 0-based insertion order; the block `brief` is
the description + a "### Concepts" list (same shape the importer built), so the
brief-xref lift + round-trip stay consistent. Node key order + 1-space indent +
trailing newline match dump.mjs so canonical stays byte-identical to a fresh dump.

Usage: python3 keap-branches-to-canonical.py <articles.json> <target-canonical.json>
"""
import json, sys

ART, TARGET = sys.argv[1], sys.argv[2]
art = json.load(open(ART))
doc = json.load(open(TARGET))

def pad(n): return f"{n:02d}"
def ext(nid, parent, name, ordinal, en, cs, brief=None):
    r = {"id": nid, "level": nid.count("."), "parentId": parent, "name": name,
         "zone": "votable", "ordinal": ordinal, "kind": "ext", "en": en}
    if cs: r["cs"] = cs
    if brief: r["brief"] = brief
    return r

existing = {n["id"] for n in doc["nodes"]}
added = 0
for br in art["branches"]:
    bid = br["branch_id"]
    for pi, p in enumerate(br["pillars"]):
        pid = f"{bid}.{pad(pi + 1)}"
        if pid in existing:
            print(f"skip existing pillar {pid}", file=sys.stderr); continue
        doc["nodes"].append(ext(pid, bid, p["name"], pi, p["en"], p.get("cs"))); added += 1
        for bi, b in enumerate(p["blocks"]):
            blid = f"{pid}.{pad(bi + 1)}"
            lines = [f"- **{c['name']}** — {c['definition']}" for c in b.get("brief_concepts", [])]
            brief = f"{b['en']}\n\n### Concepts\n" + "\n".join(lines) if lines else None
            doc["nodes"].append(ext(blid, pid, b["name"], bi, b["en"], b.get("cs"), brief)); added += 1

doc["nodes"].sort(key=lambda n: n["id"])
with open(TARGET, "w") as f:
    json.dump(doc, f, ensure_ascii=False, indent=1); f.write("\n")
print(f"merged {added} ext nodes into {TARGET} ({len(doc['nodes'])} total)")
