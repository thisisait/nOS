# Does the surveyor fail because of the MODEL or because of the CEREMONY?

Declared 2026-08-29 BEFORE the runs, so the answer cannot be chosen afterwards.

## What is already measured (baseline, MiniMax-M2)

Same backend, same effective model for both agents — verified in
`agent_session_start.result_json.model_effective`.

| ceremony | shape | runs | filed a report WITH a body |
|---|---|---|---:|
| librarian (brief/describe/judge) | numbered procedure, concrete inputs | 5 | 4 |
| surveyor (surface-survey) | open judgement, report at the end | 9 | 1 |

(9 surveyor runs, 2 produced a `conductor_report` row, only 1 with a non-empty
body — the other was the `result`/`result_json` drop, since fixed.)

## The two hypotheses, which I had been mixing

H1 CEREMONY SHAPE — an open judgement task does not converge on a write step;
   a procedure does. Predicts: raising the model does NOT fix the surveyor.
H2 MODEL STRENGTH — the surveyor's task is simply harder, and M2 is the weakest
   model in its family. Predicts: raising the model DOES fix it.

## The test

One variable: `minimax_model` M2 -> M2.7. Everything else untouched.
Three surveyor runs; one librarian run as a control that the change broke nothing.

## Decided in advance

* H2 supported if surveyor files with a body in >= 2 of 3.
* H1 supported if it files in 0 or 1 of 3 — and then the ceremony gets rewritten
  as a procedure, not another prompt edit.
* A run that errors on the binding (bad model id) is VOID, not evidence.

## RESULT, 2026-08-29

| model | surveyor runs | filed a report WITH a body |
|---|---:|---:|
| MiniMax-M2 | 9 | 1 |
| MiniMax-M2.7 | 3 | **3** — 14 781, 12 986, 10 411 bytes |

**H2 supported** against the threshold declared above (>= 2 of 3). One variable
changed: `minimax_model`. Nothing else was touched between the M2 runs and these.

### The control failed, and that is the more useful half

`librarian:brief-taxonomy` on M2.7 came back `outcome_needs_revision` with an
empty body — on a ceremony that filed on 4 of 5 M2 runs. It was NOT a
regression from the model: it did the work (four brief proposals POSTed to
KEAP), then filed its report twice and was answered **201** twice, and both rows
stored nothing. It had put the markdown under `body`; two further attempts
wrapped the payload in `event`.

With `result` and `result_json` already accepted that is FOUR spellings for one
field, from two models. The fix is not a fifth alias — each one teaches the next
model that a new spelling is fine — but a door that REFUSES a report it cannot
store, and names the field it will. Shipped with the tasks that name it.

### What this does NOT license

M2.7 clearing the surveyor does not make the ceremony's shape sound. An open
judgement task with a write at the end still converges less reliably than a
numbered procedure; a stronger model covers that, it does not remove it. The
next cheaper model, or a harder survey, brings it back. `face-loop-view` and any
ops-plane work that assumes small local models should read this as a warning,
not as a settled question.

### Cost, unmeasured

Nothing here compared price. M2.7 output tokens per surveyor run were 6 852 /
8 212 / 9 292 against M2's 3 253–10 703 — the same order, but tokens are not
money and the estate records no per-model rate. `wing:agent-cost-tally` reads
`cost_basis`, which is `foreign:<host>` for MiniMax, i.e. unpriced. Anyone
choosing a tier on cost needs that number first.
