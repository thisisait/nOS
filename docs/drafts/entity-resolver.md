# Entity resolver — rough design draft

Problem restated: a spoken sentence names a thing in ordinary language, the
model must produce an operand that EXISTS. qwen3:14b's two chain-benchmark
failures were `unknown_operand` / `namespace_not_resolvable` — a world-model
gap, not a grammar gap. Operator's proposal: fan out read-only probes,
grade only the green hits, ask when ambiguous.

## 1. Probe set

| probe | good at | cost |
|---|---|---|
| `tax:` lookup (KEAP taxonomy, exact/prefix) | canonical concept names, "bezpečnostní nálezy"→domain node | offline-ish: one KEAP HTTP call, `resolved` namespace, cheap |
| `rel:` traversal from a resolved tax node | "tabulka nápadů" → which table backs a concept once the concept is found | same call class as tax, chained |
| openapi operationId/summary fulltext (`wing.openapi.yml` + `bone.openapi.yml`, 117+ ops) | matching a verb phrase to a real endpoint — this is the exact case that 404'd | **offline, no service**: static YAML, grep/embed once at build time |
| `state/keap-tables/*.table.yml` `anchors` fulltext (18 tables) | "tabulka nápadů" → `roadmap`/`ideas` table by its declared anchor words | **offline, no service**: static YAML |
| `state/manifest.yml` fulltext | service/domain/port name resolution ("otevři gitea") | **offline, no service**: static YAML |
| vector similarity over doctrine (`docs/`, `files/anatomy/docs/`) | fuzzy paraphrase → the right guide/concept, not an operand | needs an embedding index + store — the one probe that costs a service |

Two are free (openapi + table + manifest fulltext are really one bucket:
static-file grep/embed, no daemon, sub-millisecond). One is one KEAP HTTP
round-trip (tax/rel, already a `resolved` namespace call the caller may
already make). One is a genuine service dependency (doctrine vector search)
and should be the last one tried, not the first.

## 2. The oracle problem — where the line is

02-cortex-lang's refusal is about **namespaces the caller could not already
enumerate**: `kg`/`ent` are refused at namespace granularity specifically so
no operand-shaped probing distinguishes "exists but denied" from "does not
exist" — a timing/error oracle over private structure.

Working answer to test: **a probe may only read what the caller could
already enumerate wholesale.** Concretely:
- `tax:`/`rel:` — already `resolved`, already enumerable by contract. Fine.
- `wing.openapi.yml`/`bone.openapi.yml` — published, versioned, the caller's
  own contract surface. Fine — this is not new information, it's an index
  over information already handed out.
- `state/keap-tables/*.table.yml` anchors, `state/manifest.yml` — committed,
  non-secret, already grep-able by anyone with repo/estate read access. Fine.
- Doctrine vector search — doctrine is also public/committed. Fine as a
  *ranking* aid, but it must never be the thing that decides existence; it
  can only re-rank among candidates already surfaced by an enumerable index.

What this forbids in practice: a probe against `kg:`/`ent:`, a probe against
`agent_credentials`/vault contents, a probe against another tenant's private
data, or any probe whose GREEN/RED distinction depends on data the caller
has no other way to see. It does **not** forbid the vector index existing —
only forbids it standing alone as an existence oracle. The line survives
because every probe here answers "how do I say the thing I could already
find", never "what do you have".

## 3. The grader — should it be a model?

No. Every candidate property is code-checkable:
- exists (matched a real operationId / table / manifest key / tax node)
- resolves (the operand round-trips through the same validator the executor
  uses — reuse it, don't re-derive it)
- in scope (caller's token covers that namespace/tenant — same check the
  executor already does at bind time)

Grading exists/resolves/in-scope with a second model is exactly "a model
grading a model" the estate already refuses (audit-chain-verifies-
consistency-not-key: a checker built from the same class of thing it checks
is blind to a shared failure mode). Recommend: **grader is a deterministic
scorer** — run the candidate operand through the real validator
(`/agent/v1/validate` or Wing's Cortex binding gate), rank by
(validator accepted?, probe-source priority, string-similarity score to the
spoken phrase). A model is allowed to RANK ties for phrasing quality, never
to decide existence.

## 4. Ambiguity — top-N and stop

Use the existing `agent_questions` table, `kind: choice`, `options_json` =
the top-N candidates. It already has everything this needs: resolve-once,
first-responder-wins, answerable from Telegram/ntfy/Wing without a session,
`expires_at` + `default_on_expiry` for the "operator never answers" case,
and `actor_action_id` lineage back to the session that asked. Building a
second channel would duplicate all five of those properties for no gain.
Fits directly: `kind='choice'`, `severity` low/medium, N configurable
default 3 passed as the row's `options_json`.

## 5. The ceiling — query budget

Measured constraint: one 32B model starved the validator it was judged by —
i.e. speculative concurrent load against a shared local service is a real
failure mode on this box, not a hypothetical.

Budget: **cap at 4 probes per spoken sentence, only 1 of which may be the
service-backed doctrine-vector probe.** Enforcement order, cheapest first,
short-circuit on first confident (single, high-score) match:
1. openapi/table/manifest static fulltext (all three, in-process, no cap needed — they're grep)
2. `tax:`/`rel:` KEAP call (1 round trip, sequential not fanned-out)
3. doctrine vector probe — only if 1+2 produced zero or ≥2 tied candidates, and only once, never re-tried per retry-loop iteration.

Enforced the boring way: a counter passed down the resolve call, hard
`raise` past 4, no retry-with-backoff around the vector probe (one shot).
No new scheduler needed — this is a function-local budget, not a service.

## 6. Smallest first version — a measurement, not a feature

Ship nothing that touches `agent_questions` yet. First cut: a script that
takes the same qwen3:14b chain-benchmark transcript that produced the two
failures, runs ONLY probe bucket 1 (openapi + table + manifest static
fulltext, no KEAP call, no vector index) against the failing utterances, and
reports: would this alone have resolved `unknown_operand` /
`namespace_not_resolvable`? If static fulltext alone closes both observed
failures, the KEAP/vector probes and the ambiguity UI are premature — build
them when a NEW failure mode shows up that static fulltext can't cover, not
before.

```python
# sketch only — not run
def resolve_static(phrase: str, indexes: dict[str, list[str]]) -> list[tuple[str, str, float]]:
    """indexes: {'openapi': [...summaries], 'table': [...anchors], 'manifest': [...names]}
    returns (source, candidate, score) sorted desc, capped at top-3."""
    import difflib
    hits = []
    for source, entries in indexes.items():
        for entry in entries:
            score = difflib.SequenceMatcher(None, phrase.lower(), entry.lower()).ratio()
            if score > 0.3:
                hits.append((source, entry, score))
    return sorted(hits, key=lambda h: -h[2])[:3]
```

skipped: embeddings, a real ranker, any service call — measure whether
`difflib` fulltext over already-published contracts closes the two known
failures before adding anything with a network hop.
