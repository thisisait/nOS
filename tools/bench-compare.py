#!/usr/bin/env python3
"""Pair two tools/iris-bench.py --out runs case by case: what they differ on, and whether it shows.

A claim like "the cortex plan path beats plain tool calling" is measured only when the runs differ
on ONE axis (plan path, model digest, nOS commit, primer, grammar, registry) and the paired flips
are counted: a = cases only A passed, b = cases only B passed, exact two-sided McNemar on (a, b).
A NO-DATA case on either side is left out, never counted as a fail. Two runs that differ on no
axis are a repeatability check: a single flip means the bench is not deterministic at that config.

Usage:
    tools/bench-compare.py tools.json cortex.json        # A vs B
    tools/bench-compare.py run1.json run2.json --json    # same config twice: repeatable?

Exit: 0 B better / repeatable, 1 A better / not repeatable / no measured difference, 2 confounded.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ALPHA = 0.05
TOP = ("plan_path", "primer_sha256", "grammar_sha256", "registry_hash")


def mcnemar(a: int, b: int) -> float:
    """Exact two-sided McNemar: 2 * P(X <= min(a, b)), X ~ Binom(a + b, 1/2), capped at 1."""
    n = a + b
    if n == 0:
        return 1.0
    k = min(a, b)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def _models(run: dict) -> list:
    return sorted((m.get("name"), m.get("digest")) for m in (run.get("provenance") or {}).get("models") or [])


def axes(a: dict, b: dict) -> list[str]:
    """The axes two runs differ on; a value the run did not record (None) still counts as a value."""
    out = [k for k in TOP if a.get(k) != b.get(k)]
    if (a.get("provenance") or {}).get("nos_commit") != (b.get("provenance") or {}).get("nos_commit"):
        out.append("nos_commit")
    if _models(a) != _models(b):
        out.append("models")
    return sorted(out)


def compare(a: dict, b: dict) -> dict:
    ca = {c["id"]: c for c in a.get("cases") or []}
    cb = {c["id"]: c for c in b.get("cases") or []}
    both = [i for i in ca if i in cb and not ca[i].get("no_data") and not cb[i].get("no_data")]
    left_out = sorted(set(ca) ^ set(cb) | {i for i in set(ca) & set(cb) if i not in both})
    a_only = sorted(i for i in both if ca[i]["pass"] and not cb[i]["pass"])
    b_only = sorted(i for i in both if cb[i]["pass"] and not ca[i]["pass"])
    p = mcnemar(len(a_only), len(b_only))
    diff = axes(a, b)
    if not diff:
        verdict = "not repeatable" if a_only or b_only else "repeatable"
    elif len(diff) > 1:
        verdict = "confounded"
    elif p < ALPHA:
        verdict = "B better" if len(b_only) > len(a_only) else "A better"
    else:
        verdict = "no measured difference"
    return {"axes": diff, "paired": len(both), "a_pass": sum(ca[i]["pass"] for i in both),
            "b_pass": sum(cb[i]["pass"] for i in both), "a_only": len(a_only), "b_only": len(b_only),
            "a_only_ids": a_only, "b_only_ids": b_only, "left_out": left_out, "p": p, "verdict": verdict}


EXIT = {"B better": 0, "repeatable": 0, "A better": 1, "not repeatable": 1, "no measured difference": 1, "confounded": 2}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--json", action="store_true")
    o = ap.parse_args(argv)
    r = compare(*(json.loads(Path(p).read_text(encoding="utf-8")) for p in (o.a, o.b)))
    if o.json:
        print(json.dumps(r, indent=2))
    else:
        print(f"axes: {', '.join(r['axes']) or 'none (repeatability check)'}")
        print(f"paired {r['paired']} · A {r['a_pass']} · B {r['b_pass']} · only A {r['a_only']} · only B {r['b_only']} "
              f"· McNemar p={r['p']:.4f} · left out {len(r['left_out'])}")
        for side in ("a", "b"):
            if r[f"{side}_only_ids"]:
                print(f"  only {side.upper()}: {', '.join(r[f'{side}_only_ids'])}")
        print(r["verdict"])
    return EXIT[r["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
