#!/usr/bin/env python3
"""Self-check for tools/report-chain-synth-gen.py.

Validates the REAL generated output on disk (not just an in-memory run):
every table/column referenced exists in state/keap-tables/*.table.yml, every
relation exists in the cortex relation-type ontology, every opcode is in the
frozen registry from cortex-opcodes.ts, and no case leaks a non-synthetic
client name. Plain asserts, no framework — `python3 tools/test_...py`.
"""

import importlib.util
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("gen", HERE / "report-chain-synth-gen.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

tables = gen.load_tables()
relations = gen.load_relations()
opcodes = gen.load_opcodes()

assert tables, "no DataTable definitions found"
assert "party" in tables and "legal_name" in tables["party"]
assert "depends-on" in relations, "relation ontology did not load"
assert opcodes >= {"get", "map", "filter", "rank", "classify", "resolve", "embed",
                   "link", "insert", "update", "delete", "preserve", "route",
                   "review", "delegate"}, f"frozen opcode set incomplete: {sorted(opcodes)}"

# 1. in-memory generation validates clean
cases = gen.generate(30)
assert len(cases) == 30
errors = gen.validate(cases, tables, relations, opcodes)
assert not errors, "generated cases failed validation:\n" + "\n".join(errors)
assert len({c["id"] for c in cases}) == 30, "duplicate case ids"

# 2. every emitted name is from the synthetic roster
for c in cases:
    assert c["client"] in gen.SYNTHETIC_NAMES, f"non-synthetic client name: {c['client']}"
    assert c["client"] in c["request"], f"{c['id']}: request does not name its client"
    assert c["chain"][0]["op"] == "resolve", f"{c['id']}: chain must resolve the entity first"

# 3. the file actually on disk re-validates against the schema
out = gen.DEFAULT_OUT / "expected.yml"
assert out.exists(), f"{out} missing — run the generator first"
text = out.read_text(encoding="utf-8")
steps = re.findall(r"- \{ op: ([a-z]+), operand: ([a-z0-9_.-]+) \}", text)
assert steps, "no chain steps parsed out of the generated file"
for op, operand in steps:
    assert op in opcodes, f"on-disk opcode {op!r} not in frozen registry"
    tbl, _, col = operand.partition(".")
    assert tbl in tables, f"on-disk table {tbl!r} not in schema"
    assert not col or col in tables[tbl], f"on-disk column {tbl}.{col} not in schema"
for tbl_list in re.findall(r"^    tables: \[(.*)\]$", text, re.M):
    for tbl in tbl_list.split(", "):
        assert tbl in tables, f"on-disk expected table {tbl!r} not in schema"
for rel_list in re.findall(r"^    relations: \[(.*)\]$", text, re.M):
    for rel in rel_list.split(", "):
        assert rel in relations, f"on-disk relation {rel!r} not in ontology"

print(f"OK — {len(cases)} cases, {len(steps)} on-disk chain steps; "
      f"{len(tables)} tables / {len(relations)} relations / {len(opcodes)} opcodes checked")
