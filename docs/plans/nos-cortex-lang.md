# nOS Cortex Language (nos-cortex-lang) — design plan

> **Status:** P0 spec, **freeze-ready** after two rounds of KEAP-side review
> (2026-07-24, against KEAP v1.26.0). Round 1 fixed opcode source, Resolver
> placement, authz, and the training sequence. Round 2 added two-phase validation,
> the validate-as-enumeration-oracle fix, native dotted ids, late-binding operands,
> the corpus-privacy boundary, and precedent-drift. All folded in below.
> **One-liner:** an **ontology-typed**, pipeline-shaped IR that a large API LLM
> emits to drive local nOS/KEAP systems with **zero parse ambiguity** — *operands*
> typed by the live KEAP ontology, *opcodes* a code-owned registry, execution split
> from meaning, and a case-based local runtime that replays recurring patterns.

## 1. Why

1. **LLM → local execution, reliably.** The LLM emits the smallest deterministic
   instruction; a local **Executor** expands it into real calls (Infisical secrets,
   PHP endpoints, DB writes). The LLM never sees credentials or transport.
2. **A path off the API LLM.** Every validated `(input, pipeline, outcome, correction)`
   is a precedent. A **case base** over those precedents replays recurring work
   locally; the API LLM becomes teacher + novelty fallback.

Goals, in priority: **(1) zero parse ambiguity, (2) low LLM error rate, (3)
trainable/inspectable, (4) human-readable.** "Minimal tokens" is *not* top — the cost
is the primer + operand selection, not the syntax (§8). Hence the **pipeline
(functional)** surface over symbolic/tag-block alternatives.

## 2. Operands are ontology-typed; opcodes are code-owned

Verified against KEAP v1.26.0: `/agent/v1/health.ontology.verbs` is an **integer
count**, not a vocabulary. The real relation vocabulary is `GET /agent/v1/relations
→ types[]` — **16 relational predicates**, *descriptions of how two concepts relate*,
not imperative actions:

```
analogous-to  causes  contradicts  defines  depends-on  derived-from  duality
exemplifies  generalizes  prerequisite-for  refutes  related-concept  requires
specializes  supersedes  supports
```

Their overlap with imperative opcodes (`get map insert …`) is **∅**. So:

> **Operands** (~1840 taxonomy nodes, entities, the 16 relation predicates) come
> from the ontology. **Opcodes** come from code (the Executor's handler map).

The combinatorial + hallucination risk lives in the **operands** — "pick the right
node out of 1840" (§8) — which is exactly what the ontology types.

**Opcodes must not live in `relation_types`** (even later): that registry grows
*under moderation* and the classifier may propose entries (`status='proposed'`) — an
LLM typing-run must never be able to propose a *new system capability*. The v1.16
vocab-gate is for a **descriptive** vocabulary, not an **imperative** one. And it
can't work anyway: an opcode with no handler does nothing, so a capability cannot be
added by data.

## 3. Surface syntax

```
@input | map(ent:product[červené tričko L]) | classify(tax:nos.services) | insert(db:products, ?hidden=true, dry_run=true)
```

- **Opcodes** `⟨id ∈ Executor.handlers⟩` — a closed, code-owned set. Prefer **many
  specific typed verbs** over few polymorphic (§10). e.g. `get map filter rank
  classify link resolve embed insert update delete route branch preserve review`.
- **Operand namespaces** — `tax:` `ent:` `kg:` `rel:` (ontology-backed, KEAP-validated)
  · `db:` `svc:` `doc:` (infrastructure, **Wing-validated** — §4).
- **Native dotted ids.** KEAP ids are dotted (`nos.services.bookstack`, `01.01.03`),
  **not** slash-pathed. The validator does an exact lookup — no translation layer,
  no `tax:nos/services`-vs-`nos.services` ambiguity.
- **Late-binding operand form** `ns:type[human term]` — the LLM writes a human term;
  KEAP resolves it to the canonical id *during validation* (§6.1). Keeps the 1840 ids
  out of the model's head; the AST carries **both** the surface term and the resolved id.
- **Modifiers** `key=value`; `?key=value` = default when absent; `dry_run=true` on
  mutating verbs (§5).
- **Sources** `@input @user @ctx @sel @prev`. **Operators** `| = : . / , () [] # ?`.

### Grammar (EBNF)

```ebnf
program   ::= pipeline
pipeline  ::= source? stage ("|" stage)*
stage     ::= opcode "(" arglist? ")"
opcode    ::= EXECUTOR_HANDLER                   (* code registry *)
arg       ::= entity | kv | ref | literal
entity    ::= ns ":" dotted_id ("[" term "]")?   (* dotted_id | late-bound term *)
ns        ::= "tax"|"ent"|"kg"|"rel"|"db"|"svc"|"doc"
dotted_id ::= ident ("." ident)*
kv        ::= "?"? key "=" value
```

> Examples in this spec **must typecheck** — they become the primer's P2 training
> material. `rel:` operands are exactly one of the 16 predicates (no `is-a`, no
> `curated/` prefix); e.g. `link(rel:specializes)`, not `link(rel:is-a)`.

## 4. Two authorities, two-phase validation

The Resolver is **not one component in KEAP** (that would break KEAP's read-mostly,
no-LLM-in-container invariants). Split it — and note validation itself is **two-phase**,
because only some namespaces are ontology-backed:

| phase | authority | validates | against |
|---|---|---|---|
| 1 | **KEAP** `POST /agent/v1/validate` | `tax:` `ent:` `kg:` `rel:` | the live ontology (`ent:` → `object_type_definitions`) |
| 2 | **Wing executor** | `db:` `svc:` `doc:` | the handler / resource registry |

KEAP owns *meaning*; Wing owns *dispatch + credentials (Infisical) + audit* (`events`,
`actor_action_id`). **Write this down** — left implicit, the first implementer will
"consolidate" validation by handing KEAP a list of databases, reinstating exactly the
coupling the split removed. `db:`/`svc:`/`doc:` **do not exist in KEAP** and must not.

`/agent/v1/validate` doubles as the constrained-decode + repair surface without any
executor in the path.

## 5. Validity ≠ security

Parse-validity is not authorization. Three requirements, none optional once
write-verbs exist:

1. **`validate` is an enumeration oracle — gate it.** Answering "does this operand
   exist?" lets any caller enumerate the taxonomy + object corpus, *including entries
   they may not read*. KEAP had this exact bug until v1.17 (`GET /api/objects/:id`
   leaked tier-scoped cards); the fix returned **404 for not-found and not-readable
   alike**. `validate` needs the same: resolve operands against the **calling
   identity** (never the system identity), and return a **uniform `unknown operand`**
   for both "doesn't exist" and "not yours" — distinguishable errors *are* the
   disclosure. Authz therefore cannot live only in the executor; validation already
   answers questions.
2. **Capability-scoped executor tokens, not the brain token.** `/agent/v1/*` is a
   single system-scope token with no per-viewer visibility — deliberate for a *read*
   surface. Behind an executor it means anyone with the bearer writes as the system.
   The executor uses per-capability, per-identity tokens (which verbs, namespaces,
   tenant), issued + audited separately.
3. **Destructive verbs are guarded.** `delete(db:products)` is perfectly valid
   grammar. Required: `dry_run` default on mutating verbs (`?commit=true` to execute),
   a confirm-gate on `delete`/`update` (nOS's destructive-op safety model), and
   **idempotence keys** on writes.

## 6. The local runtime (case-based) + its data

### 6.1 kNN over the existing nomic space — not word2vec

A closed token space makes the *output* side learnable from few samples, but the
*input* is still NL — the hard half is NL→features, and a home-grown word2vec over a
short, grammar-determined pipeline corpus would mostly relearn the EBNF, *worse* than
the 768-d **nomic** space KEAP already runs. So: embed the input (nomic, deployed) →
retrieve *k* nearest previously-executed inputs → if their pipelines agree and
similarity clears a threshold, replay; else escalate to the API LLM. Inspectable
("resembles what you approved before"), works at **n=1**, and *is* the P5 confidence
gate with nothing to train. A custom embedding is "not first, not no."

**Late-binding + mandatory ambiguity rejection.** The LLM writes `ent:product[tričko]`;
KEAP resolves it during validation — one API round-trip, not two, which **demotes
`/agent/v1/context` from hard prerequisite to the ambiguity fallback**. Guard: fuzzy
resolution **never silently takes the nearest match**. On comparable-score multimatch
the validator returns a typed **`ambiguous operand` with candidates** — it does not
choose. (`ingest.mjs`'s identity-drift detector exists precisely because a
valid-but-wrong id is indistinguishable from a correct one after the fact.)

**Two replay rules (they subsume the kNN-negation problem):**
- **kNN replay NEVER bypasses the dry-run gate** — at any confidence. A mis-replayed
  precedent (`"…hide it"` vs `"…DO NOT hide it"` both embed >0.9) yields a *plan*, not
  an effect; the operator sees `hidden=true` before commit.
- **Modifiers are NEVER inherited** — retrieval supplies the pipeline *shape* (opcode
  sequence); values + boolean flags do not ride along.
- Earn the threshold with a **replay gate** of adversarial minimal pairs (negation
  on/off), on the model of `scripts/recall-gate.mjs` — a number without demonstrated
  discrimination is not a guarantee.

### 6.2 The corpus is instance-level data — P0 decision, not P3

**The most serious item.** `docs/specs/ontology-anchoring.md` §6 declares *no
instance-level data in the concept graph — the product's privacy line, not a
limitation*. But `(input, pipeline, outcome, correction)` is instances **by
construction**. Hazard: kNN over the *existing* nomic space means, if corpus inputs
land in the shared `embeddings` table, knowledge retrieval (`/api/search`, hybrid
recall, `/agent/v1/graph`) returns them — one user's knowledge question surfacing
another's operational input (there is precedent: legacy `note:` embeddings linger as
known debt). **Requirement:** the corpus gets its **own store and its own index**
(not a different `kind` in the shared table), excluded from knowledge recall, with its
own retention + visibility. Decide this **before P3** — after P3 the data already exists.

### 6.3 Precedents rot; store provenance + a TTL

- **Operand drift.** The ontology grows under moderation; a precedent whose operand
  was renamed/retired resolves on replay to *something else* rather than failing.
  Store the resolved id **and** the name it had at capture; **invalidate on drift**
  (the `applyDomain()` `priorNames` check across the delete/insert boundary).
- **Corpus source outside the container from write one.** Operator corrections are
  unrecomputable human work-product. The 2026-07-22 KEAP data-dir swap silently
  dropped the derived R3 relations *because they had no source outside the container*
  and the sourced layers rebuilt and masked it. The corpus is that category — persist
  it off-container from the first write, or one swap erases all of P4.
- **Pin `ontology.version` AND `database.id`** (health) into every corpus row — a
  model trained over a corpus from a different database speaks a different language
  even when versions agree.
- **Validate-time ≠ execute-time.** KEAP typechecks at T; Wing dispatches at T+n; a
  converge/ingest between them changes the vocabulary under the AST. Either the AST
  carries a short **TTL**, or the executor **revalidates at dispatch**.

## 7. Emission protocol — structured output, not a normalizer

The Anthropic API exposes no logit-bias / grammar-mask, but it **does** offer
constrained decoding: a **tool schema**. Emit the **AST as a structured tool call**
(types + required fields enforced by the API), and render the pipeline surface *from*
the AST for humans + the corpus. This buys goal (1) at the protocol level rather than
by prompt discipline; the only objection was verbosity, and §8 says token count is not
the constraint — so evaluate this **before** writing any repairer.

A normalizer that rewrites `@input.map(...)` → `@input | map(...)` is **guessing
intent** and reintroduces ambiguity into the one layer built to remove it. If one
exists it must be **total and provably meaning-preserving** (whitespace, trailing
commas, quotes) with everything else → the repair loop as a typed error — and **every
normalization logged beside the raw emission**, or the corpus records a pipeline the
model never produced.

## 8. Token economy + operand selection

Syntax length is the wrong target: a pipeline is ~20 tokens, the **primer** (~2000)
rides every call. Levers: **cache the primer** (static), and **don't send 1840 nodes**
— operand selection is the hard part, solved by **late-binding** (§6.1) resolving human
terms server-side, with `/agent/v1/context` (budget-bounded, citable; Track D,
`ontology-anchoring.md` §4) as the ambiguity fallback.

## 9. Portability — honest version

"Cortex off nOS" must not promise *automatic* bootstrap. Track D is explicit: a domain
pack = slug root + canonical files + golden fixture + a **recall-gate pass** — a
*curated delivery*. Honest statement: **"Cortex at a company needs a domain pack, and
building it is work."** The substrate is portable; it is not free.

## 10. Answers to the open questions

- **Verb granularity → many specific, not few polymorphic.** Few polymorphic verbs
  push ambiguity into the Executor (uninspectable, untrainable); the endgame is a
  local model, so optimize for it — specific typed verbs are smaller, fixed-slot
  classes. Every opcode needs a handler anyway, so "few verbs" only hides the work.
- **Lexicon versioning → pin `ontology.version` + `database.id`** per corpus row (§6.3).
- **Confidence metric →** similarity to nearest precedent + agreement among *k*,
  calibrated against logged operator corrections.
- **Extraction boundary →** LLM proposes fields; Executor validates against the entity
  schema + fills defaults.
- **Control flow (deferred).** `source? stage ("|" stage)*` can't say "if exists update
  else create." Admitting branches trades against goals (1)+(3) — *every grammar branch
  is one the local model must learn*. Keep the IR **flat through P3**; decide on real
  cases, not a hypothetical. `upsert()` keeps inspectability (dry_run returns a plan
  showing the branch taken).

## 11. Roadmap (re-sequenced by round 2)

| Phase | Deliverable |
|---|---|
| **P0** | This spec (freeze after the §12 checklist). Opcodes = code registry; operands = ontology; two-phase validation + authz defined; **corpus-store decision made** (§6.2). |
| **P1** | **`POST /agent/v1/validate` in KEAP** (tokenize → typecheck → AST\|typed error, **zero side effects, authz-aware**). Wing executor stub, **read verbs only**, capability-scoped token. |
| **P2** | Teach Claude nos-lang via **structured tool-schema AST emission** (§7); late-binding resolves operands (so `context` is *not* a hard prereq). Measure validity rate. |
| **P3** | Write verbs behind authz + dry-run/confirm gates; corpus in its **own off-container store** with versioned + provenance rows (§6.2–6.3). |
| **P4** | **kNN case-based replay over nomic** (n=1) + a replay gate of adversarial minimal pairs; pipeline→tree visualization in KEAP. |
| **P5** | Confidence-gated local execution. **Alternative to carry:** a small model **fine-tuned on the P3 corpus** to emit the grammar — beats a large general model at this narrow task, removes the API LLM from the hot path, demotes kNN to the gate. |
| **P6** | Standalone Cortex (curated domain pack, §9). |

## 12. P0-freeze checklist (from the round-2 review)

1. ✅ Two-phase validation written down; `ent:` → `object_type_definitions` (§4).
2. ✅ `validate` authz-aware, uniform `unknown operand` (§5.1).
3. ✅ Native dotted ids; examples typecheck (§3).
4. ✅ Late-binding operands with mandatory ambiguity rejection (§6.1).
5. ✅ kNN never bypasses dry-run, never inherits modifiers (§6.1).
6. ✅ Structured tool-schema AST emission evaluated before any normalizer (§7).
7. ✅ Corpus own store, excluded from knowledge recall — a P0 decision (§6.2).
8. ✅ Precedent invalidation on drift (§6.3) + AST TTL (§6.3).
- Deferred to end-of-P3 by measurement: grammar control flow (§10), fine-tuned local
  emitter (P5 alternative, §11).

## 13. What KEAP owes next (v1.26.0 → P1)

Neither exists yet; both are plan dependencies. Recommendation (KEAP-side): build
**`/agent/v1/validate` first** — late-binding makes it the entity-resolution path,
which demotes `/agent/v1/context` to the ambiguity fallback.
- `POST /agent/v1/validate` — parse + typecheck (live ontology), AST\|typed error,
  zero side effects, authz-aware (§4–5).
- `POST /agent/v1/context` — budget-bounded citable injector (Track D).

## 14. Relation to existing nOS pieces

- **KEAP (Cortex)** — ontology, `validate`, `context`, the case-base corpus's *meaning*
  side. Read-mostly, no LLM in-container.
- **Wing / AgentKit** — the **executor** (phase-2 validation, authz, Infisical, `events`
  audit) + the NL→pipeline agent.
- **Bone / Infisical** — credential resolution in the executor's handlers.
- **The point:** the knowledge layer gains a **code-owned opcode set over
  ontology-typed operands** — meaning and execution in separate authorities.
