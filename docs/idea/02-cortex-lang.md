# 02 — cortex-lang: an ontology-typed pipeline IR

**Status: design frozen (P0 spec, freeze-ready after two review rounds). The
Wing executor now EXISTS (`files/anatomy/wing/app/Cortex/`, 2026-08-09) and
executes two of its seven verbs; the other five wait on KEAP routes that are
not published yet — see [What is actually built](#what-is-actually-built).**
**Detail:** [`nos-cortex-lang.md`](../archive/nos-cortex-lang.md) ·
[`nos-cortex-lang-wing-executor.md`](../archive/nos-cortex-lang-wing-executor.md)

## The idea

An LLM emits a **typed plan** against a known ontology. The plan is validated,
then executed **locally**. The model never executes anything, and:

> **A capability may never be added by data.** Facts about an entity are data,
> declared once and inherited. What may *act* on an entity is code, per runtime,
> hash-compared — never addable by declaring it.

That single rule is what separates this from "let the model write SQL".

## External evidence the shape is right

WrenAI (audited 2026-08-02, `technosideas/wrenai.md`) independently converged on
three of the same decisions: the zero-side-effect validate/execute split, a
compiled-and-hashed contract artifact, and a confirmed-pair corpus stored as
files with a derived, rebuildable index.

**Nothing is importable.** Their LLM still emits free-form SQL and their
validator is sqlglot/DataFusion-bound. The value is the confirmation.

## The lesson to NOT copy, which is sharper than the confirmation

WrenAI's headline repair affordance: a failed validation returns **the available
columns**. That is an enumeration oracle — already forbidden by the round-2
review. They can afford it (single-tenant, no user model at all in OSS); nOS
cannot.

**The most attractive-looking feature is the one to reject**, and it is worth
carrying that as a design guard rather than a footnote.

Their issue #2409 is the argument *for* a closed vocabulary: `read_csv(/etc/passwd)`
blocked in `FROM` but allowed in a projection, closed with a maintained
**denylist** rather than fail-closed. That is the standing cost of a free-form
expression language.

## What is actually built

| piece | state |
|---|---|
| `POST /agent/v1/validate` in KEAP | live |
| opcode registry + hash compare | live (Wing refuses to boot on a published opcode with no handler) |
| `onto1:` ontology hash gate | live, pinned |
| `agent:` + `delegate` (contract **v2**) | live in the registry; validates, executes nothing (mutating) |
| **Wing executor** | **present, and refuses five of its seven verbs** |

The executor is the capability boundary — three-axis scoped tokens
(`verbs`/`namespaces`/`tenants`). `files/anatomy/wing/app/Cortex/` landed on
2026-08-09 (`901ec719`): registry, capability, binding gate and seven handlers,
of which `get` and `resolve` execute and the other five extend
`LateBoundHandler`. That is not modesty about untested code — it is a
**measurement about the other side**: KEAP publishes no taxonomy/search/
classify/embed route to any bearer Wing holds, so those five verbs have nothing
to bind to yet.

Until they bind, [06](06-genome.md)'s hydrator still has nowhere to land for
anything but `get`/`resolve`.

## The two nouns the language was missing (shipped 2026-08-10, contract v2)

The loop needs to name **which agent** and **which model**, because swapping the
provider is how it learns.

```
@input | delegate(agent:librarian, ?via="openclaw-qwen2.5-coder:32b")
```

- `agent:` is a namespace with policy `deferred` — Wing decides, and **KEAP
  never enumerates agents**, which would be exactly the enumeration oracle this
  file rejects two sections above. A name nobody has deployed validates
  identically to one that runs nightly; that is the test.
- `?via` is a **param**, typed `model-uri`, whose value is the AgentKit URI.

**The first draft of this section was wrong and the correction is the useful
part.** It proposed `?via=model:anthropic-claude-opus-4-7` — a `model:`
namespace in the kv slot. *That does not parse.* `parseValue` accepts
`string | dotted_word`, `:` is its own token, so the value ends at `model` and
the colon is a syntax error. The suite now opens with that refusal as a test,
so the shape cannot come back.

The correction is better than the original rather than a workaround. A model is
not something the chain **operates on** — it is a hint about who runs the stage
— so it belongs in a param. And it must be **quoted**, because real model tags
carry colons: this box serves `qwen2.5-coder:32b`, `nomic-embed-text:latest`,
`hermes3:8b`. A quoted string is the one slot in this grammar that carries
another vendor's punctuation unedited, which is what
[`foreign-properties`](../doctrine/foreign-properties.md) asks of us — we own
the provider prefix, ollama owns everything after it.

The provider vocabulary is declared three times today (`agent.schema.yaml`,
`Factory::fromUri`, `test_agentkit_naming.py:89`) and `MODEL_URI_RE` is now a
fourth — one source, the rest derived (`w-provider-list`).

**The provider is a binding, not a fact in the sentence, and that is what makes
the loop work.** If a chain pinned its provider, the loop could only change
providers by rewriting chains — and then every experiment varies two things at
once and no run is comparable to another. The sentence is the constant; the
binding is the variable; the run records both. That is also the only reading
consistent with `CORTEX_SCOPE.authorizes === false`.

### `?via=` narrows, it never widens

The asymmetry is the whole safety argument, and it is worth stating as a rule
rather than a caveat:

> **Data may narrow a permission. Data may never widen one.**

`?via=model:openclaw-…` as a *restriction* — "this must not leave the box" — is
safe by construction: it can only subtract. Personal data under a residency rule
needs exactly this. `?via=` naming a remote provider is a *request*, which the
binding gate must approve anyway and whose refusal is recorded. What is
forbidden is `?via=` read as a command. The `?` arg form already carries
`defaulted: true`, so this is a change of meaning, not of grammar.

### `delegate` is a macro, and macros expand BEFORE the gate

One skill that performs what would otherwise take several is a macro, and a
macro adds no capability **only if the gate meets the expansion rather than the
name**. Three conditions, all load-bearing:

1. Expansion runs before `CortexBindingGate`, so every verb is authorised
   individually against the caller's scoped token.
2. The 16-stage limit counts the **expanded** chain. Otherwise a macro is a
   limit bypass.
3. The audit records both — the named macro and what it became. The model learns
   at the abstraction, the gate judges the concrete, and the training corpus has
   both levels.

**`delegate` is declared `mutating`, and that is not a formality.** Running an
agent spends tokens, may write memory, and can reach whatever the agent's own
scopes allow. P1 refuses every mutating stage at the door — so `delegate`
**validates today and executes nothing**, which is the honest state until every
agent run goes through one runtime (`w-agentkit-spine`). It also means Wing
needs no handler yet: the coverage gate excludes mutating opcodes precisely so
it never demands dead code.

## Declarative sentences: yes, but not in this grammar

The pipeline is functional and strictly linear (`source? stage ("|" stage)*`).
Two extensions were weighed on 2026-08-09:

- **Longer functional sentences — take it.** Named intermediates and fan-in turn
  the chain into a DAG. Still no side effects before execution, still a closed
  vocabulary, still validatable.
- **Declarative statements — not here.** A declarative sentence says what
  *holds*, not what to *do*, and admitting both into one grammar requires a
  general expression language. That road ends where WrenAI's did, five sections
  above: `read_csv(/etc/passwd)` blocked in `FROM`, allowed in a projection,
  closed with a maintained **denylist**. A denylist is the opposite of
  fail-closed.

The declarative layer therefore lives **outside** as its own typed artifact,
compiled into a cortex chain that still meets the gate. It may be rich precisely
because it executes nothing.

**The engine for it is chosen** (`w-datalog`): vendor
`datalog_reasoner.py` from [semantica-agi/semantica](https://github.com/semantica-agi/semantica)
— 16 KB, MIT, semi-naive bottom-up fixpoint with **termination guaranteed on
finite graphs**. Not the package: its *required* dependencies include torch,
transformers, spacy, opencv-python and librosa. And not the file byte-identical
either: beyond stdlib (`re`/`collections`/`dataclasses`/`typing`) it imports
two semantica-internal modules — a logging wrapper and a 1,656-line
`progress_tracker` — at seven call sites, so the vendored copy strips those as
its first declared divergence.

**Termination is necessary, not sufficient** — the same distinction the estate
already draws for STRICT health waits. A model-authored rule that terminates
can still be a resource bomb at this estate's own scale, measured on the
candidate: the textbook 2-rule ancestor closure over a 790-node chain (the
taxonomy's size) derives 312,444 facts in ~142 s; `pair(X,Y) :- node(X),
node(Y)` derives 624,890 facts in ~2 s, and the 3-variable variant is ~493M
facts. `derive_all()` loops until the delta empties with no cap of any kind,
and scaling is cubic on chains. So the second declared divergence is **hard
budgets as a vendor condition**: `max_derived_facts`, `max_iterations` and
`max_seconds`, each failing closed with a diagnostic when exceeded.

**Upstream's parser is fail-open, and closing it is the third vendor
condition.** Body parsing is a regex findall that keeps what matches and never
checks the residue: `p(X) :- q(X), not r(X).` is accepted with the `not`
silently stripped — deriving the semantic *inverse* of the author's intent —
and a comparison guard (`A > 18`) vanishes the same way; a ground query on a
true fact answers no (the empty-binding row is dropped). The vendored parser
must tokenize strictly and **raise on any unconsumed input** — negation,
operators, anything outside pure positive Datalog — and fix or forbid ground
queries. All three divergences are declarations in the vendor-contract sense
(compare declarations, not bytes): the gate
`tests/anatomy/test_cortex_lang_vendor_conditions.py` holds this document to
them today and holds the vendored copy to them the day it lands.

Its scope is **derived, not chosen**. Datalog over a graph is an enumeration
oracle, and this estate already refuses `kg:`/`ent:` at namespace granularity
*without issuing a query*, so that no timing oracle survives. Rules may
therefore read only what the caller could already enumerate wholesale — `tax:`
and `rel:`, the two `resolved` namespaces. Their Rete engine is deliberately
**not** taken: their own README warns its matcher is "intentionally simple" and
says not to wire it into production compliance gates.

## Next

Two of seven verbs execute. The next move is on the KEAP side — publish the
routes the remaining five late-bind against — not on Wing's, where the handlers
are already waiting for them.
