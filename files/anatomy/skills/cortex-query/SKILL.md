---
name: cortex-query
description: Read-only recall over KEAP /agent/v1 (RO bearer). Returns ranked passages with node ids. Refuses to write. Wraps tools/cortex-query.py, which uses tools/keap-semantic-search.py and the query set from tools/keap-recall-queries.py.
metadata:
  nos:
    audience: [hermes, openclaw]
    platforms: [macos, linux]
    requires: [python3]
prerequisites:
  commands: [python3]
---

# cortex-query — read the cortex, do not write it

Ask KEAP's hybrid search for ranked passages. The door is the **RO bearer**
(`KEAP_AGENT_TOKEN_RO`). Every write belongs to another tool.

## The one rule

**Every recall goes through `tools/cortex-query.py`**, which calls
`tools/keap-semantic-search.py` (the existing `/agent/v1/search/semantic`
client) and scores the answer against `tools/keap-recall-queries.py` (the
SKILLS.md trigger set). Do not curl KEAP. Do not open a second HTTP client.
Do not POST.

```
python3 tools/cortex-query.py "is cortex up"
python3 tools/cortex-query.py --json "cortex health"
python3 tools/cortex-query.py --fixture tests/fixtures/cortex-query-recall.json
```

Each row is `{rank, node_id, title, passage}`. Empty recall is a miss — a
broken token or drained embeddings — not a pass. If KEAP is unreachable,
`--fixture` stands in; an empty fixture is still red.

## When NOT to use

- To write anything: captures, objects, embeddings, promotions, taxonomy
  propose/describe/brief. Those are `mcp-keap` write verbs, not this skill.
- To invent a query set. Known queries live in `docs/systems/*/SKILLS.md`
  and are transcribed by `tools/keap-recall-queries.py`.
- To read DataTables / the roadmap — that is `nos-datatables`.
- When `KEAP_AGENT_TOKEN_RO` is unset and you were not pointed at a fixture:
  say so; do not go looking for another token.

## Never

- Never print the bearer.
- Never pass `--write` / `--post` / `POST`. The wrapper refuses them.
- Never treat zero hits as "nothing relevant". Zero hits means the search
  did not run honestly.
