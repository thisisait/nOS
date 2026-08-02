#!/usr/bin/env python3
"""keap-features-sync — compute the semantic-lens derived features for the KEAP
star-map. Sibling of keap-embed-sync, same trust split: the KEAP container owns
the embeddings but cannot reach Ollama; this host-side job has Ollama + numpy.

Pipeline (Option B — reuse the validated numpy compute, keep vectors host-side):
  1. GET /agent/v1/features/vectors      — the container's taxonomy embeddings
  2. embed the exemplar phrase-sets (axes config) via host-loopback Ollama
  3. project every node onto each difference-vector axis; centrality; k-means
  4. POST /agent/v1/features             — upsert node_features (GraphCanvas reads)

Positions are NEVER touched — features drive appearance only (U1 layout intact).
Design + validation: docs/archive/keap-semantic-lens.md.

Env (Pulse-rendered):
  KEAP_API_URL        default http://127.0.0.1:8091
  KEAP_AGENT_TOKEN_RO required (read: GET vectors)
  KEAP_AGENT_TOKEN_RW required (write: POST features)
  OLLAMA_URL          default http://127.0.0.1:11434
  KEAP_AXES_CONFIG    default <playbook>/tools/keap-semantic-lens/axes.json
  KEAP_FEATURES_K     default 12 (k-means texture facets)

Exit: 0 synced/no-op, 1 config error, 2 KEAP/Ollama unreachable, 3 numpy missing.
"""
from __future__ import annotations
import json, os, sys, urllib.request, urllib.error

API = os.environ.get("KEAP_API_URL", "http://127.0.0.1:8091").rstrip("/")
RO = os.environ.get("KEAP_AGENT_TOKEN_RO", "")
RW = os.environ.get("KEAP_AGENT_TOKEN_RW", "")
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
K = int(os.environ.get("KEAP_FEATURES_K", "12"))
_here = os.path.dirname(os.path.abspath(__file__))
AXES_CFG = os.environ.get("KEAP_AXES_CONFIG",
    os.path.normpath(os.path.join(_here, "..", "..", "..", "tools", "keap-semantic-lens", "axes.json")))


def http_json(url, body=None, token=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("content-type", "application/json")
    req.add_header("x-keap-agent", "keap-features-sync")
    if token:
        req.add_header("authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        out = json.loads(res.read().decode())
    # KEAP wraps success payloads in {success, data}; unwrap to the payload.
    return out.get("data", out) if isinstance(out, dict) else out


def main() -> int:
    if not RO or not RW:
        print("keap-features-sync: KEAP_AGENT_TOKEN_RO/RW required", file=sys.stderr); return 1
    try:
        import numpy as np
    except ImportError:
        print("keap-features-sync: numpy not available on the host python", file=sys.stderr); return 3
    try:
        cfg = json.load(open(AXES_CFG))
    except OSError as e:
        print(f"keap-features-sync: axes config unreadable ({AXES_CFG}): {e}", file=sys.stderr); return 1
    model = cfg.get("model", "nomic-embed-text")
    axes = cfg["axes"]

    # 1. node embeddings from the container
    try:
        vres = http_json(f"{API}/agent/v1/features/vectors", token=RO)
    except urllib.error.URLError as e:
        print(f"keap-features-sync: KEAP unreachable: {e}", file=sys.stderr); return 2
    items = vres.get("vectors", [])
    if not items:
        print("keap-features-sync: no taxonomy embeddings yet (run keap-embed-sync first) — no-op"); return 0
    ids = [it["id"] for it in items]
    V = np.array([it["vector"] for it in items], dtype=np.float32)
    V /= (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)

    # 2. exemplar axes via Ollama (difference vectors)
    def embed(texts):
        try:
            out = http_json(f"{OLLAMA}/api/embed", {"model": model, "input": texts}, timeout=300)
        except urllib.error.URLError as e:
            print(f"keap-features-sync: Ollama unreachable: {e}", file=sys.stderr); sys.exit(2)
        a = np.array(out["embeddings"], dtype=np.float32)
        return a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)
    axis_vecs = {}
    for name, ax in axes.items():
        a = embed(ax["positive"]).mean(0) - embed(ax["negative"]).mean(0)
        axis_vecs[name] = a / (np.linalg.norm(a) + 1e-9)
    proj = {name: (V @ a) for name, a in axis_vecs.items()}

    # 3. centrality + k-means (seeded k-means++)
    S = V @ V.T
    cent = (S.sum(1) - 1.0) / max(len(ids) - 1, 1)
    rng = np.random.default_rng(42); N = len(ids)
    cx = [int(rng.integers(N))]; d2 = np.maximum(1.0 - (V @ V[cx[0]]), 0.0)
    for _ in range(min(K, N) - 1):
        nxt = int(rng.choice(N, p=d2 / d2.sum())); cx.append(nxt)
        d2 = np.maximum(np.minimum(d2, 1.0 - (V @ V[nxt])), 0.0)
    C = V[cx].copy()
    for _ in range(50):
        assign = np.argmax(V @ C.T, axis=1)
        newC = np.array([V[assign == k].mean(0) if np.any(assign == k) else C[k] for k in range(len(cx))])
        newC /= (np.linalg.norm(newC, axis=1, keepdims=True) + 1e-9)
        if np.allclose(newC, C, atol=1e-5): C = newC; break
        C = newC
    cluster = np.argmax(V @ C.T, axis=1)

    # 4. POST features (canonical four axes get their own columns; all go in axis_json)
    feats = []
    for i, nid in enumerate(ids):
        row = {"node_id": nid, "centrality": round(float(cent[i]), 4), "cluster": int(cluster[i]),
               "axis_json": json.dumps({name: round(float(proj[name][i]), 4) for name in axes})}
        for name in ("abstractness", "scale", "formalness", "dynamism"):
            if name in proj: row[name] = round(float(proj[name][i]), 4)
        feats.append(row)
    res = http_json(f"{API}/agent/v1/features", {"model": model, "features": feats}, token=RW)
    print(f"keap-features-sync: upserted {res.get('upserted', 0)} node features ({len(axes)} axes, k={len(cx)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
