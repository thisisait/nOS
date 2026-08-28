# Questionnaire — answer before the implementation workflow runs

Answer inline (mark the chosen option, add a line where asked). The workflow
(`04-implementation-workflow.js`) reads this file via `args` and refuses to run unanswered.
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

**Q2. What is the word for the two-plane split itself?**
Why: "tier" is doctrine-reserved for RBAC and nothing else (CLAUDE.md, `docs/doctrine/
layers.md`) — the operator's phrase "two tiers" cannot enter code.
- (a) **plane** (sere plane / ops plane) — settled infra semantics, no repo collision.
- (b) other: ______
Recommendation: (a).

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

**Q5. What is an embryo, concretely — and what must a destination site have?**
Why: "a configuration shipping pre-trained models AND agents arrives pre-armed at a site with
no operator who can converge" is rule 7 at shipping scale (Judge B §4f).
- (a) Embryo = repo: agents + bindings + sample sets + routing; arrives with
  `NOS_ARMED_BACKENDS` empty; destination must have a converge-capable operator (human or a
  contracted remote one). Consequence: slower onboarding, honest custody.
- (b) Embryo arrives armed for a defined agent subset. Consequence: name the subset and who
  reads its ledger: ______
Recommendation: (a), until the ops plane has a `proven` agent.

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

**Q9. Accept that prose-output agents can never be "satisfied"?**
Why: arch item 3 makes satisfaction oracle-written. Surveyor's deliverable is prose; no gate
set proves prose. Judge A: "an agent whose output no reader can check has no business writing
a success marker" — it reports `run_end`, stays `unproven`, until its deliverable becomes an
artifact (a diff, a JSON survey, a `path_written`).
- (a) Yes — and surveyor/librarian deliverables get restructured into checkable artifacts.
- (b) Yes, but grader-satisfied stays as a distinct, lower state (`grader_satisfied` ≠
  `satisfied`). Consequence: two success markers; the weaker one will be quoted.
Recommendation: (a).

**Q10. Grader identity rule.**
Why: no agent declares `model.grader`; the fallback is the proposer's own client — the
configuration arXiv:2510.16657 formally shows degrading.
- (a) `model.grader` required whenever `outcomes:` exists, must differ from `model.backend`;
  grader is feedback-only (arch item 3).
- (b) Drop the grader entirely; oracle pass/fail + raw gate output as feedback. Consequence:
  cheaper, cruder revision signal.
Recommendation: (a) for agents whose revision needs prose feedback; (b) is acceptable and
cheaper — if in doubt, start (b) per-agent and add graders on evidence.

**Q11. Tenancy substrate for the ops plane.**
Why: one `wing.db`, no tenant column anywhere; a client's sessions/questions/audit in the
operator's table breaks the Art-30 story (Judge B §4d). No report covered multi-tenancy — this
is designed from estate facts alone (Judge A "could not judge").
- (a) One SQLite file per tenant (`NOS_TENANT` selects; Wing picks DB per request from the
  forward-auth header). Isolation/backup/erasure free; cross-tenant queries impossible.
- (b) Tenant column. Every future query is a place to forget a WHERE.
- (c) Defer until Q3's harness reports.
Recommendation: (a) as the design assumption; build only with the ops plane.

**Q12. The mutex.**
- (a) sere keeps global N=1 (`~/.nos/agent-run.lock`) — its agents contend on one checkout;
  per-(tenant,agent) locks are an ops-plane deliverable.
- (b) Widen now to a slot directory of N: N = ______
Recommendation: (a). Widening a serializer before the runs it serializes ever succeed buys
concurrent failures.

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

**Q14. Which Wing write routes does each agent get, day one?**
Why: after the mcp-wing split, write grants are explicit and per-route.
- (a) Zero for all six holders; add per-route on refusal evidence (a refused POST lands in the
  audit event with `refused_reason` — grant follows demonstrated need).
- (b) Grandfather current usage: enumerate from `events` which POST routes each agent actually
  called in the last 90 days and grant exactly those: run the query and attach.
Recommendation: (b) — it is (a) plus honesty about what already happens; the query is one
SELECT over `agent_tool_use` events.

**Q15. The `/questions` surface: answer channels and expiry policy.**
- Channels day one: (a) Wing UI only (b) Wing + ntfy actions (c) Wing + ntfy + telegram.
- `default_on_expiry` policy: (a) always `refuse` (b) per-question, agent-declared, capped at
  severity ≤ medium.
Recommendation: Wing UI only; always `refuse`. An expired question answered "yes" by silence
is absence read as success.

**Q16. When does the rename land?**
- (a) Now — docs/memory edit, ~1 hour, zero code refs to migrate (grep-verified).
- (b) With the first ops-plane commit.
Recommendation: (a). Naming debt compounds the moment the first flag is spelled.
