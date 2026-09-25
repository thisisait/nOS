#!/usr/bin/env python3
"""caddy-wording-coverage — static coverage of files/anatomy/ears/wording.yml
against the frozen opcode registry in cortex-opcodes.ts.

WHY. jeff.md: 'an opcode with no wording refuses the whole chain rather than
speaking syntax'. Correct, but it means a caddy turn can fail for two very
different reasons — the MODEL picked the wrong chain, or nobody wrote the
sentence for a valid opcode+operand pair the model picked correctly. Tuning the
model for a wording gap is fixing the wrong thing. This computes the second
number BEFORE any model runs: pure text over two files already on disk, no
resident model, no KEAP call, no network.

WHAT COUNTS AS COVERED. The verbaliser needs BOTH halves and it fails closed in
EVERY declared language, so a pair (opcode, namespace) is covered only when
wording.yml has the opcode under `opcodes:` and the namespace under
`namespaces:`, each with a non-empty string for every entry in `languages:`.
An opcode whose registry entry allows `min: 0` operands is also checked bare.

USAGE
  caddy-wording-coverage.py                 whole registry, plain text
  caddy-wording-coverage.py --json          same, machine-readable
  caddy-wording-coverage.py --fixture f.yml only the pairs f.yml expects
  caddy-wording-coverage.py --self-test     inline fixtures, no real files

Exit 0 iff coverage is 100% for the scope checked — usable as a CI gate on
every wording.yml change (agents-evals shape: must not regress silently when a
namespace or opcode is added upstream).

Fixture format — a YAML or JSON list, `operand_prefix` optional (bare operand):
  - {opcode: get,  operand_prefix: tax}
  - {opcode: rank}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml  # already installed estate-wide; hand-rolling a YAML reader is not laziness

REPO = Path(__file__).resolve().parent.parent
WORDING = REPO / "files/anatomy/ears/wording.yml"
OPCODES_TS = REPO / "files/anatomy/cortex/server/cortex-opcodes.ts"

# The registry is a frozen `as const` literal (decision D2), so text extraction is
# enough and a TS parser would be a dependency bought for nothing.
# ponytail: regex over the literal; if CORTEX_OPCODES ever stops being a flat
# literal, shell out to `tsx -e 'console.log(JSON.stringify(...))'` instead.
_OPCODE_RE = re.compile(
    r"name:\s*'([a-z][a-z0-9-]*)'.*?"
    r"operands:\s*\{\s*min:\s*(\d+),\s*max:\s*\d+,\s*namespaces:\s*\[([^\]]*)\]",
    re.S,
)


def parse_registry(text: str) -> dict[str, dict]:
    """{opcode: {"min": int, "namespaces": [...]}} from the frozen TS literal."""
    body = text.split("export const CORTEX_OPCODES", 1)
    if len(body) != 2:
        raise SystemExit("cortex-opcodes.ts: CORTEX_OPCODES literal not found")
    ops = {}
    for name, min_operands, ns in _OPCODE_RE.findall(body[1]):
        ops[name] = {
            "min": int(min_operands),
            "namespaces": re.findall(r"'([a-z]+)'", ns),
        }
    if not ops:
        raise SystemExit("cortex-opcodes.ts: no opcodes parsed")
    return ops


def parse_wording(text: str) -> tuple[list[str], set[str], set[str]]:
    """(languages, opcodes with full wording, namespaces with full wording)."""
    doc = yaml.safe_load(text) or {}
    langs = list(doc.get("languages") or [])
    if not langs:
        raise SystemExit("wording.yml: no `languages:` declared")

    def complete(section: str) -> set[str]:
        entries = doc.get(section) or {}
        return {
            key
            for key, val in entries.items()
            if isinstance(val, dict)
            and all(isinstance(val.get(l), str) and val[l].strip() for l in langs)
        }

    return langs, complete("opcodes"), complete("namespaces")


def registry_pairs(registry: dict[str, dict]) -> list[tuple[str, str | None]]:
    """Every (opcode, namespace) the grammar can actually produce. `None` is the
    bare form, legal only where the registry allows zero operands."""
    pairs = []
    for name, spec in sorted(registry.items()):
        if spec["min"] == 0:
            pairs.append((name, None))
        pairs.extend((name, ns) for ns in spec["namespaces"])
    return pairs


def load_fixture(path: Path) -> list[tuple[str, str | None]]:
    raw = path.read_text()
    items = json.loads(raw) if path.suffix == ".json" else yaml.safe_load(raw)
    if not isinstance(items, list):
        raise SystemExit(f"{path}: expected a list of {{opcode, operand_prefix}}")
    out = []
    for item in items:
        if not isinstance(item, dict) or "opcode" not in item:
            raise SystemExit(f"{path}: entry without an `opcode` key: {item!r}")
        out.append((item["opcode"], item.get("operand_prefix")))
    return out


def check(pairs, registry, said_ops, said_ns) -> dict:
    """A pair is missing if either half has no wording. Pairs the registry does
    not permit are reported separately: that is a broken FIXTURE, not a wording
    gap, and conflating them is the same mistake this tool exists to stop."""
    covered, missing, invalid = [], [], []
    for opcode, ns in pairs:
        if opcode not in registry:
            invalid.append({"opcode": opcode, "operand_prefix": ns, "why": "unknown opcode"})
            continue
        spec = registry[opcode]
        if ns is None and spec["min"] > 0:
            invalid.append({"opcode": opcode, "operand_prefix": ns, "why": "opcode requires an operand"})
            continue
        if ns is not None and ns not in spec["namespaces"]:
            invalid.append({"opcode": opcode, "operand_prefix": ns, "why": f"{opcode} does not accept {ns}:"})
            continue
        gaps = []
        if opcode not in said_ops:
            gaps.append(f"opcodes.{opcode}")
        if ns is not None and ns not in said_ns:
            gaps.append(f"namespaces.{ns}")
        entry = {"opcode": opcode, "operand_prefix": ns}
        if gaps:
            missing.append({**entry, "missing": gaps})
        else:
            covered.append(entry)
    total = len(covered) + len(missing)
    return {
        "checked": total,
        "covered": len(covered),
        "coverage_pct": round(100.0 * len(covered) / total, 1) if total else 100.0,
        "missing": missing,
        "invalid": invalid,
    }


def render(result: dict, langs: list[str], scope: str) -> str:
    lines = [
        f"caddy wording coverage — scope: {scope}, languages: {', '.join(langs)}",
        f"  {result['covered']}/{result['checked']} opcode+operand pairs speakable "
        f"({result['coverage_pct']}%)",
    ]
    if result["missing"]:
        lines.append("  MISSING wording (these refuse the whole chain):")
        for m in result["missing"]:
            pair = f"{m['opcode']}({m['operand_prefix']}:)" if m["operand_prefix"] else f"{m['opcode']}()"
            lines.append(f"    {pair:<24} -> {', '.join(m['missing'])}")
    if result["invalid"]:
        lines.append("  NOT IN THE GRAMMAR (fixture bug, not a wording gap):")
        for i in result["invalid"]:
            lines.append(f"    {i['opcode']}({i['operand_prefix'] or ''}) -> {i['why']}")
    lines.append("  OK" if not result["missing"] else "  GAP")
    return "\n".join(lines)


def self_test() -> None:
    reg_ts = """
export const CORTEX_OPCODES = [
  { name: 'get', summary: 'x',
    operands: { min: 1, max: 1, namespaces: ['tax', 'db'] },
    params: {}, mutating: false, since: 1 },
  { name: 'rank', summary: 'y',
    operands: { min: 0, max: 1, namespaces: ['tax'] },
    params: {}, mutating: false, since: 1 },
] as const satisfies readonly CortexOpcodeSpec[];
"""
    registry = parse_registry(reg_ts)
    assert registry == {
        "get": {"min": 1, "namespaces": ["tax", "db"]},
        "rank": {"min": 0, "namespaces": ["tax"]},
    }, registry

    full = """
languages: [cs, en]
opcodes:
  get:  {cs: "přečte {operand}", en: "read {operand}"}
  rank: {cs: "seřadí", en: "rank"}
namespaces:
  tax: {cs: "uzel {id}", en: "node {id}"}
  db:  {cs: "databázi {id}", en: "the database {id}"}
"""
    langs, ops, ns = parse_wording(full)
    assert langs == ["cs", "en"] and ops == {"get", "rank"} and ns == {"tax", "db"}

    pairs = registry_pairs(registry)
    assert pairs == [("get", "tax"), ("get", "db"), ("rank", None), ("rank", "tax")], pairs

    r = check(pairs, registry, ops, ns)
    assert r["coverage_pct"] == 100.0 and not r["missing"], r

    # Gap 1: a namespace present in the registry but absent from the table.
    gap_ns = full.replace('  db:  {cs: "databázi {id}", en: "the database {id}"}\n', "")
    _, ops2, ns2 = parse_wording(gap_ns)
    r = check(pairs, registry, ops2, ns2)
    assert r["covered"] == 3 and r["coverage_pct"] == 75.0, r
    assert r["missing"] == [{"opcode": "get", "operand_prefix": "db", "missing": ["namespaces.db"]}], r

    # Gap 2: half a language is not coverage — the verbaliser fails closed in each.
    half = full.replace('rank: {cs: "seřadí", en: "rank"}', 'rank: {cs: "seřadí", en: ""}')
    _, ops3, _ = parse_wording(half)
    assert ops3 == {"get"}, ops3
    r = check(pairs, registry, ops3, ns)
    assert r["coverage_pct"] == 50.0, r

    # Gap 3: an opcode missing entirely takes every one of its pairs down.
    r = check(pairs, registry, set(), ns)
    assert r["covered"] == 0 and r["coverage_pct"] == 0.0, r

    # A fixture pair the grammar forbids is INVALID, never counted as a gap.
    r = check([("get", "svc"), ("rank", None), ("nope", "tax"), ("get", None)], registry, ops, ns)
    assert r["checked"] == 1 and r["coverage_pct"] == 100.0, r
    assert [i["opcode"] for i in r["invalid"]] == ["get", "nope", "get"], r["invalid"]

    # Example fixture, in the shape report-chain-planning-bench will emit.
    example = [{"opcode": "get", "operand_prefix": "tax"}, {"opcode": "rank"}]
    r = check([(e["opcode"], e.get("operand_prefix")) for e in example], registry, ops, ns)
    assert r["coverage_pct"] == 100.0, r

    print("self-test ok")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixture", type=Path, help="YAML/JSON list of {opcode, operand_prefix}")
    ap.add_argument("--wording", type=Path, default=WORDING)
    ap.add_argument("--opcodes", type=Path, default=OPCODES_TS)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        self_test()
        return 0

    registry = parse_registry(args.opcodes.read_text())
    langs, said_ops, said_ns = parse_wording(args.wording.read_text())

    if args.fixture:
        pairs, scope = load_fixture(args.fixture), f"fixture {args.fixture.name}"
    else:
        pairs, scope = registry_pairs(registry), "whole registry"

    result = check(pairs, registry, said_ops, said_ns)
    result["scope"] = scope
    result["languages"] = langs
    result["opcodes_in_registry"] = len(registry)
    result["opcodes_without_any_wording"] = sorted(set(registry) - said_ops)

    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result, langs, scope))
    return 0 if not result["missing"] and not result["invalid"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
