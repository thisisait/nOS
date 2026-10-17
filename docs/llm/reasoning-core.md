# Reasoning core: seams and who checks them

LLM context note (2026-10-17). The reasoning core is a chain of two-sided contracts; most live
failures so far were one side checking what the other never promised. Each row names both sides
and the gate that holds them together. Read before changing any of them.

## The plan path (Iris, `--plan cortex`)

```
model --(ast_schema | primer)--> serve.rs plan() --render()--> organ /agent/v1/validate
      <--(repair: said_error)--                  <--AST------
plan() + calls() (cortex_plan.rs) --> query_rows / show / propose_row_* --> ledger cortex_plan rows --> iris-bench read_plan
```

| Seam | Side A | Side B | Gate |
|---|---|---|---|
| Opcodes, params, operands per op | `cortex-opcodes.ts` (organ, v3) | `ast_schema()` anyOf branch per op | `the_ast_schema_offers_each_opcode_only_what_the_registry_takes` (reads the TS) |
| Params the mapper reads | organ leaves a `db:` stage's params OPEN | `READS` in `cortex_plan.rs` refuses the rest | `a_param_the_mapper_does_not_read_is_refused_not_dropped` |
| Registry hash | `cortexRegistryHash()` | `REGISTRY_HASH` + 2 copies | `test_the_plan_mapper_knows_the_registry_hash.py` (node strips types) |
| Repair round | organ `issue()`: code, stage, detail | `said_error()` | `the_repair_round_hears_which_stage_and_key_the_organ_refused` |
| Free text | lexer: bare `-?\d+` is int, bare word ASCII only | primer quotes every string; `extract()` joins `|` lines | `the_primer_quotes_every_string_value`, `a_free_text_plan_is_read_whole` |
| Plan row → bench | serve: `primer_sha256`, `grammar_sha256`, `fallback_kind`, `table` | `iris-bench.py read_plan / same_pipeline` | `a_fallback_says_whether_...`, `test_an_estate_failure_is_no_data_...`, `test_a_plan_is_equal_to_its_expectation_...` |
| nOS vendored registry vs KEAP | `files/anatomy/cortex/server` | `thisisait/nos-keap` `server/` | `test_vendored_cortex_matches_keap.py` (`NOS_KEAP_CHECKOUT=...`) |

## The tool path (Iris direct)

- **Ollama strips tool schemas** to `anyOf/type/items/description/enum/properties/required`
  (api/types.go `ToolProperty`). No `oneOf`, `const`, `additionalProperties`. `show.component`
  keeps its `oneOf` for strict validators but carries a `kind` enum and every `SHOW_SHAPE` line in
  its description. Gate: `every_tool_property_survives_what_ollama_keeps` (tests/tool_schemas.rs).
- **`normalize_show` is where schema meets `show()`**: anything the schema or its description
  admits must draw (gate `show_draws_what_its_schema_admits`). A sourced chart's own x/series are
  placeholders; a kpi's number is never the model's.
- The shell contract (`thalamus/contract/src/renderers.rs`) stays strict; repairs go in
  `normalize_show`, not in the contract structs.

## Open debts (not fixed 2026-10-17)

- Wing's cortex executor has no live caller; its handlers ignore v3 `q`, `dir`, `fields`, and
  `RankHandler` reads `by` as a semantic query where the thalamus reads a column.
- The plan sees only the current turn (ponytail in serve.rs plan()).
- `local-model-bench.py` scores `?k=v` while Iris speaks `k=v`; it validates at KEAP :8091, Iris at :8098.
- Thalamus ledger writes `status='terminated'` for a clean end and `trigger='shell'`, outside Wing's enums.
