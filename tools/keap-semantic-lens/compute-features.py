#!/usr/bin/env python3
"""Compute the full per-node derived-features set for the semantic lens — the
phase-3 compute core, developed + validated offline against the live embedding
corpus before it is ported into the container's /features/recompute endpoint.

Per node it produces a handful of scalars (NOT the 768-dim vector): projection on
each semantic axis, centrality (hub-ness), and a k-means cluster id (texture
facet). Writes node-features.json and prints a validation view (cluster contents,
axis extremes) so the axes/clusters can be eyeballed for coherence.

Needs: emb.jsonl (see emb-dump.mjs), numpy, host Ollama (nomic-embed-text) at :11434.
"""
import json, urllib.request, sys, os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EMB = os.environ.get("EMB", "/Users/pazny/.claude/jobs/4100771d/tmp/emb.jsonl")
OLLAMA = "http://127.0.0.1:11434/api/embed"
MODEL = "nomic-embed-text"
K = 12                       # texture-facet clusters
SEED = 42

# ── node embeddings ──────────────────────────────────────────────────────────
ids, vecs = [], []
for line in open(EMB):
    line = line.strip()
    if line:
        d = json.loads(line); ids.append(d["id"]); vecs.append(d["v"])
V = np.array(vecs, dtype=np.float32)
V /= (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
N, DIM = V.shape

req = urllib.request.Request("http://127.0.0.1:8091/api/graph",
    headers={"X-Authentik-Username": "operator", "X-Authentik-Groups": "nos-admins"})
NAME = {n["id"]: n.get("name", "?") for n in json.load(urllib.request.urlopen(req)).get("data", {}).get("nodes", [])}

# ── semantic axes (versioned exemplar config) ────────────────────────────────
AXES = {
  "abstractness": (["abstract theory", "pure abstract concept", "formal abstraction", "general theoretical principle"],
                   ["concrete tangible example", "specific physical object", "practical hands-on application", "real-world instance"]),
  "scale":        (["cosmic astronomical scale", "vast galactic universe", "planetary global system"],
                   ["subatomic microscopic scale", "tiny molecular particle", "atomic quantum level"]),
  "formalness":   (["formal mathematical logic", "axiomatic deductive proof", "abstract symbolic system"],
                   ["empirical experimental observation", "measured evidence from data", "laboratory field study"]),
  "dynamism":     (["dynamic changing process evolving over time", "flow motion and transformation"],
                   ["static unchanging fixed structure", "stable permanent configuration"]),
}
def embed(texts):
    body = json.dumps({"model": MODEL, "input": texts}).encode()
    r = urllib.request.Request(OLLAMA, data=body, headers={"content-type": "application/json"})
    a = np.array(json.load(urllib.request.urlopen(r, timeout=120))["embeddings"], dtype=np.float32)
    return a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)
axis_vecs = {name: (lambda a: a / (np.linalg.norm(a) + 1e-9))(embed(pos).mean(0) - embed(neg).mean(0))
             for name, (pos, neg) in AXES.items()}
proj = {name: V @ a for name, a in axis_vecs.items()}   # per-node scalar per axis

# ── centrality (hub-ness) = mean cosine to corpus ────────────────────────────
S = V @ V.T
cent = (S.sum(1) - 1.0) / (N - 1)

# ── k-means (numpy, seeded, k-means++ init) ──────────────────────────────────
rng = np.random.default_rng(SEED)
cx = [int(rng.integers(N))]
d2 = np.maximum(1.0 - (V @ V[cx[0]]), 0.0)
for _ in range(K - 1):
    p = d2 / d2.sum()
    nxt = int(rng.choice(N, p=p)); cx.append(nxt)
    d2 = np.maximum(np.minimum(d2, 1.0 - (V @ V[nxt])), 0.0)
C = V[cx].copy()
for _ in range(50):
    assign = np.argmax(V @ C.T, axis=1)
    newC = np.array([V[assign == k].mean(0) if np.any(assign == k) else C[k] for k in range(K)])
    newC /= (np.linalg.norm(newC, axis=1, keepdims=True) + 1e-9)
    if np.allclose(newC, C, atol=1e-5): C = newC; break
    C = newC
cluster = np.argmax(V @ C.T, axis=1)

# ── output the derived-features dataset ──────────────────────────────────────
feats = []
for i, nid in enumerate(ids):
    feats.append({"id": nid, "centrality": round(float(cent[i]), 4), "cluster": int(cluster[i]),
                  **{name: round(float(proj[name][i]), 4) for name in AXES}})
out = os.path.join(HERE, "node-features.json")
json.dump({"model": MODEL, "axes": list(AXES), "k": K, "features": feats}, open(out, "w"), indent=1)
print(f"wrote {out}: {len(feats)} nodes × ({len(AXES)} axes + centrality + cluster)")

# ── validation view: cluster coherence (top-by-centrality per cluster) ───────
print("\n=== k-means clusters (texture facets) — representative members ===")
for k in range(K):
    idx = np.where(cluster == k)[0]
    if len(idx) == 0: continue
    top = idx[np.argsort(cent[idx])[::-1][:6]]
    names = ", ".join(NAME.get(ids[i], ids[i])[:20] for i in top)
    print(f"  c{k:2} (n={len(idx):3}): {names}")
