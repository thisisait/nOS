# nOS Cortex Language (nos-cortex-lang) — design plan

> **Status:** design / vision (P0). Not implemented.
> **Revised** after a live-system review (2026-07-24) corrected three structural
> errors (opcode source, Resolver placement, missing authz) and one sequencing
> mistake (training). The vision is unchanged; two columns moved.
> **One-liner:** an **ontology-typed**, pipeline-shaped Intermediate Representation
> (IR) that a large API LLM (Claude, taught "nos-lang") emits to drive local
> nOS/KEAP systems with minimal tokens and **zero parse ambiguity** — where the
> *operands* are typed by the live KEAP ontology, the *opcodes* are a code-owned
> registry, and the validated-expression corpus feeds a **case-based local runtime**
> that executes recurring patterns without the API LLM.

## 1. Why

Two problems, one language:

1. **LLM → local execution, reliably.** Verbose JSON tool-calls waste tokens and
   still hallucinate keys. The LLM should emit the *smallest deterministic*
   instruction that a local **Executor** expands into real system calls (Infisical
   secrets, PHP endpoints, DB writes) — the LLM never sees credentials or transport.
2. **A path off the API LLM.** Every validated instruction + its outcome is a
   precedent. Because the *operand* vocabulary is closed (the ontology) and the
   *opcode* set is closed (code), that corpus is exactly what a **local model** needs
   to replay recurring work — the API LLM degrades from "the brain" to "the teacher +
   the novelty fallback." That local runtime is the deterministic, offline
   business-logic layer of nOS — like a kernel's syscall dispatch, but precedent-driven.

Design goals, in priority order: **(1) zero parse ambiguity, (2) low LLM error
rate, (3) trainable/inspectable, (4) human-readable.** (Note: "minimal tokens" is
*not* a top goal — see §8; the token cost is the primer + node-selection, not the
syntax.) (2) beats compression: a named-verb syntax the LLM *never* fumbles beats a
dense symbolic one it does. Hence the **pipeline (functional, code-like)** surface
over the symbolic "caveman" and verbose tag-block alternatives.

## 2. The core: operands are ontology-typed; opcodes are code-owned

The tempting thesis "the language IS the ontology" is **false as stated** — verified
live. `/agent/v1/health.ontology.verbs` is an **integer count**, not a vocabulary,
and the real relation vocabulary at `/agent/v1/relations.types[]` is 16 **relational
predicates** — *descriptions of how two concepts relate*, not imperative actions:

```
analogous-to  causes  contradicts  defines  depends-on  derived-from
duality  exemplifies  generalizes  prerequisite-for  refutes
related-concept  requires  specializes  supersedes  supports
```

Their overlap with imperative opcodes (`get map insert …`) is the **empty set**.
So the true — and stronger — statement is:

> **Operands** (the ~1840 taxonomy nodes, entities, and the 16 relation predicates)
> **come from the ontology. Opcodes come from code.**

This is the better split because the combinatorial + hallucination risk lives in the
**operands** — "pick the right node out of 1840" is the actual hard problem (§8), and
that is exactly what the ontology types. Opcodes are a small fixed set; they need no
data.

**Why opcodes must NOT live in `relation_types` (even later):** that registry grows
*under moderation*, and the classifier may propose new entries (`status='proposed'`).
If opcodes lived there, an LLM typing run could *propose a new system capability* —
inverting the trust model. The v1.16 vocab-gate was designed for a **descriptive**
vocabulary, not an **imperative** one. And structurally it can't work anyway: an
opcode with no Executor handler does nothing, so a capability cannot be added by data.
**The opcode registry is code (the Executor's handler map); the operand vocabulary is
data (the ontology).**

## 3. Surface syntax — pipeline data-flow

```
@input | map(ent:product) | classify(tax:catalog) | insert(db:products, hidden=true)
```

Left-to-right; each stage consumes the previous stage's output (or the `@source`).
`map/classify/insert` are **code-owned opcodes**; `ent:product`, `tax:catalog`,
`db:products` are **ontology-typed operands**; `hidden=true` is a modifier.

### Lexicon

- **Opcodes** — `⟨id ∈ Executor.handlers⟩`. A closed, code-owned set. Prefer **many
  specific typed verbs** over few polymorphic ones (§10). e.g. `get map filter rank
  classify link resolve embed insert update delete route branch preserve review`.
- **Operand namespaces** — `tax:` (taxonomy node), `ent:` (entity type), `kg:`
  (knowledge-graph node), `rel:` (one of the 16 relation predicates), `db:` (store),
  `svc:` (nOS service), `doc:` (content). Path segments join with `/`.
- **Sources** — `@input @user @ctx @sel @prev` (`@prev` implicit across a pipe).
- **Modifiers** — `key=value`; `?key=value` = default applied only when absent.
- **Operators** — `|` flow · `=` bind · `:` namespace · `/` path · `,` sep · `()`
  call · `[]` set · `.` field · `#` comment · `?` default.

### Grammar (EBNF)

```ebnf
program   ::= pipeline
pipeline  ::= source? stage ("|" stage)*
source    ::= "@" ident
stage     ::= opcode "(" arglist? ")"
opcode    ::= EXECUTOR_HANDLER              (* validated against the code registry *)
arglist   ::= arg ("," arg)*
arg       ::= entity | kv | ref | literal
entity    ::= ns ":" path                   (* validated against the LIVE ontology *)
ns        ::= "tax"|"ent"|"kg"|"rel"|"db"|"svc"|"doc"
path      ::= ident ("/" ident)*
kv        ::= "?"? key "=" value
value     ::= literal | entity | ref
ref       ::= "@" ident ("." ident)*
literal   ::= STRING | NUMBER | BOOL | "null"
```

LL(1), regex-friendly, no backtracking.

## 4. Two authorities: KEAP validates, Wing executes

The single biggest structural fix. The Resolver is **not one component in KEAP** —
putting an executor with injected secrets inside KEAP would break its standing
invariants (KEAP never calls the LLM in-container; it is deliberately read-mostly).
Split it:

| | **KEAP** — meaning authority | **Wing / AgentKit** — executor |
|---|---|---|
| role | vocabulary + typechecker | dispatch + credentials + audit |
| endpoint | `POST /agent/v1/validate` | handler dispatch |
| does | tokenize → parse → typecheck against the live ontology → return **AST or typed error** | resolve creds (Infisical), call PHP/DB/svc, log to `events` |
| side effects | **none** | all |

Flow:

```
Intent (NL) ─► Claude (nos-lang) ─► pipeline
                                       │
             ┌── KEAP /agent/v1/validate ──┐        ┌── Wing executor ──┐
   pipeline ►│ parse → typecheck (ontology)│─ AST ─►│ authz gate        │
             │ → AST | TypedError          │        │ per-handler creds │
             └─────────────────────────────┘        │ dispatch + audit  │
                     (no side effects)               │ log corpus row    │
                                                      └───────────────────┘
```

KEAP stays the authority on *meaning*; execution goes where credential resolution +
agent-run **audit lineage** already live (`events`, `actor_action_id`). Bonus:
`/agent/v1/validate` is reusable for constrained decoding and the repair loop without
any executor in the path.

Layer separation (*what* vs *how*): Intent (user) → nos-cortex (LLM sees verbs +
entities only) → validate (KEAP) → authz + dispatch (Wing) → creds (Infisical, never
leaves host) → execution.

## 5. Validity ≠ security (the authz model)

**Parse-validity is not authorization**, and the plan's earlier "the type system is
the live knowledge graph, so validation is strong" is the weakest claim in it. That
an entity *exists* in the ontology says nothing about whether the caller may *touch*
it. Three requirements, none optional once write-verbs exist:

1. **Ontological membership ≠ authorization.** KEAP has a real authz model since
   v1.17 — the RBAC tier ladder in `getVisibleObjects` / `canReadObject`. Every
   operand access in an executed pipeline must pass it *for the calling identity*,
   not the system identity.
2. **Capability-scoped executor tokens, not the brain token.** `/agent/v1/*` is a
   single **system-scope** token with no per-viewer visibility — a documented,
   deliberate property *of a read surface*. The moment an executor sits behind that
   token, anyone holding the bearer can **write as the system**. The executor must
   use per-capability, per-identity tokens (which verbs, which namespaces, which
   tenant), issued and audited separately.
3. **Destructive verbs are guarded, not just grammatical.** `delete(db:products)` is
   perfectly valid grammar. Guaranteeing the LLM won't emit a nonexistent opcode does
   **not** guarantee it won't emit a harmful *valid* one. Required: `dry_run` default
   on mutating verbs (plan first, `?commit=true` to execute), a **confirm-gate** on
   `delete`/`update` (the destructive-op safety model nOS already uses elsewhere), and
   **idempotence keys** on writes so a retried pipeline can't double-insert.

## 6. Case-based execution (the local runtime — corrected)

The vision — a local, exact, inspectable decision runtime — is right and is real
differentiation. The *mechanism* in the first draft ("word2vec over the compression
language → decision trees") had a sequencing error:

- The closed token space makes the **output** side learnable from far fewer samples —
  true and essential. But the **input** side is still natural language; a closed
  vocabulary helps the *decoder*, not the *encoder*, and NL→features is the hard half.
- A word2vec over a short, template-y pipeline corpus whose co-occurrence is nearly
  determined by the grammar would mostly relearn the EBNF. And KEAP **already has a
  768-d nomic space** over the ontology, trained on real linguistic semantics — a
  home-grown word2vec over ~2000 tokens + a few hundred pipelines would be *measurably
  worse*.
- Decision-tree induction (input → pipeline) needs ~thousands of examples per pattern.
  nOS is personal / small-tenant — dozens of runs a week. That P4 would wait years.
- The draft conflated two different "trees": a pipeline **dataflow graph** (mostly a
  straight line; a tree only where `route`/`branch` appears) and a **learned
  classifier**. Different artifacts; conflating them bites in implementation.

**Instead — and it works from the first example: case-based reasoning over the
existing nomic embedding.** Embed the input (nomic, already deployed) → retrieve the
*k* nearest previously-executed inputs → if their pipelines agree and similarity
exceeds a threshold, replay with slot substitution; otherwise escalate to the API
LLM. This is:

- **inspectable** — "I did this because it resembles this thing you approved before,"
- **operational at n=1**, not n=1000,
- **exactly the P5 confidence-gated loop**, with nothing to train yet.

A *custom* embedding space is worth training only once the corpus is large enough to
have something to improve over nomic. It's **"not first," not "no."**

**Protect the corpus from write one.** `(input, pipeline, outcome, operator-correction)`
is human work-product — operator corrections are training substrate you cannot
recompute. It must have a **source outside the container from the first write**, or a
single data-dir swap wipes the training set — precisely the 2026-07-22 KEAP data-dir
replacement that silently dropped moderated relations (15 edges then; here it would be
all of P4). This is today's managed-resources lesson applied to the most valuable data
in the system.

## 7. Token economy is elsewhere than "short syntax"

Optimizing syntax length is the wrong target. A pipeline is ~20 tokens; the **primer**
(closed opcode list + namespace table + grammar + ~20 examples) rides in *every* call
at ~2000 tokens. So the levers are:

1. **Cache the primer** — it's static; it should be a cached system prefix, not re-sent.
2. **Don't send 1840 nodes into context.** The plan never said how the LLM knows the
   right operand is `tax:knowledge` and not one of the other 1839 — the *hardest* part
   of the whole thing. KEAP already has the answer: **`/agent/v1/context`**
   (budget-bounded, citable retrieval). nos-cortex must **build on it, not re-solve
   it** — which makes the context injector a **P2 prerequisite**, not a parallel branch.

## 8. Portability — honest version

§ "Cortex off nOS" must not promise *automatic* bootstrap of taxonomy/ontology at a
customer. Track D is explicit: a domain pack = **slug root + canonical files + golden
fixture + a recall-gate pass** — a *curated delivery*, not an auto-crawl. The honest
statement: **"Cortex at a company needs a domain pack, and building that pack is
work."** Portability is real (ontology + Executor + case-base are self-contained), but
the substrate is curated, not free.

## 9. Worked examples

```text
@input | map(ent:product) | insert(db:products, ?hidden=true, dry_run=true)
@input | embed() | classify(tax:knowledge) | route(?to=review, when=low_conf) | preserve(doc:inbox)
@user  | context() | resolve(kg:node) | link(rel:is-a) | rank(?by=relevance, top=5)
@sel   | link(tax:physics/cosmology, rel:curated/depends-on) | review(?queue=curator)
```

Note `context()` (node selection, §7), `rel:` operands drawn from the 16 predicates,
and `dry_run=true` on the mutating example (§5).

## 10. Answers to the open questions

- **Verb granularity → many specific, not few polymorphic.** Few polymorphic verbs
  push ambiguity into the Executor, where it becomes uninspectable magic and — worse —
  *untrainable*. The endgame is replacing the LLM with a local model, so optimize for
  it: specific typed verbs are smaller, more consistent classes with fixed slots. And
  since every opcode needs a handler regardless, "few verbs" doesn't cut implementation
  work — it hides it in handler branching.
- **Lexicon versioning → pin `ontology.version` AND `database.id`** (from health) into
  every corpus row. A model trained over a corpus from a *different database* speaks a
  different language even when version numbers match.
- **Confidence metric →** falls out of §6: similarity to the nearest precedent + the
  agreement among the *k* neighbors, calibrated against the operator corrections you
  already log.
- **Extraction boundary →** LLM proposes fields, Executor validates against the entity
  schema and fills defaults.
- **Transactions / partial failure →** per-stage idempotence keys + a pipeline-level
  compensation log; destructive stages gated (§5).

## 11. Roadmap (re-sequenced)

| Phase | Deliverable |
|---|---|
| **P0** | This spec. Opcodes = code-owned registry; operands = ontology; **authz model defined** (§5). Coordinate with KEAP `feat/ontology-sot` (don't move the pin — untagged). |
| **P1** | **`/agent/v1/validate` in KEAP** (tokenize → typecheck → AST\|error, **zero side effects**). Executor stub in Wing, **read verbs only**, capability-scoped token. |
| **P2** | **`/agent/v1/context` injector first** (else the LLM misses the entity), *then* teach Claude nos-lang (primer + AgentKit agent). Measure validity rate. |
| **P3** | Write verbs behind the authz + dry-run/confirm gates; **corpus with versioned rows, stored outside the container**. |
| **P4** | **kNN case-based execution over the nomic space** (works from n=1) + pipeline→tree visualization in KEAP. Custom embedding only once the corpus warrants it. |
| **P5** | Confidence-gated local execution; escalate + teach-back on novelty. |
| **P6** | Standalone Cortex (with a curated domain pack, §8). |

## 12. Relation to existing nOS pieces

- **KEAP (Cortex)** — owns the ontology, `/agent/v1/validate`, `/agent/v1/context`,
  the case-base corpus, and (later) the local model. Read-mostly, no LLM in-container.
- **Wing / AgentKit** — the **executor** (dispatch, authz, Infisical, audit lineage in
  `events`), and host of the NL→pipeline agent.
- **Bone / Infisical** — credential resolution inside the executor's handlers.
- **The point:** today the ontology is knowledge you *read*; nos-cortex adds a
  **code-owned opcode layer over ontology-typed operands** — the knowledge layer gains
  an instruction set, with meaning and execution kept in separate authorities.
