---
name: weakness-scan
description: Ask the nOS loop engine what is currently wrong with the estate — a ranked, evidence-carrying list drawn from the working tree, the security remediation queue, scan freshness, the hidden-fees ledger and the corpus-diff ledger. Use before proposing any change, and whenever asked "what should I fix next".
---

# weakness-scan — ask, do not assess

Read `../../ENGINE.md` first. It holds the base URL and the token; this file
holds neither.

One call. You are a reader of the engine's answer, not a second opinion on it.

## The call

```bash
curl -sS -H "Authorization: Bearer $(tok loop_propose_token)" \
     "$BASE/api/v1/loop/weaknesses?top=10"
```

Optional narrowing, all of it output-only: `top=N`, `source=<name>` (repeatable),
`min_severity=<level>`. These select and truncate. **No parameter can make a
weakness look better than its source says it is** — if you find yourself reaching
for one to get a shorter list, you are editing the finding, not the report.

## What you do with the answer

Present it. The order is the engine's ranking — do not re-sort by your own sense
of importance, do not merge items you think are duplicates, do not drop the ones
you cannot act on. Each item carries a stable `weakness_id` and an `evidence_sha`;
both are load-bearing downstream (`propose` needs the id, and the `evidence_sha` is
what lets a previously-refused fingerprint unblock when the evidence moves).

## Three fields you may never drop

- **`complete`** — false whenever any source failed to report.
- **`degraded_sources`** — which ones.
- **`self_reported_sources`** — sources whose freshness is a claim rather than an
  observation.

If `complete` is false, say so **in the same sentence as the count**. "No
weaknesses found" and "no weaknesses found, and the list is partial" are
different statements, and collapsing them is `docs/hidden_fees/08` — absence
reading as success — which is precisely the defect this whole loop exists to
detect. An empty list from a degraded read is not an all-clear.

## Refusals

- `503` — the loop tokens are not configured on this host. Say that. Do not
  route around it by running scanners yourself.
- `403` — you are not on loopback, or the token is wrong. Report; do not retry
  with a different credential.

## What this skill never does

- Never runs the underlying scanners directly. The engine reads them the same way
  for Claude Code, for Hermes and for a 03:00 Pulse job; a hand-run scanner gives
  a number none of those three can reproduce.
- Never invents, estimates or infers a weakness that is not in the response.
- Never assigns a severity. Severity comes from the source, through the engine.
