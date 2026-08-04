# Workflow standard

> **Companion to** [docs/doctrine/workflows.md](doctrine/workflows.md), which holds
> the canonical decisions in under 80 lines. This file carries the measurements,
> the rationale and the checklist.
> **Machine-checked by:** `tests/anatomy/test_workflow_declares_fanout_semantics.py`
> **Related:** [doctrine/four-trees.md](doctrine/four-trees.md) · [doctrine/gates.md](doctrine/gates.md)

This governs multi-agent workflows in nOS: when to fan out, how to judge, and
what a workflow must declare before it may run. It exists because the operator's
own observation — *"multi-agent WF are currently bullshit; re-re-inventing the
wheel increases cost insanely with each agent, that lands later than the only
important one, which landed first"* — turned out to be right about the symptom
and worth correcting about the cause.

---

## 1. The rule

**Every `parallel()` declares its semantics. There are exactly two legal kinds.**

| kind | meaning | why the cost is repaid |
|---|---|---|
| **union** | each agent searches a *disjoint* space; outputs are added together | you keep everything you paid for |
| **veto** | N independent attempts to *refute one specific claim*; disagreement is the product | cheap, bounded, and diversity is the whole point |

**`selection` — N alternatives, keep one — is banned** without an explicit,
written justification in the workflow's own source. Quality there scales as
`max()` while cost scales as `sum()`, and you additionally wait for the slowest
to produce something you throw away.

A chain is not a fan-out. If step B needs step A's output — a route shape, an
exported name, a mount seam — it is sequential, and running it in parallel is
just a guess followed by a rewrite.

**Disjointness test, as the operator states it:** parallel is licensed only when
the task is *completely unambiguous*, in a *different directory*, with *no
dependency on or reference to another agent's work*.

**Refinement, forced within the hour by the first case it was applied to.** The
directory rule is a cheap and usually correct *proxy*. What actually matters is
**disjointness of OUTPUT, not of input.** A review panel whose lenses all read
the same code but ask different questions — *will this work? what would you
stop? what is the strongest objection?* — produces finding sets that are added
together, not chosen between. That is a union, and it is legitimate, even though
every agent read the same files.

So the test in full:

- **Union** requires that *no agent's output is discarded or reconciled*. If you
  will keep all of it, the input may overlap.
- The directory rule remains the right default for *construction*, where shared
  input almost always means shared output and therefore a merge.
- If you cannot say what each agent contributes that no other one does, you do
  not have a union — you have a selection wearing its clothes.

---

## 2. The measurement behind it

34 subagent runs on 2026-08-04, read from the session's own transcripts:

```
tool calls                   1 366
duplicate calls                 76   (7%)   <- NOT the problem
output tokens              710 455          10% of billable equivalent
cache creation           9 390 136          33%   <- the orientation tax
cache read             197 827 381          57%
duration  median 436s   max 996s   -> a barrier waits 2.3x the median
```

**Roughly 90% of the spend is context; 10% is product.** The waste is *not*
agents repeating each other's commands — that is 7%. It is that **each agent
pays a full orientation tax to produce a small amount of output**, and in a
selection fan-out you pay N taxes and keep one answer.

The duplicates that did occur name the second-order problem exactly: 15 agents
each issued an identical `ToolSearch: select:WebFetch,WebSearch`, and 5 agents
independently recomputed the same `git diff --name-only v0.9-beta..HEAD`. Pure
orientation, zero product.

**Corollary — the brief.** 16 agents read a shared `brief.md`. That pattern is
correct and should be deliberate: ground *once*, pass the brief *in the prompt*,
and let no agent rediscover what another already established.

---

## 3. The gate is the thing, not the model

> An agent finishes a change and merges without human review because **a gate
> reads evidence and applies rules** — not because the model is trusted.

This is the whole justification for the machinery. Everything below serves it.

**Code checks outrank LLM scores.** A deterministic check has no verbosity bias,
no sycophancy, and no variance. Reach for an LLM judge only for claims no code
can express, and even then make it *refute* rather than *rate* — "try to break
this" is a far better prompt than "score this 1-10", because a score is a
comfortable place for a model to hide.

**Panels only for high blast radius** (§6), and when you use one, draw the judges
from *different families* — different prompts, different lenses, ideally
different models. Three copies of the same judge is one judge with extra steps.

**The judge is code; the proposer is a model; they never share an identity.**
The verdict IS the reward signal, so any path by which a proposer can influence
its own verdict is the failure mode. In a workflow this means: an agent that
wrote code may not be the agent that verifies it, and a verify agent must
receive the artefact, not the author's account of the artefact.

---

## 4. Guardrails inside the run, not only after it

Evals belong *inside* the workflow, steering it, not only at the end grading it.
Three that every nOS workflow should carry:

- **Reject low grounding.** An agent that reports a finding without a file, a
  line, or a command output has not made a finding. The `schema` option on
  `agent()` is the cheapest enforcement available — require an `evidence` field
  and the model must produce one to return at all.
- **Quarantine fabrications.** For any workflow that builds against an API: a
  field that cannot be pointed to in a real response does not enter the
  artefact. Collect observed fields in the grounding phase, pass them forward,
  and make a verify agent hunt for one that was invented.
- **Block schema failures.** Validation happens at the tool-call layer, so the
  model retries against the contract instead of a downstream stage guessing.

These are guardrails in the strict sense: they change what the run *does*, not
merely what it *reports*.

---

## 5. Grade the trajectory, not just the answer

A correct answer reached by a broken path will not survive contact with the next
task. Grade both:

- **Soundness** — does each step follow from what was actually observed?
- **Faithfulness** — does the final report describe the run that happened?
  A summary that omits a failed step is a fabrication even when every fact in it
  is true.

**Source the strongest tests from real logs of clean and broken runs.** nOS has
these and they are underused:

| log | what it holds |
|---|---|
| `pulse_runs` in `wing.db` | `exit_code`, `stdout_tail`, `stderr_tail` per scheduled run |
| the loop ledger (`loop_verdicts`) | hash-chained verdicts with the reason a judge skipped |
| `~/.claude/projects/*/subagents/*.jsonl` | every tool call an agent made, with usage |
| `~/.nos/ansible.log` | every converge, task by task |

A test derived from a run that actually broke is worth more than a test derived
from imagining how it might.

---

## 6. Gate on blast radius

Rigour should be proportional to **what a mistake costs to undo**, not to how
confident anything sounds. The ladder in this estate:

| radius | example | required before merge |
|---|---|---|
| **worktree** | a scratch experiment | nothing; delete it |
| **branch** | code on `fix/*` | pytest green |
| **`dev`** | pushed | pytest + a **retro-red** gate + lint |
| **estate** | a converge touches ~50 containers | the above + `--tags verify` |
| **data** | a removal, a rotation, a migration | the above + dry-run first + operator confirm |
| **irreversible** | key rotation without the old key, force-push, deleting a backup | do not automate |

Prioritise **deterministic checks, clean trajectories, and history** over
confidence. A model saying "I'm confident" is not evidence; a gate that was red
an hour ago and is green now is.

---

## 7. nOS-specific obligations

**The four trees.** A workflow declares which of branch / checkout / worktree /
estate it writes to. Nothing propagates on its own. Agents that mutate files in
parallel need `isolation: 'worktree'` — and if you needed that, ask first
whether the fan-out was a chain in disguise.

**The ratchet: every claimed improvement carries a retro-red gate.** A gate that
passes on the fixed tree proves nothing until it has been shown to *fail on the
tree before the fix*. Run it in a scratch worktree at the prior commit. If it
only fails because a file is missing, that is a weak red — mutate the fixed
artefact instead and confirm the specific assertion fires.

**Success markers are written by a reader, never by the attempting code.** This
estate has eight measured instances of the opposite: a `dispatched_at` stamped
by the sender even on failure; a `status=scanned` written by a scan that never
ran; a backup reporting success over empty archives; a container reporting
healthy for ten days while serving its own installer. In a workflow this means a
build agent may not declare its own step verified.

**Division of labour between gates** ([gates.md](gates.md)): pytest owns the
*shape*, `--tags verify` owns the *effect*, `nos-smoke --strict` owns
*end-to-end truth*. None may claim another's job, and **a gate you can satisfy
by editing the gate is not one**.

**Commit convention** applies to anything a workflow commits: Conventional
Commits, subject ≤ 50 chars, body bullets ≤ 6 lines, no `Co-Authored-By`.

---

## 8. Two loops, and why the gate is a commit

Discovery files work; implementation changes the estate. Keeping them separate
is only real if the crossing costs something discovery cannot pay.

A **status column is the wrong gate** because it is data, and discovery's whole
job is writing data — it POSTs roadmap rows to KEAP over HTTP. Any lane it can
write, it can promote itself into, so the gate would hold by convention only. A
hallucinated finding would walk into a merged change and the two loops would be
one loop wearing a costume.

A **committed workflow spec** is on the far side of a boundary discovery has no
route across: it speaks HTTP to a table and cannot author, commit or push a
file. `meta.implements: '<slug>'` carries the binding, and it is the presence
of that line IN GIT that authorises — not its value.

What this cannot check: whether whoever committed the spec actually read the
row. Nothing static can. It checks that the crossing left a trace somewhere
discovery cannot reach, which is the property the split needs.

Operator-filed items lose nothing — a human writing the spec IS the triage.
Review and analysis workflows carry no `implements` because they change
nothing.

## 9. Recursion

The point of all of the above is a system that can improve *itself*. Three
invariants make self-modification monotone instead of degenerate:

1. **Asymmetric judgement.** The proposer may propose changes to anything —
   including the judges and including this document. A change to a judge must be
   evaluated by the **previous** version of that judge. Otherwise the shortest
   path to a passing verdict is rewriting the test.
2. **The ratchet is mandatory, not customary.** A self-enhancing system that may
   claim improvement without a retro-red gate will claim it.
3. **The anti-fabrication invariant is load-bearing.** A system that writes its
   own success markers converges on lying. Eight instances were found in
   *non*-recursive code in a single day; under recursion the drift compounds.

**Recursion argues for sequential.** Parallelism buys wall-clock at the cost of
coherence, and each iteration of a recursive system must build on the last.
Reserve fan-out for the veto step, which is the one place disagreement is the
product.

**Workflow definitions are therefore versioned** (`.claude/workflows/`, tracked
by an explicit un-ignore). The reasoning is the same one already recorded in
`.gitignore` for the nos-loop plugin — anything living only in per-host runtime
state drifts per host and CI never sees it — plus one more that only applies
here: *a loop cannot propose a change to a file that is not in the repository,
and a judge cannot be retro-red against a version that was never committed.*

---

## 9. The checklist

Before running a workflow:

- [ ] Every `parallel()` is `union` or `veto`, and says which in a comment
- [ ] No chain is disguised as a fan-out — no agent guesses another's output
- [ ] Grounding happens **once**; later agents receive the brief, not the task of rediscovering it
- [ ] Verify agents receive the artefact, not the author's account of it
- [ ] Findings carry evidence, enforced by `schema`, not by request
- [ ] Blast radius named, and rigour matched to it (§6)
- [ ] Any new gate is retro-red before it is believed
- [ ] What was **not** built is reported, explicitly

---

## 10. Open

- **Fable's independent review of this ground** — the operator ran one
  (session `01RZKdTSFz1wfKpjyJj2ZYVj`); its findings are not yet folded in.
  Session URLs are not machine-readable, so this must be pasted in by hand.
- **Cost accounting per workflow.** The numbers in §2 were reconstructed after
  the fact from transcripts. `budget.spent()` exists; nothing records a
  per-workflow cost against its outcome, so "was this workflow worth it" is
  still answered by impression.
- **The smallest recursive step**, not yet taken: let the loop propose a change
  to a workflow definition and have the *previous* judge rule on it. It carries
  all three invariants of §8 and either holds or fails safely.
