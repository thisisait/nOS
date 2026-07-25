# nos-cortex-lang — KEAP consumer review, round 2

Status: **review of the revised nOS design plan (2026-07-24).** Written from the
KEAP side against v1.26.0, which is the substrate the plan builds on. Round 1
(delivered as prose) corrected three structural errors — opcode source, Resolver
placement, missing authz — and one sequencing mistake. All four landed. This
round reviews what the revision opened up, evaluates a third-party critique that
came with it, and names three problems nobody in the loop has raised.

Round 1's corrections are **not** re-argued here; where the revised plan already
states them, this document only notes follow-through that is still missing.

## 1. Verdict

The revision is sound and is ready to freeze as P0 after the changes in §6.
`operands are ontology-typed, opcodes are code-owned` is a better thesis than the
one it replaced — more accurate *and* more useful, because it puts the closed
vocabulary exactly where the combinatorial risk lives.

Two things about it are genuinely well made and should survive further editing:
the layer separation (the LLM never sees credentials or transport), and the
read-only P1 with zero blast radius. Both are the kind of decision that is cheap
now and impossible to retrofit.

## 2. The two-authority split needs a second half

`§4` gives KEAP the typechecker and Wing the executor. Correct. But of the seven
operand namespaces, only `tax:`, `kg:` and `rel:` are ontology-backed. **`db:`,
`svc:` and `doc:` do not exist in KEAP at all** — they are infrastructure
references, and `/agent/v1/validate` cannot typecheck them.

So validation is inherently **two-phase**:

| phase | authority | validates | against |
| --- | --- | --- | --- |
| 1 | KEAP | `tax:` `kg:` `rel:` `ent:` | the live ontology |
| 2 | Wing | `db:` `svc:` `doc:` | the handler/resource registry |

This must be written down. Left implicit, the first implementer to notice that
"validation happens in two places" will consolidate it — by handing KEAP a list
of databases, which reinstates exactly the coupling §4 removed.

`ent:` needs an anchor while this is being written: KEAP has an
`object_type_definitions` table, which is the plausible backing. Name it in the
spec or it will be invented a second time.

## 3. `/agent/v1/validate` is an enumeration oracle

Not raised anywhere so far, and it is a security property, not a detail.

An endpoint that answers *"does this operand exist?"* lets any caller enumerate
the taxonomy and the object corpus — **including entries they have no right to
read** — by asking. A surface with no side effects is not automatically a surface
with no disclosure.

KEAP has had this exact bug shape and fixed it: until v1.17, `GET
/api/objects/:id` gated only on `visibility === 'private'` and leaked
tier-scoped cards to any authenticated caller. The fix was to gate through
`canReadObject` and return **404 for not-found and not-readable alike**.

`validate` needs the same discipline:

- resolve operands against the **calling identity**, never the system identity;
- return a uniform `unknown operand` for both "does not exist" and "not yours" —
  distinguishable errors are the disclosure;
- and note that this interacts with §5 of the plan: the authz gate cannot live
  only in the executor, because validation already answers questions.

## 4. Operand syntax does not match KEAP identifiers

Three concrete defects, all checkable against a live system:

1. **The examples do not typecheck.** `link(rel:is-a)` — `is-a` is not among the
   sixteen predicates (`specializes` / `generalizes` / `exemplifies` are the
   near ones). `rel:curated/depends-on` — verbs are flat ids, there is no
   `curated/` prefix. In a specification whose subject is validity, and whose
   examples become the primer's training material in P2, examples that the
   validator would reject teach the model the wrong language.
2. **Path separator.** The grammar says `path ::= ident ("/" ident)*`, but KEAP
   ids are **dotted**: `01.01.03`, `nos.services.bookstack`. A `/`-form forces a
   translation layer between the language and the real identifier, which is
   friction plus a fresh ambiguity (`tax:nos/services` — is that the node
   `nos.services`?).
3. **Recommendation:** adopt the native id form directly — `tax:nos.services.
   bookstack`. The validator then does an exact lookup instead of a translation,
   and a whole error class disappears.

## 5. On the third-party critique

Evaluated point by point, because its quality is uneven and two of its remedies
would do harm as written.

### 5.1 Late-binding operands — accepted, and it supersedes round 1's advice

The proposal: let the LLM write a human term (`ent:product[tričko]`) and have
KEAP resolve it to a canonical id during validation.

This is better than what round 1 recommended. Round 1 said "the context injector
is a P2 prerequisite", which implies a lookup turn *before* generation — two API
round-trips per action. Late-binding collapses that to one, keeps the 1840 ids
out of the model's head entirely, resolves inside the authority that owns the
vocabulary, and leaves an auditable AST carrying **both** the surface term and
the id it resolved to.

It also re-sequences `/agent/v1/context`: that endpoint stops being the gate for
entity selection and becomes the fallback for genuinely ambiguous cases plus the
carrier for rules and evidence. It moves from hard prerequisite to parallel work.

**One guard is mandatory.** Fuzzy resolution must never silently take the nearest
match. When a term matches several nodes at comparable scores, the validator
returns a typed `ambiguous operand` with the candidate list; it does not choose.
The reason is written into this repository: `knowledge/ingest.mjs` carries an
identity-drift detector precisely because a **valid-but-wrong id is
indistinguishable from a correct one after the fact** — every reference still
resolves, nothing downstream reports anything, and the graph looks healthy. A
silent nearest-match would move that failure into the execution path, where it
is more expensive.

### 5.2 kNN blindness to negation — real, but §5 of the plan already contains most of it

The failure case (`"add a red shirt, hide it"` vs `"...but DO NOT hide it"`
embedding at >0.9 similarity while meaning the opposite) is correct, and it is a
well-known weakness of cosine similarity.

What the critique missed is that the revised plan's dry-run gate already catches
the consequence: mutating verbs default to `dry_run`, and `delete`/`update` sit
behind a confirm-gate. A mis-replayed precedent therefore produces a **plan, not
an effect**, and the operator sees `hidden=true` before commit.

So the remedy is not a local 3B parameter-extraction model (heavy, premature).
It is two sentences of specification:

- **kNN replay never bypasses the dry-run gate.** Ever, at any confidence.
- **Modifiers are not inherited from a precedent.** Retrieval supplies the
  pipeline *shape* (the opcode sequence); values and boolean flags do not ride
  along.

And because this project already has a doctrine for measuring semantics, the
threshold should be earned rather than assumed: build a **replay gate** on the
model of `scripts/recall-gate.mjs`, using adversarial minimal pairs (the same
input with and without a negation). The recall gate earned trust by
demonstrating *discrimination* — a templated target failed, the healthy fixture
passed. A similarity threshold with no such proof is a number, not a guarantee.

### 5.3 No constrained decoding — right direction, dangerous remedy, better option missed

The premise holds: the Anthropic API exposes neither logit bias nor grammar
masking. The quoted "2–5 % syntax error rate" is unsourced, and the plan already
says P2 measures the validity rate — so it is a thing to measure, not to design
around.

The remedy as proposed is the problem. **A normalizer that rewrites
`@input.map(...)` into `@input | map(...)` is guessing intent.** Silently
permissive repair reintroduces ambiguity into the one layer whose entire purpose
is to remove it, against stated goal (1). If a normalizer exists it must be
**total and provably meaning-preserving** — whitespace, trailing commas, quote
style — with everything else going to the repair loop as a typed error. And every
normalization must be logged alongside the raw emission, or the corpus records a
pipeline the model never produced and the training set quietly diverges from the
generator.

**The missed option is stronger than either.** The Anthropic API *does* offer
constrained decoding; it is called a tool schema. Have the model emit the **AST
as a structured tool call** — types and required fields enforced by the API, not
by prompt discipline — and render the pipeline surface *from* the AST for humans
and for the corpus. The only argument against structured JSON was verbosity, and
§7 of the plan already concludes that **token count is not the constraint**. With
that argument gone, this buys goal (1) at the protocol level rather than by
hoping. It should be evaluated before anyone writes a repairer.

### 5.4 Linear pipelines cannot express conditionals — real gap, wrong urgency

Correct that `source? stage ("|" stage)*` cannot say "if it exists, update;
otherwise create".

But admitting control flow into the IR is a large decision that trades against
the plan's own priorities: it moves the language toward a programming language,
costing parse simplicity (goal 1) and trainability (goal 3) — **every branch in
the grammar is a branch the local model must learn to predict**, which is the
bet P4/P5 rests on.

The critique dismisses the alternative with an argument that does not hold: that
an `upsert()`-style verb "pushes complexity into the Executor and loses
inspectability". Inspectability is not lost — `dry_run` returns a **plan**, and
the plan shows which branch was taken. The complexity sits in the handler; the
decision remains visible.

**Recommendation:** keep the IR flat through P3 and decide this on evidence — the
real cases that cannot be expressed flatly — rather than on a hypothetical.

### 5.5 Hardware ceiling — aimed at a design the revision abandoned

Most of this point argues against the *original* framing (word2vec, decision
trees, a local general-purpose LLM). The revised §6 is case-based kNN over the
nomic space; nomic is ~137M parameters, so P4's memory budget is close to
nothing and the 12–16 GB calculation does not apply to it.

The underlying concern is nonetheless better grounded than the critique knew:
this host runs at least twenty containers concurrently (KEAP, Superset, Metabase,
Qdrant, Outline, BookStack, ONLYOFFICE, Postgres, QGIS, …). Headroom for
inference is genuinely thin.

And it contains one idea nobody else raised, which may be the strongest
long-term move available: **the P3 corpus is not only a case base, it is a
fine-tuning set.** A small model fine-tuned to emit this grammar will beat a
large general model at this narrow task — which is the path to removing the API
LLM from the hot path entirely, with kNN demoted to the confidence gate rather
than the executor. Worth carrying in the plan as an explicit P5 alternative.

## 6. Three problems nobody has raised

### 6.1 The ontology moves; precedents rot silently

The operand vocabulary is a **live** ontology that grows under moderation (Track
T grown nodes, R3 vocabulary growth). Pinning `ontology.version` into a corpus
row is necessary but not sufficient: a precedent whose operand was since renamed
or retired will, on replay, resolve to **something else** rather than fail.

This is the identity-drift problem again, one layer up. The case base needs the
same treatment ingest gives the taxonomy: a precedent whose operands have drifted
is **invalidated, not replayed**. Cheapest form: store the resolved id *and* the
name it had at capture, and compare on retrieval — exactly what
`applyDomain()`'s `priorNames` check does across the delete/insert boundary.

### 6.2 The corpus is instance-level data, and that collides with the substrate's own privacy line

This is the most serious item in this review.

`docs/specs/ontology-anchoring.md` §6 states, as an explicit non-goal, that no
instance-level data (people, cases-in-progress, account state) belongs in the
concept graph — and calls that boundary *the product's privacy line, not a
limitation*. The R4 spec restates it: KEAP records that *a citizen* needs a
licence, never whether a named person holds one.

The Cortex corpus — `(input, pipeline, outcome, operator-correction)` — is
instance-level **by construction**. It is specific sentences from specific people
about specific data.

The concrete hazard is not abstract. The revised §6 proposes kNN **over the
existing nomic space**. If corpus inputs are embedded into the same `embeddings`
table, knowledge retrieval will return them: `/api/search`, the hybrid recall
path, and `/agent/v1/graph` all read that space. A user's knowledge question
could surface another user's operational input. There is precedent for a stray
kind lingering in that table — the legacy `note:` embeddings are already carried
as known debt.

**Requirement:** the corpus gets its own store and its own index — not merely a
different `kind` in the shared table — and is explicitly excluded from knowledge
recall, with its own retention and visibility rules. This is a **P0 decision**,
not a P3 one: after P3 the data is already there.

### 6.3 Validation and execution do not happen at the same time

KEAP typechecks against the ontology at T; Wing dispatches at T+n. A converge or
an ingest between them changes the vocabulary underneath the AST. Either ASTs
carry a short TTL, or the executor revalidates at dispatch. Cheap to decide now,
awkward later.

## 7. What KEAP now provides (v1.26.0, released 2026-07-24)

The substrate the plan depends on, stated precisely so it is not misread a
second time:

- `GET /agent/v1/health` → `ontology: { verbs, toeRelations, curatedRelations,
  byStatus }`. **`verbs` is an integer count, not a vocabulary.**
- `GET /agent/v1/relations` → `types[]` is the verb list — 16 **relational
  predicates**, agent-token gated.
- `GET /agent/v1/health` → `database: { id, initializedAt, freshThisBoot }`. Pin
  `id` into every corpus row alongside `ontology.version` (§10 of the plan): a
  model trained over a corpus from a different database speaks a different
  language even when the version numbers agree.
- `knowledge/ontology/` is the versioned SoT for the verb registry and the
  moderated edges; `knowledge/_schema/ontology-format.md` is its contract.

Not yet built, and named as dependencies by the plan: `/agent/v1/validate`,
`/agent/v1/context`.

## 8. Recommended changes before freezing P0

1. Write down the two-phase validation split (§2), and anchor `ent:` to
   `object_type_definitions`.
2. Make `validate` authz-aware with a uniform `unknown operand` (§3).
3. Adopt native dotted ids; fix the examples so they typecheck (§4).
4. Adopt late-binding operands **with mandatory ambiguity rejection** (§5.1).
5. State that kNN replay never bypasses dry-run and never inherits modifiers
   (§5.2).
6. Evaluate structured-output (tool-schema) emission of the AST before
   specifying any normalizer (§5.3).
7. Decide the corpus store and its exclusion from knowledge recall (§6.2).
8. Add precedent invalidation on operand drift (§6.1) and an AST TTL (§6.3).

Left open deliberately, to be decided by measurement at the end of P3: control
flow in the grammar (§5.4), and a fine-tuned local emitter (§5.5).
