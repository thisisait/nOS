---
name: judge
description: Trigger a named gate set against the nOS loop engine and report the verdict it returns — pass, fail or indeterminate, with evidence. Use to evaluate a recorded proposal, or to get one deterministic reading of the repo's health. Never to decide an outcome yourself.
---

# judge — trigger, wait, quote

Read `../../ENGINE.md` first. It holds the base URL and the token; this file
holds neither.

**You are not the judge. The judge is code.** Your entire job is to address it,
wait for it, and repeat what it said. Every accept/reject in this loop comes from
a process that actually exited — an exit code, a count, a diff — and never from a
model's opinion of the work, least of all its own.

You hold `loop_judge_token`: `read` and `judge`, no `propose`.

## Trigger

```bash
curl -sS -X POST -H "Authorization: Bearer $(tok loop_judge_token)" \
     -H 'Content-Type: application/json' \
     -d '{"gate_set":"<set>","proposal_uuid":"<uuid-or-omit>"}' \
     "$BASE/api/v1/loop/judge"
```

The field is `proposal_uuid`, not `proposal`. It was `proposal` here until
2026-08-03, and the engine dropped the unknown key silently: the set ran as an
unattached BASELINE, a verdict sealed against no proposal, and that proposal —
left with zero verdicts — wedged as `attempt-pending` until an operator lifts
it (`POST /api/v1/loop/forget`, operator identity only — not yours).
Omit the key entirely for a deliberate baseline; never misspell it. The engine
now answers 422 instead of doing something else quietly.

`202` returns a `run_id`. The call is asynchronous because one gate set runs for
minutes; that is expected, not a hang.

An attached run judges the proposal's STORED diff: the engine applies it in a
sandbox at a base it chooses and the verdict names both the base and the judged
tree. There is no way to send a different diff here — what gets judged is what
was proposed. If the diff no longer applies, the verdict is `indeterminate`
with that reason; the engine never falls back to judging the unpatched repo.

## Wait

```bash
curl -sS -H "Authorization: Bearer $(tok loop_judge_token)" \
     "$BASE/api/v1/loop/judge/<run_id>"
```

Poll until the status is no longer `running`. **`running` is not a result.** Do
not report an outcome, hedge one, or predict one while a run is in flight. If you
run out of patience, say the run is still in flight and give the id — that is a
true statement; anything else is the loop reporting its own success.

## Report

Quote `result` verbatim. It is one of three values:

- **`pass`** — every judge in the set passed.
- **`fail`** — at least one judge failed.
- **`indeterminate`** — at least one judge did no work, could not run, or was
  killed. **It is not a soft fail and it is not a near-pass.**

Never collapse three values into two. `indeterminate` is recorded distinctly so a
broken *judge* is never mistaken for a broken *proposal*; flatten it into `fail`
and the loop starts "fixing" code in response to a down organ, which is worse
than doing nothing because it looks like progress.

Report the per-judge evidence with it — each judge's name, exit code, work count
and the run id. A verdict without its evidence is a claim.

## What this skill never does

- **Never runs a judge directly.** Not `pytest`, not the linter, not the smoke
  runner, not the generator, not the corpus differ. Running one by hand bypasses
  the worktree sandbox, the work-count ratchet, the pinned side-effect flags and
  the ledger — and yields a number that nobody, on any other runtime, can
  reproduce. If the engine's route is not mounted, say so and stop.
- **Never writes a verdict.** There is no endpoint that accepts one. If you find
  yourself composing a result field, you are building the thing this design
  deleted on purpose.
- **Never edits anything to make a run greener.** If a judge fails on the gate
  itself, that is a finding for the operator, not a target.
- **Never accepts, applies, commits or merges.** A green verdict is information.
  Application is an operator act.

## Checking a verdict

Do not re-judge to double-check — replay. The engine stored the exact argv, the
judged tree's id and the base it was built from, the exit code, the work count
and a stdout hash for exactly this. A
verdict that cannot be replayed is a claim, and this estate spent a release
learning what claims are worth.
