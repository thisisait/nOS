#!/usr/bin/env python3
"""Read-only KEAP recall for agents.

Wraps tools/keap-semantic-search.py (the client) and tools/keap-recall-queries.py
(the known-query set). Returns ranked passages with node ids. Refuses to write.

  tools/cortex-query.py "is cortex up"
  tools/cortex-query.py --fixture tests/fixtures/cortex-query-recall.json
  tools/cortex-query.py --json "cortex health"

Exit 0 ranked hits · 1 empty recall · 2 refuse / unreachable.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys
import urllib.error

REPO = pathlib.Path(__file__).resolve().parent.parent
WRITE_FLAGS = ("--write", "--rw", "--post", "--mutate")


class EmptyRecall(RuntimeError):
    """Empty recall is not a pass (broken token / drained embeddings)."""


def _load(filename: str, name: str):
    path = REPO / "tools" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_refusal(argv: list[str]) -> str | None:
    for a in argv:
        if a in WRITE_FLAGS or a.upper() == "POST":
            return f"REFUSING: cortex-query is read-only (got {a!r})"
    return None


def passages_from_hits(hits: list[dict]) -> list[dict]:
    out = []
    for i, row in enumerate(hits, 1):
        node_id = row.get("id") or row.get("nodeId") or row.get("node_id") or ""
        title = row.get("title") or row.get("name") or ""
        passage = (row.get("description") or row.get("text") or "").strip()
        out.append({
            "rank": i,
            "node_id": node_id,
            "title": title,
            "passage": passage,
            "score": row.get("score"),
            "kind": row.get("kind"),
        })
    return out


def grade(hits: list[dict], expect: list[str]) -> str:
    """First expect-ref that lands in the ranked passages. Empty is red."""
    passages = hits if (hits and "node_id" in (hits[0] or {})) else passages_from_hits(hits)
    if not passages:
        raise EmptyRecall("empty recall is not a pass")
    titles = {p.get("title") or "" for p in passages}
    ids = {p.get("node_id") or "" for p in passages}
    for ref in expect:
        kind, _, value = ref.partition(":")
        if kind == "title" and value in titles:
            return ref
        if kind == "node" and value in ids:
            return ref
    raise EmptyRecall(f"none of {expect} in ranked passages")


def recall_hits(query: str, fixture_path: pathlib.Path | None = None) -> list[dict]:
    """Live recall via keap-semantic-search; fixture only when KEAP is unreachable.

    An empty live answer is returned as empty (grade() turns it red). The
    recorded fixture is NOT a substitute for a drained corpus.
    """
    search = _load("keap-semantic-search.py", "keap_semantic_search")
    try:
        raw = search.fetch_results(query, limit=5)
    except (urllib.error.URLError, OSError, TimeoutError):
        if fixture_path is None:
            raise
        raw = json.loads(pathlib.Path(fixture_path).read_text(encoding="utf-8"))["results"]
    return passages_from_hits(raw)


def known_expect(query: str) -> list[str] | None:
    """Expect-refs if this query is in the SKILLS.md recall set, else None.

    Arbitrary questions still run; the set is the smoke/benchmark, not a
    whitelist. A miss on a known query is red; a miss on an unknown query
    is just ranked passages, provided the list is not empty.
    """
    recall = _load("keap-recall-queries.py", "keap_recall_queries")
    for case in recall.build()["cases"]:
        if case["q"] == query:
            return case["expect"]
    return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    refused = write_refusal(argv)
    if refused:
        print(refused, file=sys.stderr)
        return 2

    ap = argparse.ArgumentParser(description="Read-only KEAP recall (RO bearer).")
    ap.add_argument("query", nargs="?", help="natural-language query")
    ap.add_argument("--fixture", type=pathlib.Path, help="recorded recall JSON when KEAP is unreachable")
    ap.add_argument("--json", action="store_true", help="print ranked passages as JSON")
    ap.add_argument("--limit", type=int, default=5, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.fixture and not args.query:
        doc = json.loads(args.fixture.read_text(encoding="utf-8"))
        query = doc["q"]
        expect = doc.get("expect") or known_expect(query)
        hits = passages_from_hits(doc["results"])
    else:
        query = args.query
        if not query:
            ap.error("query required (or --fixture with a recorded q)")
        expect = known_expect(query)
        if args.fixture:
            # Force the fixture path only as fallback inside recall_hits.
            hits = recall_hits(query, fixture_path=args.fixture)
        else:
            search = _load("keap-semantic-search.py", "keap_semantic_search")
            try:
                hits = passages_from_hits(search.fetch_results(query, limit=args.limit))
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                print(f"REFUSING: KEAP recall unreachable ({exc})", file=sys.stderr)
                return 2

    if not hits:
        print("REFUSING: empty recall is not a pass", file=sys.stderr)
        return 1
    matched = None
    if expect:
        try:
            matched = grade(hits, expect)
        except EmptyRecall as exc:
            print(f"REFUSING: {exc}", file=sys.stderr)
            return 1

    if args.json:
        print(json.dumps({"q": query, "matched": matched, "passages": hits},
                         indent=2, ensure_ascii=False))
        return 0
    print(f"“{query}” — {len(hits)} passage(s)  matched {matched}", file=sys.stderr)
    for p in hits:
        print(f"  {p['rank']}. [{p.get('kind') or '?'}] {p['node_id']}  {p['title']}")
        if p["passage"]:
            text = p["passage"].replace("\n", " ")
            print(f"      {text[:160]}{'…' if len(text) > 160 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
