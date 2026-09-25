#!/usr/bin/env python3
"""Caddy entity-collision bench — code-oracle grader.

Roadmap row: caddy-entity-collision-bench (parent: caddy-entity-resolve).

Grades a resolver against state/fixtures/caddy-entity-collision/cases.yml and
buckets every case into the three outcomes caddy-entity-resolve names:

  WRONG_SINGLE    resolver committed to ONE entity and it was not the right
                  one -- including committing to one entity on a case the
                  fixture labels genuinely ambiguous. A report built from the
                  wrong client's books. THE ONLY BUCKET THAT GATES A RELEASE.
  CORRECT_SINGLE  one right answer existed, resolver returned exactly it.
  SURFACED_TOP_N  the case was genuinely ambiguous and the resolver surfaced a
                  top-N containing every live possibility, and stopped.

Plus one residual, reported but NOT gating:

  OTHER           not confidently wrong and not right either -- an over-
                  cautious top-N on a case that had a single right answer, or
                  a top-N on an ambiguous case that dropped a live candidate.
                  Three buckets cannot hold these; folding them into
                  WRONG_SINGLE would blunt the gate, so they are counted apart.

Exit status: 1 if WRONG_SINGLE > 0 (or --max-wrong exceeded), else 0.

Usage:
    tools/caddy-entity-collision-check.py                  # stub resolver
    tools/caddy-entity-collision-check.py --resolver pkg.mod:resolve
    tools/caddy-entity-collision-check.py --self-test      # bucket-logic test

stdlib only, except PyYAML -- already a hard dependency of ~every tool in
tools/ and the format every fixture under state/fixtures/ is written in.
(A .json fixture would keep this pure-stdlib; the repo convention won.)
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "state" / "fixtures" / "caddy-entity-collision" / "cases.yml"

WRONG_SINGLE = "WRONG_SINGLE"
CORRECT_SINGLE = "CORRECT_SINGLE"
SURFACED_TOP_N = "SURFACED_TOP_N"
OTHER = "OTHER"


# ─────────────────────────────────────────────────────────────────────────────
# RESOLVER PLUGIN POINT
#
# A resolver is any callable with this signature:
#
#     resolve(query: str, candidates: list[dict]) -> dict
#
#   query       the spoken/typed turn, verbatim.
#   candidates  the fixture's candidate entities, each {id, label, note}.
#               A real resolver fans out read-only over tax:/rel: instead of
#               being handed this list; the list is the bench's stand-in for
#               "what the fan-out could have reached", so a resolver under
#               test may ignore it entirely and return its own ids.
#
#   returns     {"match": "<entity id>"}      -- committed to one entity, or
#               {"top_n": ["<id>", ...]}      -- ambiguous, surfaced and stopped
#
# Point --resolver at "module.path:callable" to grade the real one once
# caddy-entity-resolve's fan-out exists.
# ─────────────────────────────────────────────────────────────────────────────


def stub_resolver(query: str, candidates: list[dict]) -> dict:
    """NOT A RESOLVER. Exists only to exercise this checker end to end.

    Naive token-overlap over the candidate labels; commits when one candidate
    wins outright, surfaces the tied leaders otherwise. Its scores are not a
    claim about anything -- any bucket counts it produces are a test of the
    GRADER, never a quality measurement of entity resolution.

    ponytail: token overlap, no diacritics folding, no aliases, no dates.
    The real resolver replaces it wholesale; do not grow this.
    """
    words = {w.strip(".,").lower() for w in query.split() if len(w.strip(".,")) > 2}
    scored = []
    for c in candidates:
        hay = f"{c['id']} {c.get('label', '')}".lower()
        scored.append((sum(1 for w in words if w in hay), c["id"]))
    best = max(s for s, _ in scored)
    leaders = [cid for s, cid in scored if s == best]
    if best == 0:
        return {"top_n": [c["id"] for c in candidates][:3]}
    if len(leaders) == 1:
        return {"match": leaders[0]}
    return {"top_n": leaders[:3]}


def load_resolver(spec: str | None):
    if not spec:
        return stub_resolver
    mod_name, _, attr = spec.partition(":")
    if not attr:
        raise SystemExit(f"--resolver wants 'module.path:callable', got {spec!r}")
    return getattr(importlib.import_module(mod_name), attr)


def classify(case: dict, result: dict) -> tuple[str, str]:
    """Bucket one (case, resolver result) pair. Returns (bucket, reason).

    This function is the bench. Everything else is plumbing.
    """
    if not isinstance(result, dict) or ("match" in result) == ("top_n" in result):
        return OTHER, "resolver returned neither exactly one 'match' nor one 'top_n'"

    truth = case["truth"]
    ambiguous = truth == "ambiguous"

    if "match" in result:
        if ambiguous:
            # The defect shape the roadmap row exists for: a genuinely
            # ambiguous turn silently resolved to one entity.
            return WRONG_SINGLE, f"committed to {result['match']} on a genuinely ambiguous case"
        if result["match"] == truth:
            return CORRECT_SINGLE, ""
        return WRONG_SINGLE, f"committed to {result['match']}, truth is {truth}"

    top_n = list(result["top_n"])
    if not ambiguous:
        hit = truth in top_n
        return OTHER, (
            f"surfaced top-N on a case with one right answer ({'truth included' if hit else 'truth NOT in top-N'})"
        )
    missing = [e for e in case["expect_top_n"] if e not in top_n]
    if missing:
        return OTHER, f"top-N dropped live candidate(s): {', '.join(missing)}"
    return SURFACED_TOP_N, ""


def run(resolver, cases: list[dict]) -> list[tuple[dict, str, str]]:
    out = []
    for case in cases:
        try:
            result = resolver(case["query"], case["candidates"])
        except Exception as exc:  # a resolver that throws is not a wrong match
            out.append((case, OTHER, f"resolver raised {type(exc).__name__}: {exc}"))
            continue
        bucket, reason = classify(case, result)
        out.append((case, bucket, reason))
    return out


def report(graded, label: str) -> int:
    counts = {b: 0 for b in (WRONG_SINGLE, CORRECT_SINGLE, SURFACED_TOP_N, OTHER)}
    for _, bucket, _ in graded:
        counts[bucket] += 1

    print(f"caddy entity-collision bench — {len(graded)} cases — resolver: {label}\n")

    # Loudest first: this is the bucket that gates a release.
    print(f"  !! WRONG SINGLE MATCH : {counts[WRONG_SINGLE]}   <-- RELEASE GATE")
    for case, bucket, reason in graded:
        if bucket == WRONG_SINGLE:
            print(f"     !! {case['id']}: {reason}")
            print(f"        query: {case['query']!r}")
    print()
    print(f"     correct single    : {counts[CORRECT_SINGLE]}")
    print(f"     surfaced top-N    : {counts[SURFACED_TOP_N]}")
    print(f"     other (non-gating): {counts[OTHER]}")
    for case, bucket, reason in graded:
        if bucket == OTHER:
            print(f"        - {case['id']}: {reason}")
    return counts[WRONG_SINGLE]


# ─────────────────────────────────────────────────────────────────────────────
# Self-test of the bucket logic itself, on SYNTHETIC resolver outputs -- not
# the stub resolver, whose behaviour is irrelevant to whether classify() is
# right. Run: tools/caddy-entity-collision-check.py --self-test
# ─────────────────────────────────────────────────────────────────────────────

def self_test() -> None:
    definite = {"truth": "tax:party/a", "candidates": [], "query": "q"}
    ambig = {
        "truth": "ambiguous",
        "expect_top_n": ["tax:party/a", "tax:party/b"],
        "candidates": [],
        "query": "q",
    }

    def b(case, result):
        return classify(case, result)[0]

    # definite-truth cases
    assert b(definite, {"match": "tax:party/a"}) == CORRECT_SINGLE
    assert b(definite, {"match": "tax:party/b"}) == WRONG_SINGLE
    assert b(definite, {"top_n": ["tax:party/a", "tax:party/b"]}) == OTHER
    assert b(definite, {"top_n": ["tax:party/b"]}) == OTHER

    # genuinely-ambiguous cases
    assert b(ambig, {"match": "tax:party/a"}) == WRONG_SINGLE, "right-ish guess is still a silent commit"
    assert b(ambig, {"match": "tax:party/b"}) == WRONG_SINGLE
    assert b(ambig, {"top_n": ["tax:party/a", "tax:party/b"]}) == SURFACED_TOP_N
    assert b(ambig, {"top_n": ["tax:party/b", "tax:party/a", "tax:party/c"]}) == SURFACED_TOP_N
    assert b(ambig, {"top_n": ["tax:party/a"]}) == OTHER, "dropping a live candidate is not a clean surface"

    # malformed resolver output never counts as a wrong single match
    assert b(definite, {}) == OTHER
    assert b(definite, {"match": "tax:party/a", "top_n": ["tax:party/a"]}) == OTHER
    assert b(definite, "tax:party/a") == OTHER

    # a throwing resolver lands in OTHER, not the gate
    def boom(_q, _c):
        raise RuntimeError("no network here")

    assert run(boom, [dict(definite, id="x")])[0][1] == OTHER

    # the fixture file itself is well-formed against the schema the grader reads
    for case in load_cases():
        assert case["truth"] == "ambiguous" or any(
            c["id"] == case["truth"] for c in case["candidates"]
        ), f"{case['id']}: truth is not one of its own candidates"
        if case["truth"] == "ambiguous":
            ids = {c["id"] for c in case["candidates"]}
            assert case["expect_top_n"], f"{case['id']}: ambiguous case needs expect_top_n"
            assert set(case["expect_top_n"]) <= ids, f"{case['id']}: expect_top_n has a non-candidate"
        for c in case["candidates"]:
            assert c["id"].startswith(("tax:", "rel:")), f"{case['id']}: {c['id']} is out of resolver scope"

    print("self-test OK — bucket classification + fixture schema")


def load_cases() -> list[dict]:
    return yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))["cases"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--resolver", help="'module.path:callable'; default is the STUB resolver")
    ap.add_argument("--fixture", type=Path, default=FIXTURE)
    ap.add_argument("--max-wrong", type=int, default=0, help="wrong single matches tolerated before exit 1")
    ap.add_argument("--json", action="store_true", help="machine-readable per-case buckets")
    ap.add_argument("--self-test", action="store_true", help="test the bucket logic and exit")
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return 0

    cases = yaml.safe_load(args.fixture.read_text(encoding="utf-8"))["cases"]
    resolver = load_resolver(args.resolver)
    label = args.resolver or "STUB (not a quality measurement)"
    graded = run(resolver, cases)

    if args.json:
        print(json.dumps([{"id": c["id"], "bucket": b, "reason": r} for c, b, r in graded], indent=2))
        wrong = sum(1 for _, b, _ in graded if b == WRONG_SINGLE)
    else:
        wrong = report(graded, label)
        if not args.resolver:
            print("\nNOTE: the stub resolver is naive token overlap. These counts test"
                  "\n      the GRADER, not entity-resolution quality.")

    return 1 if wrong > args.max_wrong else 0


if __name__ == "__main__":
    sys.exit(main())
