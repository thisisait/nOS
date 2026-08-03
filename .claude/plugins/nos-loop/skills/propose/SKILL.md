---
name: propose
description: Record one bounded change with the nOS loop engine before making it — read the budget, POST the proposal, obey the refusal. Use when acting on a weakness from weakness-scan, or whenever a change is meant to be judged and remembered rather than just applied.
---

# propose — record first, change second

Read `../../ENGINE.md` first. It holds the base URL and the token; this file
holds neither.

You are the proposer. You hold `loop_propose_token`, which carries `read` and
`propose` and **not** `judge`. You cannot trigger the judgment of your own work.
That is not an inconvenience to route around — it is constraint A at the
credential level. In a self-improvement loop the verdict is the reward signal for
the next modification, so a proposer that can reach its own verdict does not
merely lie, it optimises against the lie.

## Order of operations, and it is not negotiable

**Record the proposal before you touch a file.** A proposal recorded after the
change is a description of what happened, and the ledger's whole job is to know
what was *attempted* — including the attempts that were refused, and the ones
that were killed halfway.

### 1. Read the budget

```bash
curl -sS -H "Authorization: Bearer $(tok loop_propose_token)" \
     "$BASE/api/v1/loop/budget?gate_set=<set>"
```

The response is the authority on allowed roots, forbidden paths, size caps and
the closed `intent_class` enum. **This document lists none of them, deliberately.**
If you do not know which intent class fits, take it from the budget response, or
from the engine's refusal — which names the enum. Do not guess it from here and
do not carry it between sessions.

### 2. POST the proposal

```bash
curl -sS -X POST -H "Authorization: Bearer $(tok loop_propose_token)" \
     -H 'Content-Type: application/json' \
     -d '{"weakness_id":"…","intent_class":"…","target_paths":["…"],
          "gate_set":"…","tree_sha":"<git-rev-parse-HEAD>",
          "proposer_id":"agent:claude-code","diff_text":"…"}' \
     "$BASE/api/v1/loop/proposals"
```

`tree_sha` is `git rev-parse HEAD` — the tree the proposal was written against.
It is context, not control: when the proposal is judged, the engine applies the
stored diff at a base IT chooses (the repo's HEAD at judge time), so a declared
tree_sha never selects the tree a verdict is about. `proposer_id` names who is
proposing (`agent:claude-code`). The diff field is `diff_text`; it was written
here as `diff`, and together with the two missing fields that made every
documented proposal a 422 — the skill described a call that could not be made.

`weakness_id` comes from `weakness-scan`, unedited. `target_paths` are exactly
the files you intend to change — declaring a path you do not touch is as wrong as
touching one you did not declare.

### 3. Read the answer

- **`201`** — you get a `uuid` and a `fingerprint`. Keep both; the judge needs the
  uuid, and the fingerprint is how history knows this attempt.
- **`409`** — refused. The body names the offending path and the judge that claims
  it, or says the fingerprint is exhausted. **Quote the reason and stop.**

## The refusals, and what not to do about them

**Do not pre-filter.** Do not decide locally that a path is probably forbidden and
quietly pick another. The budget is enforced by the engine so that it means the
same thing here, in Hermes, and in an unattended Pulse cycle. A check you perform
in your head is a boundary that exists in one client only.

**Do not perturb.** If a fingerprint is exhausted, do not re-offer the same
attempt with reformatted whitespace, a reworded rationale or a different model
name. The fingerprint excludes diff text on purpose, precisely so that this does
not work; trying it is the §2 failure mode one level down.

**Do not widen.** A refusal that names an oracle path — a test, a linter config, a
generator, a smoke catalog — is the engine refusing to let a proposal edit the
gate that will judge it. That refusal is the point of the design. A gate you can
satisfy by editing the gate is not one.

The block lifts honestly, and only three ways: the weakness's own evidence
changes, the gate set changes, or an operator forgets the fingerprint.

## After 201

**Do not apply the change yourself.** The `diff_text` you just recorded IS the
change: the engine applies that stored diff inside its own sandbox when the
proposal is judged, so the verdict is on the proposed tree — edits you make to
the working copy are invisible to the judges, and a diff that exists only as
working-copy edits is a proposal that was never recorded. One change per cycle —
two changes under one verdict teach nothing about either.

**Stop and hand the proposal uuid to the `judge` skill.** Do not fetch the
evaluator's token. Do not run a judge command to "check first". If you want to
know whether it holds, that is what judgment is for, and it must be triggered by
an identity that is not yours.
