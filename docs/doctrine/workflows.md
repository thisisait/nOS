# Doctrine: multi-agent workflows

**Detail, measurements and the checklist:** [docs/workflow-standard.md](../workflow-standard.md).
**Machine-checked by:** `tests/anatomy/test_workflow_declares_fanout_semantics.py`.

## 1. Every `parallel()` declares its kind. There are two.

| kind | meaning | why the cost is repaid |
|---|---|---|
| **union** | outputs are ADDED; none is discarded or reconciled | you keep everything you paid for |
| **veto** | N independent attempts to REFUTE one claim | disagreement is the product; a single refutation is decisive |

**`selection` — N alternatives, keep one — is banned** without a written
justification: quality scales as `max()`, cost as `sum()`, and you wait for the
slowest to produce what you discard.

**A chain is not a fan-out.** If step B needs step A's output — a route shape,
an exported name, a mount seam — it is sequential. Running a chain in parallel
parallelises the *guessing*, and reconciling costs more than the wall-clock saved.

**Disjointness is a property of OUTPUT, not of input.** Different directories is
the right default for *construction*. But a review panel whose lenses read the
same code and ask different questions produces finding sets that are added, not
chosen between — that is a legitimate union. If you cannot say what each agent
contributes that no other one does, you have a selection wearing union's clothes.

## 2. Why: measured, 2026-08-04

34 subagent runs. Duplicate tool calls were **7%** — agents do not mostly repeat
each other. But **~90% of spend is context, ~10% is product**, and a barrier
waits **2.3×** the median agent. The tax is per-agent orientation, so every
agent whose output you discard or must merge is paid for in full. **Ground
once:** the brief is written in one place and passed *in the prompt*.

## 3. The gate is the thing, not the model

An agent may merge without human review because **a gate reads evidence and
applies rules** — never because a model is trusted.

- **Code checks outrank LLM scores.** No verbosity bias, no variance. Use an LLM
  judge only for claims no code can express, and make it **refute**, not rate.
- **Panels only for high blast radius**, and drawn from *different families*.
  Three copies of one judge is one judge.
- **The judge is code; the proposer is a model; they never share an identity.**
  An agent that wrote code may not verify it, and a verifier receives the
  artefact, not the author's account of it.
- **Prefer the weakest gate that still fails.** A gate pinning one concrete
  output is a strong hypothesis — easy to overfit, and passing it generalises
  nothing. A *property* gate (idempotence, schema validity, "every catalog token
  has a renderer") is weak, and passing it implies far more. Matters most for
  `gate-add`, where a proposer picks the gate. (Bennett, AGI-23.)

## 4. Guardrails steer the run, they do not only grade it

Reject low grounding (require an `evidence` field via `schema`); quarantine
fabrications (a field absent from a real response never enters the artefact);
block schema failures at the tool-call layer so the model retries against the
contract. Grade the **trajectory**, not only the answer — a report that omits a
failed step is a fabrication even when every fact in it is true. Source the
hardest tests from real logs of clean and broken runs (`pulse_runs`, the loop
ledger, subagent transcripts, `ansible.log`).

## 5. Rigour scales with blast radius

worktree → branch → `dev` → estate → data → irreversible. Deterministic checks,
clean trajectories and history outrank confidence. **Do not automate the
irreversible.**

## 6. Two loops, and the gate between them

**Discovery** files work. **Implementation** changes the estate. They fail in
opposite ways — discovery by noise and silence, implementation by blast radius
— so they need different gates and must not share one.

**The transition requires something discovery cannot do**, so it is not a
status: a status is data, and any lane discovery can write it can promote
itself into. A roadmap row is a **proposal**; a **committed** workflow spec
naming it (`meta.implements: '<slug>'`) is the **authorisation**. Discovery
POSTs rows over HTTP and has no path into git — which is why
`.claude/workflows/` is versioned. Review workflows carry no `implements`; they
change nothing. Gate: `tests/anatomy/test_triage_gate_is_a_commit.py`.

## 7. Recursion

1. **Asymmetric judgement.** A change to a judge is evaluated by the *previous*
   version of that judge, or the shortest path to passing is rewriting the test.
2. **The ratchet is mandatory.** Every claimed improvement carries a gate shown
   to be RED before the fix. A system that may claim improvement unproven, will.
3. **Success markers are written by a reader, never by the attempting code.**
   Eight instances of the opposite were measured in *non*-recursive code in a
   single day; under recursion the drift compounds.

**Recursion argues for sequential:** parallelism buys wall-clock at the cost of
coherence, and each iteration must build on the last. Fan out only to veto.

**Workflow definitions are versioned** (`.claude/workflows/`, explicitly
un-ignored). A loop cannot propose a change to a file that is not in the
repository, and a judge cannot be retro-red against a version never committed.
