# nOS Cortex Language (nos-cortex-lang) — design plan

> **Status:** design / vision (P0). Not implemented. Owner surface: KEAP (the Cortex).
> **One-liner:** an ontology-typed, pipeline-shaped Intermediate Representation (IR)
> that a large API LLM (Claude, taught "nos-lang") emits to drive local nOS/KEAP
> systems with **minimal tokens and zero ambiguity** — and whose closed vocabulary
> doubles as the training substrate for a **local decision model** (word2vec +
> decision trees) that eventually executes the known 80% without the API LLM.

## 1. Why

Two problems, one language:

1. **LLM → local execution, reliably.** Verbose JSON tool-calls waste tokens and
   still hallucinate keys. We want the LLM to emit the *smallest deterministic*
   instruction that a local **Resolver** expands into real system calls (Infisical
   secrets, PHP endpoints, DB writes) — the LLM never sees credentials or transport.
2. **A path off the API LLM.** Every validated instruction + its outcome is a
   training pair. Because the language's vocabulary is **closed and drawn from the
   KEAP ontology**, that corpus is exactly what you need to train a small *local*
   model — first embeddings, then decision trees — that predicts the instruction
   itself for recurring inputs. The API LLM degrades from "the brain" to "the
   teacher + the novelty fallback." That local model is the real **Cortex runtime**:
   the deterministic, offline, business-logic layer of nOS — like a kernel's syscall
   table, but learned.

Design goals, in priority order: **(1) zero parse ambiguity, (2) low LLM error
rate, (3) minimal tokens, (4) trainable/visualizable, (5) human-readable.** Note
that (2) beats (3): a slightly longer named-verb syntax that the LLM *never* gets
wrong is worth more than a dense symbolic one it fumbles. This is why we pick the
**pipeline (functional, code-like)** surface over the "caveman" symbolic and the
verbose tag-block alternatives.

## 2. The core idea: the language IS the ontology

We do **not** invent an alphabet. KEAP already exposes one — `/agent/v1/health`
now returns `ontology: {verbs, toeRelations, curatedRelations, byStatus}`. So:

| Language construct | Comes from | Role |
|---|---|---|
| **verbs** (opcodes) | `ontology.verbs` | the closed action set |
| **entities** (operands) | taxonomy nodes / entity types | namespaced references |
| **relations** (edges) | `toeRelations` + `curatedRelations` | typed links |
| **sources** | runtime context | `@input`, `@user`, `@ctx` |

A **closed vocabulary** is the unlock: it is (a) deterministically parseable, (b)
constrainable at decode time so the LLM *cannot* emit an unknown opcode, and (c) a
finite token space — which is what makes a custom word2vec/embedding well-defined.
The ontology nodes literally *are* the tokens.

## 3. Surface syntax — pipeline data-flow

```
@input | map(ent:product) | classify(tax:catalog) | insert(db:products, hidden=true)
```

Read left-to-right; each stage consumes the previous stage's output (or the
`@source`) and produces the next. `map`, `classify`, `insert` are **ontology
verbs**; `ent:product`, `tax:catalog`, `db:products` are **namespaced entities**;
`hidden=true` is a **modifier**. The LLM writes *only* business intent; it has no
idea `insert(db:...)` will fetch a DB key from Infisical and POST to a PHP endpoint.

### Lexicon

- **Verbs** — `⟨id ∈ ontology.verbs⟩`. Opcodes. Closed set. e.g. `get map filter
  rank classify link resolve embed insert update delete route branch preserve review`.
- **Namespaces** — `db:` (store), `tax:` (taxonomy node), `ent:` (entity type),
  `kg:` (knowledge-graph node), `rel:` (relation type), `svc:` (nOS service),
  `doc:` (content). Path segments join with `/`: `tax:physics/cosmology`.
- **Sources** — `@input @user @ctx @sel @prev` (`@prev` is implicit across a pipe).
- **Modifiers** — `key=value` keyword args; `?key=value` = *default/fallback*
  applied only when the value is absent from the incoming data.
- **Operators** — `|` flow · `=` bind · `:` namespace · `/` path · `,` arg-sep ·
  `()` call · `[]` set/collection · `.` field access · `#` comment · `?` default.
- **Literals** — `"string"`, `123`, `true|false|null`.

### Grammar (EBNF)

```ebnf
program   ::= pipeline
pipeline  ::= source? stage ("|" stage)*
source    ::= "@" ident
stage     ::= verb "(" arglist? ")"
verb      ::= ONTOLOGY_VERB                 (* validated against live ontology *)
arglist   ::= arg ("," arg)*
arg       ::= entity | kv | ref | literal
entity    ::= ns ":" path
ns        ::= "db"|"tax"|"ent"|"kg"|"rel"|"svc"|"doc"
path      ::= ident ("/" ident)*
kv        ::= "?"? key "=" value
value     ::= literal | entity | ref
ref       ::= "@" ident ("." ident)*
literal   ::= STRING | NUMBER | BOOL | "null"
```

The grammar is LL(1) and regex-friendly — the Resolver can parse it with a hand
tokenizer; no ambiguity, no backtracking.

## 4. Semantics & the Resolver

The Resolver is the local authority. It does **not** run in the LLM.

```
Intent (NL)  ──►  Claude (taught nos-lang)  ──►  nos-cortex expression
                                                        │
                                                        ▼
        ┌───────────────────── Resolver (KEAP /agent/v1/exec) ─────────────────────┐
        │ 1. tokenize + parse → AST                                                 │
        │ 2. validate: every verb ∈ ontology.verbs, every entity resolves,         │
        │    every relation ∈ toe/curated  → else REJECT (typed error, no exec)     │
        │ 3. plan: map each stage to a handler; thread @prev                        │
        │ 4. resolve creds per handler (Infisical) — invisible to the LLM          │
        │ 5. dispatch (PHP endpoint / DB / svc) with the secret injected           │
        │ 6. log (input, expression, AST, outcome) → the training corpus           │
        └───────────────────────────────────────────────────────────────────────────┘
```

Layer separation (the whole point — *what* vs *how*):

| Layer | Owner | Sees |
|---|---|---|
| Intent | user / system | natural language |
| **nos-cortex** | the LLM | verbs + entities only |
| Resolver / router | local (KEAP/Bone) | AST → handlers |
| Credentials | local (Infisical) | never leaves the host |
| Execution | local (PHP / DB / svc) | the actual call |

**Validation-before-execution is the safety model.** An expression that references
an unknown verb or an entity absent from the ontology is rejected *before any side
effect*. This is stronger than JSON-schema tool validation because the type system
is the live knowledge graph, not a static schema.

## 5. The decision-tree / local-training angle

This is where nOS-KEAP gains its outsized value.

**A pipeline is a decision path.** `@input | classify(tax:catalog) | route(?to=review
when=low_conf) | insert(db:products)` renders *directly* as a tree: each verb is a
node, each `route/branch/when` is an edge. KEAP can **visualize** the pipeline as a
decision tree and let the operator **edit** it; edits become training constraints.

**The learning loop:**

1. Novel input → API LLM emits a pipeline → Resolver validates + executes → the
   tuple `(input, pipeline, outcome, operator-correction?)` is logged.
2. The corpus is a clean supervised set over a **closed token space**. Train, in order:
   - **word2vec / embeddings** over the ontology tokens (verbs + entities) → a
     semantic space where "insert a hidden product" sits near its pipeline.
   - **decision trees / rule ensembles** mapping `input features → pipeline` for the
     deterministic majority of business logic (exact, inspectable, offline).
3. **Confidence gating:** the local model handles high-confidence known patterns
   (no API call); it escalates novel / low-confidence inputs to the API LLM, which
   also *teaches* the next round of training data. Over time the LLM-call rate falls.

The result is nOS's "runtime AI": **local, exact, inspectable, API-optional on the
hot path** — decision trees you can read and audit, not a black box. The API LLM
stays the general intelligence for the long tail; the Cortex runs the business.

## 6. Teaching Claude "nos-lang"

- A **primer** (system prompt / an AgentKit agent profile / a `/nos-lang` skill):
  the closed verb list + namespace table + grammar + ~20 worked examples, fetched
  live from `/agent/v1/health.ontology` so it never drifts from the real vocabulary.
- **Grammar-constrained decoding** where the endpoint supports it → the model
  *cannot* emit an invalid token. Otherwise the Resolver's REJECT + a one-shot
  repair prompt closes the loop.
- The LLM's only job: **NL → valid pipeline.** Everything else is local.

## 7. Portability — Cortex off-nOS

Because the language is derived from the ontology and the Resolver + local model
are self-contained, KEAP-Cortex can be **"vypuštěn" onto a company server**: point
it at the company's data, it bootstraps taxonomy / ontology / entities, starts
answering in nos-cortex, logs the corpus, and trains its local decision model on
*that company's* processes → self-optimizing automation, API-LLM-agnostic. The
ontology is the portable substrate; nos-cortex makes it executable.

## 8. Worked examples

```text
# create a product from free text, default-hidden
@input | map(ent:product) | insert(db:products, ?hidden=true)

# classify an incoming document and file it, escalate the uncertain ones
@input | embed() | classify(tax:knowledge) | route(?to=review, when=low_conf) | preserve(doc:inbox)

# answer a knowledge question from the graph, ranked
@user | resolve(kg:node) | link(rel:is-a) | rank(?by=relevance, top=5)

# curate: propose a relation between two taxonomy nodes for operator review
@sel | link(tax:physics/cosmology, rel:curated/depends-on) | review(?queue=curator)
```

Each is a few tokens, unambiguous, executable, *and* a drawable decision path.

## 9. Roadmap

- **P0 — spec (this doc).** Freeze the namespaces + grammar; agree the verb set is
  sourced from `ontology.verbs`. Coordinate with the KEAP `feat/ontology-sot` work
  (the ontology-SoT + the new `/agent/v1/health.ontology` fields are the substrate).
- **P1 — thin Resolver (read-only).** KEAP `/agent/v1/exec`: tokenize → parse →
  validate against the live ontology → dispatch **read verbs only** (`get map
  classify resolve rank`). No credentials, no writes → zero blast radius. Proves the
  round-trip.
- **P2 — teach Claude.** Primer + a KEAP AgentKit agent; NL → pipeline → execute for
  a handful of real read ops. Measure LLM validity rate.
- **P3 — write verbs + corpus.** Add `insert/update/link/preserve/review` with
  credential resolution behind the Resolver; log every `(input, pipeline, outcome)`.
- **P4 — local training + visualization.** word2vec over the corpus; decision-tree
  induction; render pipelines as editable trees in KEAP.
- **P5 — confidence-gated local execution.** Local model short-circuits the API LLM
  for known patterns; escalation + teach-back for novelty.
- **P6 — standalone Cortex** deployable off nOS (§7).

## 10. Open questions

- **Verb granularity** — few powerful polymorphic verbs (lower LLM error, more
  Resolver magic) vs many specific verbs (more explicit, more tokens). Lean few + typed.
- **Extraction boundary** — for `map(ent:product)`, does the LLM structure the
  fields or does the Resolver? Proposal: LLM proposes, Resolver validates against the
  entity schema and fills defaults.
- **Transactions / partial failure** across a multi-stage pipeline (rollback semantics).
- **Scoping / multi-tenancy** in the entity namespaces (per-tenant `db:`).
- **Lexicon versioning** — the ontology evolves; the language must carry a version so
  a trained local model knows which vocabulary it speaks. Pin `ontology.version` in
  every logged corpus row.
- **Confidence metric** for the local-vs-API gate (calibration).

## 11. Relation to existing nOS pieces

- **KEAP (Cortex)** — owns the ontology, the Resolver (`/agent/v1/exec`), the corpus,
  and the local model. `docs/plans/nos-cortex-lang.md` is its language layer.
- **AgentKit / Wing** — hosts the "nos-lang" agent (the NL→pipeline translator) and
  the audit lineage (every exec is an `events` row, same as agent runs).
- **Bone / Infisical** — credential resolution inside the Resolver's handlers.
- **This is the concrete form of the "Cortex" in the anatomy** (`CLAUDE.md`
  Architecture → Cortex/KEAP): today the ontology is knowledge you *read*; nos-cortex
  turns its **verbs into opcodes** — the knowledge layer becomes an instruction set.
