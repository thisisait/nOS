#!/usr/bin/env python3
"""PoC: derive interpretable semantic axes from KEAP node embeddings via
difference-vectors between exemplars, project every node, and eyeball whether
the axes are meaningful (top/bottom nodes per axis). Also centrality (hub-ness).
Nothing is stored — this only validates the concept on the real corpus."""
import json, urllib.request
import numpy as np

EMB = "/Users/pazny/.claude/jobs/4100771d/tmp/emb.jsonl"
OLLAMA = "http://127.0.0.1:11434/api/embed"
MODEL = "nomic-embed-text"

# node embeddings
ids, vecs = [], []
for line in open(EMB):
    line = line.strip()
    if not line: continue
    d = json.loads(line); ids.append(d["id"]); vecs.append(d["v"])
V = np.array(vecs, dtype=np.float32)
V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)   # unit-normalize
print(f"loaded {len(ids)} node embeddings, dim {V.shape[1]}")

# names from the live graph (for interpreting results)
req = urllib.request.Request("http://127.0.0.1:8091/api/graph",
    headers={"X-Authentik-Username": "operator", "X-Authentik-Groups": "nos-admins"})
NAME = {n["id"]: n.get("name", "?") for n in json.load(urllib.request.urlopen(req)).get("data", {}).get("nodes", [])}

def embed(texts):
    body = json.dumps({"model": MODEL, "input": texts}).encode()
    r = urllib.request.Request(OLLAMA, data=body, headers={"content-type": "application/json"})
    e = json.load(urllib.request.urlopen(r, timeout=120))["embeddings"]
    a = np.array(e, dtype=np.float32)
    return a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)

# axis = mean(positive pole) - mean(negative pole), then unit-normalize.
# "high" score = toward the positive pole named first.
AXES = {
  "abstractness": (
     ["abstract theory", "pure abstract concept", "formal abstraction", "general theoretical principle"],
     ["concrete tangible example", "specific physical object", "practical hands-on application", "real-world instance"]),
  "scale(macro>micro)": (
     ["cosmic astronomical scale", "vast galactic universe", "planetary global system"],
     ["subatomic microscopic scale", "tiny molecular particle", "atomic quantum level"]),
  "formal(vs empirical)": (
     ["formal mathematical logic", "axiomatic deductive proof", "abstract symbolic system"],
     ["empirical experimental observation", "measured evidence from data", "laboratory field study"]),
  "dynamic(vs static)": (
     ["dynamic changing process evolving over time", "flow motion and transformation"],
     ["static unchanging fixed structure", "stable permanent configuration"]),
}
axis_vecs = {}
for name, (pos, neg) in AXES.items():
    a = embed(pos).mean(0) - embed(neg).mean(0)
    axis_vecs[name] = a / (np.linalg.norm(a) + 1e-9)

def show(name, scores, k=8):
    order = np.argsort(scores)
    print(f"\n=== {name} ===")
    print("  TOP (positive pole):")
    for i in order[::-1][:k]:
        print(f"    {scores[i]:+.3f} {ids[i]:16} {NAME.get(ids[i], ids[i])[:34]}")
    print("  BOTTOM (negative pole):")
    for i in order[:k]:
        print(f"    {scores[i]:+.3f} {ids[i]:16} {NAME.get(ids[i], ids[i])[:34]}")

for name, a in axis_vecs.items():
    show(name, V @ a)

# centrality: mean cosine similarity to all other nodes (hub-ness)
S = V @ V.T
cent = (S.sum(1) - 1.0) / (len(ids) - 1)
order = np.argsort(cent)[::-1]
print("\n=== centrality (mean cosine to corpus — hubs) TOP ===")
for i in order[:10]:
    print(f"    {cent[i]:.3f} {ids[i]:16} {NAME.get(ids[i], ids[i])[:34]}")
print("  (low centrality = outliers/frontier)")
for i in order[-6:]:
    print(f"    {cent[i]:.3f} {ids[i]:16} {NAME.get(ids[i], ids[i])[:34]}")
