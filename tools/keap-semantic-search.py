#!/usr/bin/env python3
"""keap-semantic-search — semantic search over the estate's knowledge, from the shell.

A thin READER over KEAP's shipped hybrid search (GET /agent/v1/search/semantic):
the query is embedded (Ollama nomic-embed-text) and matched with vector_top_k over
the libsql-native `embeddings` (F32_BLOB 768) plus lexical + graph legs, all
server-side. This tool adds nothing to the store — it USES the libsql vectors that
already exist, so there is no second embedder and no drift (the host-side row
embedding was rejected for exactly that; row search is KEAP-side, see the
keap-row-vector-search roadmap row).

Covers what KEAP embeds today: taxonomy / capture / note / object. DataTable ROWS
(invoices, parties) are NOT embedded yet — they light up here once KEAP adds a row
kind to its embed sources.

  tools/keap-semantic-search.py "unpaid invoices over 30 days"
  tools/keap-semantic-search.py "účetní závěrka" --limit 5 --kind taxonomy
  tools/keap-semantic-search.py "..." --json      # raw results for a pipe

Exit 0 ok · 2 KEAP unreadable.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
from digest_absorb import ro_token  # noqa: E402  (shared RO token resolver)
from keap_api import proxy_header  # noqa: E402

ENDPOINT = "http://127.0.0.1:8091/agent/v1/search/semantic"


def fetch_results(query: str, limit: int = 10, kind: str | None = None) -> list[dict]:
    """GET /agent/v1/search/semantic. Raises OSError/URLError if KEAP is unreachable.

    An empty list is a real answer (broken token / drained embeddings), not an
    outage — callers that treat [] as success are the defect cortex-query pins.
    """
    params: dict[str, str | int] = {"q": query, "limit": limit}
    if kind:
        params["kind"] = kind
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    hdr = {"Authorization": f"Bearer {ro_token()}", **proxy_header()}
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read() or b"{}")
    return (data.get("data") or {}).get("results") or data.get("results") or []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="natural-language query")
    ap.add_argument("--limit", type=int, default=10, help="max results (default 10)")
    ap.add_argument("--kind", help="filter to one kind (taxonomy|capture|note|object)")
    ap.add_argument("--json", action="store_true", help="print raw result JSON")
    args = ap.parse_args()

    try:
        results = fetch_results(args.query, args.limit, args.kind)
    except (urllib.error.URLError, OSError) as exc:
        print(f"REFUSING: KEAP semantic search unreachable ({exc})", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0

    legs: list[str] = []
    seen: set[str] = set()
    for r in results:
        for leg in r.get("legs") or []:
            if leg not in seen:
                seen.add(leg)
                legs.append(leg)
    print(f"“{args.query}” — {len(results)} hit(s)  [legs: "
          f"{', '.join(legs) or 'n/a'}]", file=sys.stderr)
    for r in results:
        kind = r.get("kind", "?")
        name = r.get("name") or r.get("title") or r.get("id", "?")
        path = r.get("path")
        desc = (r.get("description") or "").strip().replace("\n", " ")
        print(f"  [{kind:8}] {name}" + (f"   · {path}" if path else ""))
        if desc:
            print(f"             {desc[:140]}{'…' if len(desc) > 140 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
