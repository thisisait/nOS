# Ollama will not honour GBNF on the production wire

Measured 2026-09-13 on this host, `ollama 0.33.3`, `hermes3:8b` already
resident, prompt `Say hello.`, temperature 0, seed 1, grammar
`root ::= "ZZZ"`. No weights were pulled.

| surface | grammar placement | output |
|---|---|---|
| `POST /api/generate` | none | `Hello! How can I assist you today?` |
| `POST /api/generate` | `options.grammar` | identical (confirms 2026-08-22) |
| `POST /api/generate` | top-level `grammar` | identical |
| `POST /api/chat` | top-level `grammar` | identical |
| `POST /v1/chat/completions` | `grammar` | identical |
| `POST /v1/chat/completions` | `extra_body.grammar` | identical |
| `POST /v1/chat/completions` | `response_format: json_object` | JSON — this field *is* honoured |

Unknown keys are accepted and dropped. The OpenAI-compat surface the
estate actually uses (`state/llm-backends.yml` `ollama.base_url` →
`http://127.0.0.1:11434/v1`, `OpenAiCompatAdapter` → `/chat/completions`)
has no GBNF field that constrains decoding.

A second adapter that spoke `/api/generate` instead would not help: the
native generate endpoint drops the same key. `format` / JSON schema cannot
stand in for `state/cortex-lang.gbnf` — cortex-lang is a CFG (arity,
namespaces, pipes), not an object shape.

The only path that has been shown to constrain decoding is
`llama-server --grammar-file` (`tools/local-model-bench.py --grammar`).
That is a different process than the ollama daemon production talks to.
Wiring it is a later adapter (or a swap of the local backend), not a body
key on today's request. Do not ship a `grammar` field that ollama will
echo as set and ignore.

Gate that stays red until a real turn actually attaches the file:
`tests/anatomy/test_agentkit_production_sends_cortex_grammar.py`.
