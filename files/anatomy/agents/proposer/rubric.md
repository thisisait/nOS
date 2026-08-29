# Rubric — proposer

The gate set decides whether the estate still stands. This rubric decides
whether the RUN was a proposal rather than an exploration.

## Satisfied

- Exactly one proposal was recorded, or one was refused by the engine and the
  refusal is quoted verbatim.
- The budget was read BEFORE the diff was authored, and the intent class came
  from the budget or from a refusal — not from memory.
- The diff touches only paths the budget allows, and is the smallest that
  closes the named weakness.
- The report names the proposal uuid, or the refusal.

## Not satisfied

- No proposal recorded and no refusal quoted — the run explored and stopped.
- More than one proposal from one weakness.
- Any attempt to judge, commit, push, or open a merge request.
- A diff against files that were never read.
- A refusal restated as a summary rather than quoted. The engine's words are
  the evidence; a paraphrase is the agent's opinion of the evidence.
