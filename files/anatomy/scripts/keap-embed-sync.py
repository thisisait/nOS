#!/usr/bin/env python3
"""keap-embed-sync — feed the KEAP (cortex) libSQL vector corpus.

Pulse job (keap-base plugin). The trust-boundary split: KEAP's container
decides WHAT to embed (GET /agent/v1/embeddings/pending assembles canonical
texts + content_hash diff); this host-side job decides HOW — it calls the
host-loopback Ollama (the container on gated_net cannot) and POSTs vectors
back. Idempotent: no pending items -> no-op, exit 0.

Env (Pulse-rendered):
  KEAP_API_URL          default http://127.0.0.1:8091
  KEAP_AGENT_TOKEN_RW   required (write scope for POST /agent/v1/embeddings)
  OLLAMA_URL            default http://127.0.0.1:11434
  KEAP_EMBED_BATCH      default 32 (texts per Ollama call)

Exit codes: 0 synced/no-op, 1 config error, 2 KEAP/Ollama unreachable.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

KEAP_API_URL = os.environ.get("KEAP_API_URL", "http://127.0.0.1:8091").rstrip("/")
TOKEN_RW = os.environ.get("KEAP_AGENT_TOKEN_RW", "")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
BATCH = int(os.environ.get("KEAP_EMBED_BATCH", "32"))
PAGE = 200  # pending items fetched per KEAP round-trip (server caps at 500)


def http_json(url: str, body: dict | None = None, token: str | None = None, timeout: int = 60) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("content-type", "application/json")
    req.add_header("x-keap-agent", "keap-embed-sync")
    if token:
        req.add_header("authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode())


def embed_batch(texts: list[str], model: str) -> list[list[float]]:
    out = http_json(f"{OLLAMA_URL}/api/embed", {"model": model, "input": texts}, timeout=300)
    embeddings = out.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise RuntimeError(f"ollama returned {len(embeddings or [])} vectors for {len(texts)} texts")
    return embeddings


def main() -> int:
    if not TOKEN_RW:
        print("keap-embed-sync: KEAP_AGENT_TOKEN_RW not set", file=sys.stderr)
        return 1

    total_upserted = 0
    grand_total = None
    while True:
        try:
            pending = http_json(
                f"{KEAP_API_URL}/agent/v1/embeddings/pending?limit={PAGE}", token=TOKEN_RW
            )["data"]
        except (urllib.error.URLError, OSError, KeyError) as exc:
            print(f"keap-embed-sync: KEAP unreachable: {exc}", file=sys.stderr)
            return 2

        items, model, dim = pending["items"], pending["model"], pending["dim"]
        if grand_total is None:
            grand_total = pending["total"]
        if not items:
            print(f"keap-embed-sync: corpus current (upserted {total_upserted}, pruned {pending['pruned']})")
            return 0

        for i in range(0, len(items), BATCH):
            chunk = items[i : i + BATCH]
            try:
                vectors = embed_batch([it["text"] for it in chunk], model)
            except (urllib.error.URLError, OSError, RuntimeError) as exc:
                print(f"keap-embed-sync: ollama embed failed: {exc}", file=sys.stderr)
                return 2
            payload = {
                "model": model,
                "dim": dim,
                "items": [
                    {
                        "kind": it["kind"],
                        "refId": it["refId"],
                        "contentHash": it["contentHash"],
                        "vector": vec,
                    }
                    for it, vec in zip(chunk, vectors)
                ],
            }
            res = http_json(f"{KEAP_API_URL}/agent/v1/embeddings", payload, token=TOKEN_RW)
            total_upserted += res["data"]["upserted"]
            print(f"keap-embed-sync: upserted {total_upserted}/{grand_total} ({model})")


if __name__ == "__main__":
    sys.exit(main())
