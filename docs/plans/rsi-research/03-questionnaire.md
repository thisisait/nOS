# Questionnaire — answer before the implementation workflow runs

Answer inline (mark the chosen option, add a line where asked). The workflow
(`04-implementation-workflow.js`) reads this file via `args` and refuses to run unanswered.

**Status 2026-08-28: ALL SIXTEEN ANSWERED** by the operator (see the
`> **ANSWER**` blocks). Three answers depart from the recommendation — Q8, Q5
and Q12 — and each says why in its own block.
Every question is a decision the evidence does not make for you, or a disagreement between the
two judges. Recommendations are given with reasons; they are not defaults — an unanswered
question blocks, it does not resolve.

---

**Q1. What is the client plane called?**
Why: "nos-bi" names a domain (warehouse/accounting/CRM); "nos-sere" names a relation to the
estate. Different axes — and a client-side agent that also improves its estate would be
nameless under "nos-bi" (Judge A §4). Grep-verified: neither name exists in code yet; the
rename is free today and a `devboxnos-*`-scale migration later.
- (a) `nos-ops` — one axis with sere (what the gate corpus proves about). Consequence: embryo
  shipping both planes is expressible.
- (b) `nos-bi` — keeps your working name. Consequence: the axis mismatch is permanent once it
  becomes a flag/client-prefix/directory.
- (c) other: ______
Recommendation: (a). Both judges accept the axis argument; nothing argues for (b) except
familiarity.

> **ANSWER (operator, 2026-08-28): (a) `nos-ops`.** Agreed — one axis with sere.

**Q2. What is the word for the two-plane split itself?**
Why: "tier" is doctrine-reserved for RBAC and nothing else (CLAUDE.md, `docs/doctrine/
layers.md`) — the operator's phrase "two tiers" cannot enter code.
- (a) **plane** (sere plane / ops plane) — settled infra semantics, no repo collision.
- (b) other: ______
Recommendation: (a).

> **ANSWER (operator): (a) `plane`.** sere plane / ops plane.

**Q3. Does the ops plane proceed now, and on what condition?**
Why: fourteen reports produced **zero** measurements of a sub-3B model doing tool use; the
nearest (3B, Thought-ICS arXiv:2602.02416) holds only with an oracle and degrades autonomous.
Nine reports' nos-bi sections say "none survive" (Judge B §4a). Building on silence is the
failure mode the estate names.
- (a) Measure first: build the harness (one task family, one labelled sample set, N local
  models from the binding registry, oracle-scored) and gate the plane on its output.
  Consequence: ops plane slips one step; the step produces the first real number.
- (b) Proceed on the design bet. Consequence: scaffold may be built for a model class that
  cannot serve it.
- (c) Park the plane; sere only this cycle.
Recommendation: (a). It is also the cheapest: the harness reuses the binding registry and the
one_shot branch, both needed anyway.

> **ANSWER (operator, 2026-08-28): (a) measure first — and treat the gap as a
> thing to CLOSE, not to wait out.** Build the harness (one task family, one
> labelled sample set, N local models from the binding registry, oracle-scored)
> and let its output gate the plane. See the Q4 answer for the model class the
> harness must actually cover: the measurement is not "is 1B enough", it is
> "where is the boundary between the chain-emitting tier and the tool-use tier".

**Q4. What may the ~1B local model do?**
Why: the boundary decides the whole ops-plane tool surface.
- (a) Emit nos-lang chains only — zero tools; the chain is the tool call; code validates and
  executes it (memory `nos-cortex-lang-vision`). Consequence: model never self-assesses (the
  one principle the corpus supports at small scale, SWE-Gym Batch 7); expressiveness capped by
  the chain language.
- (b) Chains + a read-only retrieval tool. Consequence: multi-turn, which the corpus shows
  degrading at small scale.
- (c) The full six-tool roster. Consequence: unsupported by any measurement.
Recommendation: (a).

> **ANSWER (operator, 2026-08-28): (a) for now — chains only, zero tools — but
> this is an interim position, not the destination.** The target is TWO local
> tiers, and the harness in Q3 must measure both:
>   * **~1B — the chain tier.** Emits nos-lang chains; code validates and
>     executes. This is the `nos-lang:1B` input side.
>   * **~3–7B — the tool-use tier.** A model fine-tuned FOR tool use, on
>     `nos-lang:1B` output as its input. This is where real tool calling lives.
> Consequence for the workflow: the measurement harness is parameterised over a
> model-size range, not pinned at 1B, and the ops plane's tool surface stays
> closed until the 3–7B tier has a number. Nothing in the corpus measures either
> tier, which is exactly why Q3 is (a).

**Q5. What is an embryo, concretely — and what must a destination site have?**
Why: "a configuration shipping pre-trained models AND agents arrives pre-armed at a site with
no operator who can converge" is rule 7 at shipping scale (Judge B §4f).
- (a) Embryo = repo: agents + bindings + sample sets + routing; arrives with
  `NOS_ARMED_BACKENDS` empty; destination must have a converge-capable operator (human or a
  contracted remote one). Consequence: slower onboarding, honest custody.
- (b) Embryo arrives armed for a defined agent subset. Consequence: name the subset and who
  reads its ledger: ______
Recommendation: (a), until the ops plane has a `proven` agent.

> **ANSWER (operator): (c) DEFER — no embryos until the ops plane has a
> `proven` agent.** This is stricter than the recommendation, and it is the
> strictest reading of Q3: we do not ship pre-built configurations to clients
> while the plane they encode has no measurement behind it. When embryos do
> come, (a) is the shape — a repo, arriving with `NOS_ARMED_BACKENDS` empty and
> a converge-capable operator at the destination. Nothing in this cycle's
> workflow builds embryo machinery.

**Q6. May the loop ever propose harness edits (agent.yml / system.md / tool rosters)?**
Why: the judges' sharpest disagreement. A (item 6): yes, guarded by a judge that refuses diffs
touching the proposer's own directory or widening any grant. B (do-not-adopt #2): no — the
gates on an agent ARE those files; a proposer editing the file the scope check reads satisfies
the gate by editing the gate (rule 4), and an unconverged edit changes the next run's roster
(rule 7).
- (a) Never. Harness edits are operator work.
- (b) A's guarded variant: `harness` proposal kind, judge refuses self-touch and grant-
  widening, merges still behind the three-YES reader.
- (c) Later — revisit after N oracle-satisfied sessions: N = ______
Recommendation: (c) with N=10. B's mechanism argument is correct today; A's guard design is
sound enough to revisit once the loop has a success record to protect.

> **ANSWER (operator, 2026-08-28): (c), and the revisit condition is a SURFACE,
> not a count.** Harness enhancement becomes an explicit operator-facing TOGGLE,
> default OFF, surfaced in a **loop editor** where the harnesses are visible
> before the switch is thrown. The estate does not get to enable this for itself:
> the toggle is operator state, and the loop may not propose a change to it
> (it belongs on the Q7 denylist for that reason).
> Build order: the loop editor surface FIRST (you cannot consent to what you
> cannot see), the toggle with it, the guarded `harness` proposal kind only
> after. Judge B's mechanism objection stands until the toggle exists — with it
> OFF, today's behaviour is unchanged, which is what makes shipping it safe.

**Q7. What may nos-sere never touch (the denylist)?**
Why: prose denylists rot; this one becomes a judge (`engine:judge-runner` refuses the diff),
which requires an explicit list.
Proposed floor: `state/judge-sets.yml` and `tests/**` gates (rule 4), `files/anatomy/agents/`
(pending Q6), credentials/secrets paths, `tools/loop-*.py` + `files/anatomy/bone/{ledger,
looproutes,loopauth}.py` (the loop may not edit the loop), `.github/workflows/**`.
- (a) Accept the floor as listed.
- (b) Amend: ______
Recommendation: (a). Note: `default.config.yml` stays PROPOSABLE — it is already in
MigrationWriteTool's allowlist and version bumps are the loop's core value.

> **ANSWER (operator): (a) accept the floor as listed** — `state/judge-sets.yml`,
> `tests/**` gates, `files/anatomy/agents/`, credential paths, `tools/loop-*.py`
> + `files/anatomy/bone/{ledger,looproutes,loopauth}.py`, `.github/workflows/**`.
> `default.config.yml` stays PROPOSABLE.
> **Plus one addition, written rather than assumed:** the Q6 harness-enhancement
> toggle itself is on the denylist. The loop may not propose enabling its own
> harness editing. A permission a system can grant itself is not a permission.

**Q8. The memory model, after the Dreamer deletion.**
Why: three reports independently converged on wiring Dreams (ACE/MLEvolve/EvolveR) and Judge B
called that convergence "the most dangerous artefact in this corpus" — the Curator writing
permanent context from one run's feedback is rule 2. Judge A would keep the table under a
verdict-only `CHECK`; Judge B deletes the writer and waits.
- (a) No memory until the first oracle-satisfied session exists; then decide.
- (b) Build now: `agent_memory_stores.written_by CHECK ('engine:judge-runner')`, append-only
  structured deltas written by the verdict reader, `loadMemoryContext()` finally called.
  Consequence: ~120 LOC on a loop with zero completions.
- (c) No agent memory ever; KEAP is the estate's memory.
Recommendation: (a). The design in (b) is doctrine-clean and can wait for a loop that works.

> **ANSWER (operator): (c) NO agent memory, ever — KEAP is the estate's memory.**
> Stronger than the recommendation, which only deferred the decision. The reason
> is that a second memory beside the cortex is a second truth: KEAP already is
> the curated knowledge layer, with a review queue, a moderator and an
> `/agent/v1` API an agent can query. An agent that also keeps private
> cross-session state would accumulate conclusions nobody curated and nobody can
> contradict.
> Consequences the workflow must honour, so this does not rot into prose:
>   * DELETE `Memory/Dreamer.php`, `Memory/MemoryStore.php`, `bin/dream-agent.php`
>     and the `agent_memory_stores` table — not park them. Dead machinery that
>     looks live is how the estate gets a third memory by accident.
>   * DELETE the gate that pins Dreams (`test_agentkit_dreams.py`) in the same
>     commit, and add one that REFUSES the table's return: a gate that fails if
>     `agent_memory_stores` reappears or if `loadMemoryContext` is reintroduced.
>   * Anything an agent learns that is worth keeping goes to KEAP through the
>     existing capture/promotion path, where a human moderates it.

**Q9. Accept that prose-output agents can never be "satisfied"?**
Why: arch item 3 makes satisfaction oracle-written. Surveyor's deliverable is prose; no gate
set proves prose. Judge A: "an agent whose output no reader can check has no business writing
a success marker" — it reports `run_end`, stays `unproven`, until its deliverable becomes an
artifact (a diff, a JSON survey, a `path_written`).
- (a) Yes — and surveyor/librarian deliverables get restructured into checkable artifacts.
- (b) Yes, but grader-satisfied stays as a distinct, lower state (`grader_satisfied` ≠
  `satisfied`). Consequence: two success markers; the weaker one will be quoted.
Recommendation: (a).

> **ANSWER (operator, 2026-08-28): (a), with the output contract made explicit.**
> Agents produce their deliverable THROUGH TOOLS — db rows, structured files —
> and their "answers" are structured, not prose. Prose is a report for a human,
> never the artifact a verdict is read from.
> Plus a reformat fallback, because a structured contract that fails closed on a
> missing bracket throws away work that was otherwise correct:
>   1. **A hardcoded parser first.** Deterministic repair of the common
>      malformations (unbalanced bracket, trailing comma, fenced block, prose
>      preamble). No model in this step — it must be cheap and predictable.
>   2. **Only if that fails, a bounded reformat loop** — one re-ask, format-only,
>      the original content quoted back, no new reasoning.
>   3. **If both fail, the run is UNPARSEABLE, not satisfied.** The fallback
>      repairs SHAPE, never content, and a repaired output is marked as repaired
>      in the session row — a reader must be able to see that the parser touched
>      it. Silent repair would be the success marker written by the thing that
>      failed.


**Q10. Grader identity rule.**
Why: no agent declares `model.grader`; the fallback is the proposer's own client — the
configuration arXiv:2510.16657 formally shows degrading.
- (a) `model.grader` required whenever `outcomes:` exists, must differ from `model.backend`;
  grader is feedback-only (arch item 3).
- (b) Drop the grader entirely; oracle pass/fail + raw gate output as feedback. Consequence:
  cheaper, cruder revision signal.
Recommendation: (a) for agents whose revision needs prose feedback; (b) is acceptable and
cheaper — if in doubt, start (b) per-agent and add graders on evidence.

> **ANSWER (operator): (b) per-agent, start WITHOUT a grader** — oracle pass/fail
> plus the raw gate output as the revision signal. A grader is added only on
> evidence: a run where the raw gate output demonstrably was not enough to
> revise from. Grant follows demonstrated need, the same rule as Q14.
> When a grader IS added, (a) still binds: `model.grader` must differ from
> `model.backend`, and the grader gives feedback only — the verdict is the
> oracle's (arXiv:2510.16657 is why the same-model fallback is not an option).

**Q11. Tenancy substrate for the ops plane.**
Why: one `wing.db`, no tenant column anywhere; a client's sessions/questions/audit in the
operator's table breaks the Art-30 story (Judge B §4d). No report covered multi-tenancy — this
is designed from estate facts alone (Judge A "could not judge").
- (a) One SQLite file per tenant (`NOS_TENANT` selects; Wing picks DB per request from the
  forward-auth header). Isolation/backup/erasure free; cross-tenant queries impossible.
- (b) Tenant column. Every future query is a place to forget a WHERE.
- (c) Defer until Q3's harness reports.
Recommendation: (a) as the design assumption; build only with the ops plane.

> **ANSWER (operator): (a) one SQLite file per tenant.** `NOS_TENANT` selects;
> Wing picks the DB per request from the forward-auth header. Design assumption
> now, built only with the ops plane — nothing in this cycle creates tenant DBs.

**Q12. The mutex.**
- (a) sere keeps global N=1 (`~/.nos/agent-run.lock`) — its agents contend on one checkout;
  per-(tenant,agent) locks are an ops-plane deliverable.
- (b) Widen now to a slot directory of N: N = ______
Recommendation: (a). Widening a serializer before the runs it serializes ever succeed buys
concurrent failures.

> **ANSWER (operator): widen now — N=3 for AgentKit runs, and the claude-CLI
> path stays EXCLUSIVE.** Departs from the recommendation, with the reason the
> lock exists preserved: concurrent claude-CLI spawns crashed every participant
> (2026-05-27), so a CLI spawn (`pulse-run-agent.sh`, `scan-runner.sh`) takes
> ALL THREE slots and therefore still meets nobody. Bound AgentKit runs are
> PHP in-process — a different failure mode — and may run three abreast.
> Implementation note for the workflow: this is a change to
> `files/anatomy/scripts/agent-run-lock.sh` (slot directory, not a single
> mkdir), it must keep the stale-owner reclaim per slot, and it ships with a
> gate that proves a CLI acquisition excludes a concurrent AgentKit one. Do NOT
> widen it by giving the two paths separate locks — two locks for one invariant
> is the estate's signature defect, and this file was written to end it.

**Q13. Accept the proposer's cost increase from joining the ledgers?**
Why: arch item 5 moves the proposer from one bypass-mode CLI call to an AgentKit session with
tools: 5–30 calls/run, bounded by the ceilings it thereby gains. What it buys: session row,
scope gate, ceiling, `MigrationWriteTool` allowlist, provenance from weakness to MR.
- (a) Yes, at existing ceilings.
- (b) Yes, with a tighter per-proposer ceiling: tokens = ______
- (c) No — keep the CLI path, accept two provenance systems. Consequence: "AgentKit-driven
  nos-loop" stays aspirational; every corpus mechanism attaches downstream of an unaudited
  proposer (PostTrainBench's cheat taxonomy documented exactly these conditions, Batch 12).
Recommendation: (a).

> **ANSWER (operator): (a) yes, at existing ceilings.**

**Q14. Which Wing write routes does each agent get, day one?**
Why: after the mcp-wing split, write grants are explicit and per-route.
- (a) Zero for all six holders; add per-route on refusal evidence (a refused POST lands in the
  audit event with `refused_reason` — grant follows demonstrated need).
- (b) Grandfather current usage: enumerate from `events` which POST routes each agent actually
  called in the last 90 days and grant exactly those: run the query and attach.
Recommendation: (b) — it is (a) plus honesty about what already happens; the query is one
SELECT over `agent_tool_use` events.

> **ANSWER (operator): (b) grandfather from measured use.** Run the SELECT over
> `agent_tool_use` events for the last 90 days, grant each agent exactly the
> POST routes it actually called, and ATTACH THE QUERY OUTPUT to the commit —
> the grant must be traceable to the measurement that justified it. A route
> nobody called is not granted, and that absence is a finding worth reporting,
> not a gap to fill.

**Q15. The `/questions` surface: answer channels and expiry policy.**
- Channels day one: (a) Wing UI only (b) Wing + ntfy actions (c) Wing + ntfy + telegram.
- `default_on_expiry` policy: (a) always `refuse` (b) per-question, agent-declared, capped at
  severity ≤ medium.
Recommendation: Wing UI only; always `refuse`. An expired question answered "yes" by silence
is absence read as success.

> **ANSWER (operator): Wing UI only; `default_on_expiry` is always `refuse`.**
> No ntfy actions, no Telegram — an approval channel is an authentication
> surface, and the notification channels are not authenticated the way Wing is.

**Q16. When does the rename land?**
- (a) Now — docs/memory edit, ~1 hour, zero code refs to migrate (grep-verified).
- (b) With the first ops-plane commit.
Recommendation: (a). Naming debt compounds the moment the first flag is spelled.
> **ANSWER (operator): (a) now.** The rename is a docs-and-memory edit today
> (grep-verified: zero code references) and a migration once the first flag is
> spelled. `nos-bi` is retired as a name; `nos-ops` is the client plane.

---

## Answer summary — what the workflow reads

| Q | Answer |
|---|---|
| Q1 | client plane is **`nos-ops`** |
| Q2 | the split is a **plane** (sere plane / ops plane) |
| Q3 | **measure first** — harness gates the plane |
| Q4 | ~1B = chain tier (nos-lang, no tools); **3–7B tool-use tier** fine-tuned on nos-lang:1B output; harness measures both |
| Q5 | **defer embryos** until an ops-plane agent is `proven` |
| Q6 | harness edits behind an operator **toggle**, default off, in a **loop editor**; surface first |
| Q7 | denylist floor accepted **+ the Q6 toggle itself** |
| Q8 | **no agent memory ever** — KEAP is the memory; delete Dreamer + MemoryStore + the table |
| Q9 | tool-produced structured artifacts; **hardcoded parser** then one bounded reformat; else UNPARSEABLE |
| Q10 | **no grader** to start, per-agent, added on evidence; if added, must differ from the backend |
| Q11 | **one SQLite per tenant**, built with the ops plane |
| Q12 | **N=3 for AgentKit, CLI exclusive**, one lock |
| Q13 | proposer onto AgentKit, **existing ceilings** |
| Q14 | **grandfather** write routes from 90 days of `agent_tool_use`, attach the query |
| Q15 | **Wing UI only**, expiry = `refuse` |
| Q16 | rename **now** |
