#!/usr/bin/env python3
"""Generate synthetic report-prepare training cases from SCHEMA ONLY.

report-chain-synthetic-training-data: there is no real usage history to train
report-prepare "muscle memory" on, and there should not be — early usage
history is real client data. So the cases are derived MECHANICALLY from the
two things that are locally machine-readable and carry no client rows:

  * state/keap-tables/*.table.yml          — DataTable definitions (names + columns)
  * files/anatomy/cortex/knowledge/ontology/relation-types.json
                                           — the `rel:` relation vocabulary
  * files/anatomy/cortex/server/cortex-opcodes.ts
                                           — the frozen opcode registry

DATA SAFETY: this reads table/column DEFINITIONS and a relation vocabulary.
It never opens a seed file, a fixture row, or anything under an importer's
input. Every client name it emits is obviously synthetic and generated here.

Output shape mirrors state/fixtures/consulting-firm/expected.yml — an answer
key keyed by case id, which report-chain-planning-bench's code oracle diffs
against the set of tables a model actually queried (superset-with-
justification = pass, missing = fail).

stdlib only — no PyYAML. The .table.yml files are read with narrow regexes
for `title:`/`key:` and the output YAML is emitted directly; both are flat
enough that a parser would be more code than the job.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TABLES_DIR = REPO / "state" / "keap-tables"
RELATION_TYPES = REPO / "files/anatomy/cortex/knowledge/ontology/relation-types.json"
OPCODES_TS = REPO / "files/anatomy/cortex/server/cortex-opcodes.ts"
DEFAULT_OUT = REPO / "state" / "fixtures" / "report-chain-synthetic"


# --------------------------------------------------------------------------
# schema sources (structure only — never a row)
# --------------------------------------------------------------------------

def load_tables() -> dict[str, set[str]]:
    """table slug -> set of column keys, from the .table.yml definitions."""
    tables = {}
    for path in sorted(TABLES_DIR.glob("*.table.yml")):
        text = path.read_text(encoding="utf-8")
        # only the `- { key: x, ... }` column rows; `key:` appears nowhere else
        # at column depth in these files.
        cols = set(re.findall(r"^\s*-\s*\{\s*key:\s*([a-z_]+)", text, re.M))
        tables[path.name[: -len(".table.yml")]] = cols
    return tables


def load_relations() -> set[str]:
    data = json.loads(RELATION_TYPES.read_text(encoding="utf-8"))
    return {t["type"] for t in data["types"]}


def load_opcodes() -> set[str]:
    text = OPCODES_TS.read_text(encoding="utf-8")
    # the registry entries are `name: 'get',` inside CORTEX_OPCODES.
    return set(re.findall(r"^\s*name:\s*'([a-z]+)',", text, re.M))


# --------------------------------------------------------------------------
# the report families
#
# Each is a SHAPE, not a query: which tables a correct report-prepare chain
# must touch, which relation edge ties the bundle, and the minimal ordered
# opcode chain that gets there. Operands are `table.column` or `rel:<type>`
# and are validated against the loaded schema before anything is written.
# --------------------------------------------------------------------------

REPORT_TYPES = {
    "ongoing-books": {
        "request": "prepare the ongoing report for client {name}",
        "relations": ["depends-on"],
        "chain": [
            ("resolve", "party.legal_name"),
            ("get", "account"),
            ("filter", "account.party"),
            ("get", "posting"),
            ("filter", "posting.account"),
            ("get", "journal-entry"),
            ("rank", "journal-entry.date"),
            ("map", "posting.amount"),
        ],
    },
    "receivables": {
        "request": "what does {name} still owe us — pull the receivables report",
        "relations": ["depends-on"],
        "chain": [
            ("resolve", "party.legal_name"),
            ("get", "invoice"),
            ("filter", "invoice.buyer"),
            ("get", "invoice-line"),
            ("filter", "invoice-line.invoice"),
            ("rank", "invoice.due_date"),
            ("map", "invoice.payable_amount"),
        ],
    },
    "vat-summary": {
        "request": "prepare the quarterly VAT summary for {name}",
        "relations": ["derived-from"],
        "chain": [
            ("resolve", "party.legal_name"),
            ("get", "invoice"),
            ("filter", "invoice.book_owner"),
            ("get", "invoice-line"),
            ("classify", "invoice.vat_regime"),
            ("map", "invoice.vat_breakdown"),
        ],
    },
    "party-registry": {
        "request": "check the registry and contact details we hold for {name}",
        "relations": ["defines"],
        "chain": [
            ("resolve", "party.slug"),
            ("get", "party-registry-status"),
            ("filter", "party-registry-status.party"),
            ("get", "party-tax-identity"),
            ("get", "party-address"),
            ("get", "party-contact"),
            ("classify", "party-registry-status.vat_reliability"),
        ],
    },
    "project-delivery": {
        "request": "prepare the delivery report on the {name} engagement",
        "relations": ["depends-on"],
        "chain": [
            ("resolve", "party.legal_name"),
            ("get", "kolben-project"),
            ("filter", "kolben-project.client"),
            ("get", "kolben-ticket"),
            ("filter", "kolben-ticket.project"),
            ("get", "kolben-time-entry"),
            ("get", "kolben-engineer"),
            ("map", "kolben-time-entry.hours"),
            ("rank", "kolben-ticket.priority"),
        ],
    },
    "print-throughput": {
        "request": "prepare the production report for {name}'s outstanding print orders",
        "relations": ["prerequisite-for"],
        "chain": [
            ("resolve", "party.legal_name"),
            ("get", "print-order"),
            ("filter", "print-order.customer"),
            ("get", "print-job"),
            ("filter", "print-job.order"),
            ("get", "print-job-step"),
            ("get", "print-material"),
            ("rank", "print-job-step.planned_start"),
        ],
    },
    "invoice-verify-queue": {
        "request": "what is still unverified on {name}'s books before we report",
        "relations": ["depends-on"],
        "chain": [
            ("resolve", "party.legal_name"),
            ("get", "invoice"),
            ("filter", "invoice.book_owner"),
            ("get", "pending-invoice-verify"),
            ("get", "invoice-review"),
            ("filter", "invoice.verified"),
            ("review", "invoice-review.slug"),
        ],
    },
}

# SYNTHETIC only. "Vzor"/"Vzorová" is Czech for "specimen/sample"; the suffixes
# are real Czech legal forms so the shape is realistic, the identity is not.
# Nothing here is read from a seed, a fixture, or any live table.
SYNTHETIC_NAMES = [
    "Firma Vzor s.r.o.",
    "Vzorová Dílna a.s.",
    "Ukázka Trading s.r.o.",
    "Model Podnik s.r.o.",
    "Testovací Sklad a.s.",
    "Zkušební Služby s.r.o.",
    "Vzorek Logistika s.r.o.",
    "Příkladná Výroba a.s.",
    "Demo Konzult s.r.o.",
    "Fiktivní Atelier s.r.o.",
]


def table_of(operand: str) -> str:
    return operand.split(".", 1)[0]


def generate(n: int) -> list[dict]:
    """N cases, cycling report type x synthetic name. Deterministic."""
    types = sorted(REPORT_TYPES)
    cases = []
    for i in range(n):
        slug = types[i % len(types)]
        spec = REPORT_TYPES[slug]
        name = SYNTHETIC_NAMES[(i // len(types)) % len(SYNTHETIC_NAMES)]
        cases.append({
            "id": f"{slug}-{i + 1:03d}",
            "report_type": slug,
            "request": spec["request"].format(name=name),
            "client": name,
            "tables": sorted({table_of(op) for _, op in spec["chain"]}),
            "relations": list(spec["relations"]),
            "chain": [{"op": op, "operand": operand} for op, operand in spec["chain"]],
        })
    return cases


# --------------------------------------------------------------------------
# validation — the generator refuses to write a case it cannot vouch for
# --------------------------------------------------------------------------

def validate(cases, tables, relations, opcodes) -> list[str]:
    errors = []
    for case in cases:
        for step in case["chain"]:
            if step["op"] not in opcodes:
                errors.append(f"{case['id']}: opcode {step['op']!r} not in frozen registry")
            tbl, _, col = step["operand"].partition(".")
            if tbl not in tables:
                errors.append(f"{case['id']}: table {tbl!r} not in schema")
            elif col and col not in tables[tbl]:
                errors.append(f"{case['id']}: column {tbl}.{col} not in schema")
        for tbl in case["tables"]:
            if tbl not in tables:
                errors.append(f"{case['id']}: expected table {tbl!r} not in schema")
        for rel in case["relations"]:
            if rel not in relations:
                errors.append(f"{case['id']}: relation {rel!r} not in ontology")
    return errors


# --------------------------------------------------------------------------
# output — expected.yml, same answer-key convention as consulting-firm's
# --------------------------------------------------------------------------

def q(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def render(cases, n) -> str:
    out = [
        "# ===========================================================================",
        "# report-chain-synthetic — answer key for the `report-prepare` task family.",
        "#",
        "# GENERATED by tools/report-chain-synth-gen.py from SCHEMA ONLY:",
        "#   state/keap-tables/*.table.yml, the cortex relation-type ontology, and",
        "#   the frozen opcode registry in cortex-opcodes.ts. No client data, real",
        "#   or historical, was read to produce it; every name below is synthetic.",
        "#   Do not hand-edit — regenerate.",
        "#",
        "# cases: id -> the NL-ish request and the MINIMAL correct chain.",
        "#   tables    — the set report-chain-planning-bench's code oracle diffs",
        "#               against what a model actually queried (superset with a",
        "#               justification = pass, missing = fail).",
        "#   relations — the `rel:` edge type the bundle hangs on.",
        "#   chain     — ordered opcode+operand steps; opcodes are the frozen set.",
        "# ===========================================================================",
        "",
        f"count: {n}",
        "cases:",
    ]
    for c in cases:
        out.append(f"  {c['id']}:")
        out.append(f"    report_type: {c['report_type']}")
        out.append(f"    request: {q(c['request'])}")
        out.append(f"    client: {q(c['client'])}   # SYNTHETIC")
        out.append(f"    tables: [{', '.join(c['tables'])}]")
        out.append(f"    relations: [{', '.join(c['relations'])}]")
        out.append("    chain:")
        for s in c["chain"]:
            out.append(f"      - {{ op: {s['op']}, operand: {s['operand']} }}")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-n", "--count", type=int, default=30, help="cases to generate (default 30)")
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT, help="output directory")
    args = ap.parse_args()

    tables, relations, opcodes = load_tables(), load_relations(), load_opcodes()
    cases = generate(args.count)
    errors = validate(cases, tables, relations, opcodes)
    if errors:
        for e in errors:
            print(f"INVALID: {e}")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "expected.yml"
    target.write_text(render(cases, len(cases)), encoding="utf-8")
    print(f"wrote {len(cases)} cases to {target}")
    print(f"schema: {len(tables)} tables, {len(relations)} relation types, {len(opcodes)} opcodes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
