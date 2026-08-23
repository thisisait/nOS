# The operator model — what a human does, and what may not happen without one

> Status: doctrine, opened 2026-08-23. Closes roadmap row `loop-operator-model`.
> Two halves: the operator's five steps (stated 2026-08-05) and the decision
> rights that say which of them an agent may take alone (stated 2026-08-23).

## 1. The five steps

The operator's own loop, recorded so it does not live only in a conversation:

1. **Promote an idea** from the planner to a plan.
2. **Review proposed plans** and promote one to a workflow.
3. **Release it** — a cron, or a manual run.
4. **File ideas and plans through a channel OUTSIDE the master session** —
   claw, hermes, a separate session.
5. **Manual testing**, to be replaced by a real Playwright e2e suite.

**Step 4 is the riskiest, not the easiest.** Several channels writing ideas
without dedup fills the planner with near-duplicates; `discovery-scan` already
needs an `obs-` prefix and a slug-skip for exactly that reason, and the ideas
table already carries `shepherd` twice and `traccar` twice.

## 2. Decision rights

The rule that generates all of them, stated 2026-08-23:

> **Either the playbook does it during the loop, or the operator runs `nos`.
> Nothing in between.**

An ad-hoc `docker compose down`, a hand-run `brew`, a `docker exec` that
changes something — these are refused not because they are dangerous but
because they are **invisible**. Nothing converges them, nothing records them,
and the next reader cannot tell them from drift. The playbook is where a
destructive act belongs; what needs gating is the APPROVAL, not the mechanism.

| change | who decides | on silence |
| --- | --- | --- |
| `config.yml` — the estate's own configuration | **operator, always** | wait |
| the roadmap — rows, statuses, priorities | operator, asked at low priority | **act, and record what was assumed** |
| everything else — code, gates, docs, readers, queue reconciliation | agent | act |

**Why `config.yml` is absolute.** It is the layer that decides what this estate
IS — which services exist, which flags resolve, which secrets are minted. A
config change is not reversible by reading; it is reversible only by another
converge, and on a live estate that is minutes of downtime for services someone
depends on. So it is asked, every time, and the asking blocks.

**Why the roadmap is not.** A roadmap row is a claim about intent, and a wrong
one is corrected by the next reader — `roadmap-verify.py` exists precisely so a
row that lies gets caught by a probe rather than by an outage. Blocking on it
would trade a cheap error for an expensive stall. Ask, prefer an answer, and if
none comes, act and write down what was assumed.

**A flag, not a command.** When an agent needs the operator, the ask should be a
line in `config.yml` or a row in the roadmap — something the machinery then
executes — never a shell command for a human to paste. That distinction is the
whole of the rule above.

## 3. This is beta scaffolding, and it should say so

The manual interventions above exist for **agility during beta**, while one
operator can hold the whole estate in their head and a wrong call costs an
afternoon. They are not the destination.

The destination is a harness good enough that development happens inside it —
UI included — so that approval is a click with an audit row behind it rather
than a sentence in a chat log. `Wing /pulse`, the `/users` console and the
face's Anatomy views are the beginning of that surface; the `agents-inbox` row
(`AskOperatorTool`, `AgentQuestionRepository`, `inbox/answer`) is the piece that
turns "the agent asked" into a record rather than a message.

Recording the temporariness matters because the alternative is that scaffolding
becomes architecture by default. When this estate is a company where every
decision costs someone's day, the ask has to be a surface with a trail — and the
table in §2 is what that surface must implement.

## 4. What this does not license

- An agent may not widen its own decision rights by editing this file. The same
  rule as everywhere: a gate you can satisfy by editing the gate is not one.
- "Act on silence" for the roadmap is not permission to act on a **config**
  question by routing it through a roadmap row.
- Autonomy over "everything else" still means **through the machinery**. Editing
  a rendered artifact under `~/stacks` instead of the template that produces it
  is a hand-poke wearing a different hat.
