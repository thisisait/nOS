# Deterministic evals and a ≤3B fine-tune for Iris

LLM context note (2026-10-21). Where the benches stand, what makes a run repeatable, how to claim
"path B beats path A", and the fine-tune path with its data and cost. Read with
[reasoning-core.md](reasoning-core.md).

## What exists

| Piece | Where | Deterministic? |
|---|---|---|
| Wire bench, code as judge | `tools/iris-bench.py`, `state/fixtures/iris-bench.yml` (43 cases, cs twins) | judge yes; model no (see below) |
| Plan judging (`--plan cortex`) | iris-bench `read_plan` + organ `/agent/v1/validate` | yes, op by op |
| Plan → tool calls mapper | `state/fixtures/cortex-plan/cases.yml` (22) → `tests/cortex_plan.rs` | yes, offline gate |
| Fixed data | `iris-bench.py --seed` (iris-bench-2 tables), nos-assay domains + tiers | yes |
| Provenance | `--out` records nOS commit, Ollama digest, primer/grammar sha | yes |
| Majority of N | `--repeat N` | masks noise, does not remove it |
| Paired A/B, per kind | `tools/iris-bench.py --compare` (2026-10-21) | yes |
| Offline re-judge | `iris-bench.py --rescore` | yes |
| Sampler pin | `iris_local_seed` → `NOS_LOCAL_SEED` → `seed` on a local row (2026-10-21) | yes, same host + digest |

Not in CI and cannot be: a live run needs a model, KEAP, the organ and the ledger. CI holds the
judge, the mapper and the compare tool (offline gates); the run itself is an operator step.

## "nos-lang has a measurable benefit" — partly, not provably

Numbers in the repo (none of the runs themselves are committed; they live under `~/.nos/bench`
and `~/iris-bench-local` on the host):

- v0.17-beta baseline (devlog 2026-10-17, pre-#57, nos-assay, M1 Max): `qwen3.5:9b` plain tools
  68/126 smoke, 143/284 standard; `hermes3:8b` 28/126; first live cortex plan run 1/14.
- `default.config.yml` (2026-10-18/19): cortex on `qwen3.5:9b` GGUF standard 85 → 70/283 beside the
  catalogue rework; "cortex beat tools" on chart, kpi, top-n, insert-row — hence `iris_plan: hybrid`
  and `iris_cortex_intents`. Default is still `tools`.
- `state/habitat/llm-backends.yml` (2026-08-30): hermes3:8b fails cortex-lang syntax, qwen3:14b semantics.

What is missing for the claim to stand: a paired run (same digest, commit, seed, case set) where
only `iris_plan` differs, its two `--out` files kept, and `--compare` saying `B better` per
kind. Overall, cortex (85/283) is below plain tools (143/284) — the benefit is per intent, which
is exactly what hybrid bets on and what `by_kind` now measures.

## A repeatable run

1. `config.yml`: `iris_local_temperature: 0`, `iris_local_seed: 42`; converge thalamus.
2. `NOS_LIVE=1 tools/iris-bench.py --seed` once (fixed tables).
3. Same config twice → `tools/iris-bench.py --compare run1.json run2.json` must say `repeatable`.
   Not repeatable at temperature 0 + seed = the host's Ollama is not deterministic (batching,
   Metal kernels); then `--repeat 3` and report it.
4. Change ONE axis (`iris_plan: tools` → `hybrid`/`cortex`, catalogue, or the model tag), run again →
   `tools/iris-bench.py --compare tools.json cortex.json`. Verdict by exact McNemar on paired flips;
   two axes at once = `confounded` (exit 2). 43 cases detect only big effects (≈ 6+ net flips);
   use a nos-assay `--tier standard` domain for smaller ones.

Debts: provenance does not record temperature/seed (the bench reads the wire, not the plist);
hidden fee 62 (multi-turn ledger slicing, `intent_ok` regex) still applies.

## Fine-tune: what to tune

Recommended target: **plan generation** — one user turn (+ table catalogue) → one cortex-lang v3
pipeline. Narrow, has a grammar (`state/cortex-lang.gbnf`) and a JSON-schema engine
(`ast_schema()`), and every output is checked by code (organ validate + mapper + execute on seeded
rows). Tool calling / `show` rendering is diffuse and Ollama strips its schemas; leave it to the
base model or a later round.

Candidates (≤3B): Qwen2.5-3B-Instruct (best JSON/tool behaviour at size; Qwen research licence,
check before any commercial use), Llama-3.2-3B-Instruct (community licence; weaker Czech),
Qwen3-1.7B (Apache-2.0, tiny control). The floor `llm_cell_min_params_b: 3` reads size from the
TAG: name it e.g. `nos-plan:3b`, or the binding refuses it.

Method: QLoRA (4-bit base, r=16–32, all linear layers) with Unsloth or TRL+PEFT; SFT on chat
format `system` (short primer) / `user` (turn + catalogue) / `assistant` (pipeline text). Bake the
long primer into the weights: train and serve with the SAME short system prompt. Export:
merge → GGUF (`q4_k_m` + `q8_0`) → Modelfile with the model's chat template →
`ollama create nos-plan:3b`. Alternative on the Mac Studio: `mlx_lm.lora` (free, slower).

## Training data: not enough yet

Have: 43 bench cases (eval set: never train on them), 22 mapper cases, nos-assay domains, a few
live ledger plans (1/14 valid). That is an eval set, not a training set. Need 2k–10k validated
pairs: generate them.

Generator (rejection sampling, code as filter): table defs from nos-assay domains × intent
templates (count, filter, group-by, rank, chart kind, cs/en) → teacher model writes the pipeline →
keep only if organ validates, mapper maps, and executing on seeded rows equals a code oracle.
Hold out whole domains for eval. Then: base 3B vs tuned 3B vs qwen3:14b, same digest pin, through
`iris-bench.py --compare`.

## Cost (vast.ai, checked 2026-10-21)

Prices: RTX 4090 ≈ $0.35–0.60/h (computeprices.com, 2026-10-20: min $0.48, median ≈ $0.57),
A100 ≈ $0.80–1.50/h, H100 ≈ $1.50–2.50/h; disk ≈ $0.10–0.15/GB/month, billed while stopped.
QLoRA 3B on a 4090 ≈ 2–4k tok/s; at ~1.5k tokens/example (short primer):

| Run | Tokens | GPU time | Cost |
|---|---|---|---|
| 2k ex × 1 epoch, 4090 | 3 M | ~0.5 h + 1–2 h setup/export/eval | $1–2 |
| 10k ex × 3 epochs, 4090 | 45 M | ~4–6 h + 2 h | $3–5 |
| 50k ex × 3 epochs, A100 | 225 M | ~12–20 h + 2 h | $15–35 |

Realistic project (5–10 runs: sweeps, retries): **$10–50; high $100–150**. Teacher-model API cost
for data generation and the operator's time dominate the GPU bill. Evals run on the Mac Studio
(Ollama, the real estate), not on vast.
