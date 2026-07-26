#!/usr/bin/env python3
"""keap-embed-sync — feed the KEAP (cortex) libSQL vector corpus.

Pulse job (keap-base plugin). The trust-boundary split: the SERVER decides
WHAT to embed (GET /agent/v1/embeddings/pending assembles canonical texts +
content_hash diff); this host-side job decides HOW — it calls the
host-loopback Ollama (a container on gated_net cannot) and POSTs vectors
back. Idempotent: no pending items -> no-op, exit 0.

── FAN-OUT (S2, docs/plans/cortex-corpus-parallel.md §4) ─────────────────
Two SEQUENTIAL passes, incumbent first, within one slot. Each pass is
self-contained: its own /pending diff, its own Ollama calls, its own
POST-back. The pending sets differ per store by construction, so there is
nothing to share and nothing to coordinate.

  - NO SHARED VECTOR CACHE. A (model, content_hash) cache would halve the
    Ollama time and would not hide divergence (divergent text hashes
    differently, so it would miss). It is rejected anyway: independence is
    the PRODUCT of this stage, and two pipelines that share a cache are
    one pipeline with two outputs. Cost is not the constraint — a full
    pass measures 17.7 s.
  - NOTHING IS TUNED. The organ ships float8/max_neighbors=20 and KEAP
    runs the plain default index. That asymmetry IS the S3 experiment;
    do not "fix" it here or there.
  - COMPARABILITY IS ASSERTED, NOT ASSUMED. Before either pass, every
    target must declare the SAME (model, dim). The wire protocol already
    carries both — /pending returns them and the job embeds with whatever
    the server declared — so one assertion turns a silent incomparability
    (two corpora embedded by different models, compared as if they were
    one experiment) into a visible halt. Dim is additionally fixed at 768
    by `embeddings.vector F32_BLOB(768)` on both sides.
  - THE INCUMBENT DECIDES THE EXIT CODE. A parallel target that is down or
    fails mid-pass is reported and skipped; only KEAP's failure is fatal.

Env:
  KEAP_API_URL          default http://127.0.0.1:8091
  KEAP_AGENT_TOKEN_RW   required (write scope for POST /agent/v1/embeddings)
  CORTEX_API_URL        set to also embed the cortex organ (e.g.
                        http://127.0.0.1:8098); empty = single target
  CORTEX_AGENT_TOKEN_RW the organ's OWN rw token — a DIFFERENT env name
                        holding a DIFFERENT secret, on purpose (§2.1)
  OLLAMA_URL            default http://127.0.0.1:11434
  KEAP_EMBED_BATCH      default 32 (texts per Ollama call)

Exit codes: 0 synced/no-op, 1 config error, 2 the INCUMBENT or Ollama was
unreachable, 3 the targets disagree on (model, dim) — nothing was embedded.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

TOKEN_RW = os.environ.get("KEAP_AGENT_TOKEN_RW", "")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
BATCH = int(os.environ.get("KEAP_EMBED_BATCH", "32"))
PAGE = 200  # pending items fetched per round-trip (server caps at 500)


class Target:
    def __init__(self, name: str, base: str, token: str, incumbent: bool):
        self.name = name
        self.base = base.rstrip("/")
        self.token = token
        self.incumbent = incumbent
        self.model: str | None = None
        self.dim: int | None = None
        self.upserted = 0
        self.error = ""


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


def build_targets() -> list[Target]:
    targets = [
        Target("keap", os.environ.get("KEAP_API_URL", "http://127.0.0.1:8091"), TOKEN_RW, incumbent=True)
    ]
    url = os.environ.get("CORTEX_API_URL", "").strip()
    token = os.environ.get("CORTEX_AGENT_TOKEN_RW", "").strip()
    if url and token:
        targets.append(Target("cortex", url, token, incumbent=False))
    elif url and not token:
        print(
            "keap-embed-sync: CORTEX_API_URL is set but CORTEX_AGENT_TOKEN_RW is empty — "
            "the cortex corpus is NOT being embedded",
            file=sys.stderr,
        )
    return targets


def probe(t: Target) -> bool:
    """Fetch (model, dim) without embedding anything. limit=0 keeps it a probe."""
    try:
        data = http_json(f"{t.base}/agent/v1/embeddings/pending?limit=0", token=t.token)["data"]
    except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
        t.error = f"unreachable: {exc}"
        return False
    t.model, t.dim = data.get("model"), data.get("dim")
    return True


def run_pass(t: Target) -> bool:
    """One target's full embed pass. Returns success; records its own error."""
    total_upserted = 0
    grand_total = None
    while True:
        try:
            pending = http_json(f"{t.base}/agent/v1/embeddings/pending?limit={PAGE}", token=t.token)["data"]
        except (urllib.error.URLError, OSError, KeyError) as exc:
            t.error = f"unreachable mid-pass: {exc}"
            return False

        items, model, dim = pending["items"], pending["model"], pending["dim"]
        if grand_total is None:
            grand_total = pending["total"]
        if not items:
            t.upserted = total_upserted
            print(f"keap-embed-sync[{t.name}]: corpus current (upserted {total_upserted}, pruned {pending['pruned']})")
            return True

        for i in range(0, len(items), BATCH):
            chunk = items[i : i + BATCH]
            try:
                vectors = embed_batch([it["text"] for it in chunk], model)
            except (urllib.error.URLError, OSError, RuntimeError) as exc:
                # Ollama is SHARED. Its failure is not this target's fault and is
                # not evidence about this target's health — it is reported as its
                # own condition so the nightly diff does not read a missing
                # embedding pass as a divergent corpus.
                t.error = f"ollama embed failed: {exc}"
                t.upserted = total_upserted
                return False
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
            try:
                res = http_json(f"{t.base}/agent/v1/embeddings", payload, token=t.token)
            except (urllib.error.URLError, OSError, KeyError) as exc:
                t.error = f"vector POST failed: {exc}"
                t.upserted = total_upserted
                return False
            total_upserted += res["data"]["upserted"]
            print(f"keap-embed-sync[{t.name}]: upserted {total_upserted}/{grand_total} ({model})")


def main() -> int:
    if not TOKEN_RW:
        print("keap-embed-sync: KEAP_AGENT_TOKEN_RW not set", file=sys.stderr)
        return 1

    targets = build_targets()
    incumbent = targets[0]

    live = [t for t in targets if probe(t)]
    if incumbent not in live:
        print(f"keap-embed-sync: incumbent unreachable: {incumbent.error}", file=sys.stderr)
        return 2
    for t in targets:
        if t not in live:
            print(f"keap-embed-sync: target '{t.name}' skipped — {t.error}", file=sys.stderr)

    # ── the comparability gate ───────────────────────────────────────────────
    # Refuse the WHOLE run, not just the odd target: two corpora embedded by
    # different models are not two indexes over one corpus, and every recall
    # number produced from them afterwards would be measuring the wrong thing
    # while looking entirely healthy.
    if len(live) > 1:
        shapes = {(t.model, t.dim) for t in live}
        if len(shapes) > 1:
            detail = "; ".join(f"{t.name}={t.model}/{t.dim}" for t in live)
            print(
                "keap-embed-sync: targets disagree on (model, dim) — refusing the run so the two "
                f"corpora are never embedded incomparably: {detail}",
                file=sys.stderr,
            )
            return 3

    # Sequential, incumbent first. One Ollama, one pass at a time — no
    # contention, and a slow parallel pass can never delay the incumbent's.
    failures = []
    for t in live:
        if not run_pass(t):
            failures.append(t)
            print(f"keap-embed-sync: target '{t.name}' FAILED — {t.error}", file=sys.stderr)

    summary = ", ".join(f"{t.name} +{t.upserted}" + ("" if t not in failures else " [FAILED]") for t in live)
    print(f"keap-embed-sync: {summary} (model {incumbent.model}, dim {incumbent.dim})")
    return 2 if incumbent in failures else 0


if __name__ == "__main__":
    sys.exit(main())
