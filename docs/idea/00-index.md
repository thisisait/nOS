# docs/idea — the ten things nOS is actually trying to do

> Consolidated 2026-08-02 from 69 plan documents. Nine of them shipped, 38 never
> ran, and the rest overlapped each other. This directory is the living surface;
> `docs/archive/` holds the detail and the history.
>
> **Ceiling: twenty documents — BREACHED: 24 as of 2026-09-03, gated as a
> ratchet (test_idea_surface_is_indexed.py, ceiling may only fall) until an
> absorb/archive pass brings it back under.** Was ten until 2026-08-02, raised the same day the
> first new idea arrived, because forcing a merge nobody wanted is not what the
> constraint is for. At the ceiling one absorbs the next or one is finished. The
> previous surface reached 20 390 lines because nothing ever forced that choice.

Counted 2026-09-14: most “open/design” rows below had already shipped or
been seeded. Files stay in this directory until `idea-surface-absorb` moves
cites (gates still pin `docs/idea/11-agentic-loop-contract.md`,
`13-relations.md`, `15-business-fixture.md`, `21-mariadb-tls-ladder.md`,
`02-cortex-lang.md`). Ceiling stays 24 until that cite-migration; it may
only fall. Do not add idea 22+. Device work is dtt `device-organ`.

## The set

| | idea | status (honest 2026-09-14) | the one sentence |
|---|---|---|---|
| [01](01-secrets.md) | Secrets — kill the blast radius | **keep** — P1 inert; P3/P5 open | One leaked string yielded 103 credentials; the fix is one-way derivation, not a safer cupboard. |
| [02](02-cortex-lang.md) | cortex-lang — an ontology-typed IR | **shipped** — cite target; archive after absorb | The LLM emits a typed plan; execution is local, and a capability can never be added by data. |
| [03](03-cortex-corpus.md) | The corpus, and what it can honestly recall | **seeded** (`cortex-*`, `kpro`) — archive after absorb | Parity is measured nightly; the user tree is one document, so recall is thin by *input*, not by design. |
| [04](04-one-filesystem.md) | One filesystem | **keep** | The same document can live in three places and nothing decides which is real. |
| [05](05-per-user-isolation.md) | Per-user isolation | **seeded** `fs-peruser` — absorb into 04 | Per-user prices concurrency, not headcount — and the secret scope must be built before the containers are. |
| [06](06-genome.md) | The genome and its organelles | **keep** — L1 shipped; codegen still 2/4 | One declaration the runtimes inherit, instead of the same law restated in five languages. |
| [07](07-face.md) | face — the desktop and its tables | **keep** | Four render styles ship; the settings surface is the open half. |
| [08](08-lifecycle.md) | Lifecycle — blank, upgrade, coexist | **keep** — PG cutover never ran | The install↔leave loop closes; the upgrade engine's headline claim is still unexercised. |
| [09](09-hidden-fees.md) | Hidden fees | **keep** — pointer only; tally lives in `docs/hidden_fees/` | The costs paid without a decision. Do not copy a count here. |
| [14](14-notification-spine.md) | One notification spine | **seeded** — archive after absorb | One abstract channel; chats, mail and approval surfaces are implementations. The write half ships and no channel carries an answer back. |
| [12](12-state-surface.md) | The state surface | **seed** `state-surface` then archive | One artifact every model reads first — actor_id on events is the real gap. |
| [10](10-roadmap-surface.md) | The roadmap surface | **shipped** — archive after absorb | A plan that must be rewritten by hand to stay true will not stay true; the table is asked, not copied. |
| [11](11-agentic-loop.md) | The agentic loop | **built** — index said “design”; that was a lie (fee 50) | The propose→judge loop exists; remaining defects are `loop-*` rows. |
| [13](13-relations.md) | Relations | **R1–R5 shipped** — still a cite target | What is joined to what, and who owns the verb. |
| [15](15-business-fixture.md) | A real business on nOS | **increment 1 shipped** — cite target | A fixture is data that argues back. |
| [11a](11-agentic-loop-contract.md) | The loop engine contract | **settled law** — do not move until cite-migration | Tests and Bone import this path as the contract. |
| [13F](13-fable-review.md) | Fable review of the loop engine | **record** — colliding number | Filed under 13; 13 proper is relations. |
| [16](16-orchestrator-question.md) | The orchestrator question | **decision record** — not open | Which layer is ours. |
| [17](17-loop-split-refactor-graph.md) | Loop split refactor graph | **record** | Six-dimension research output, filed late. |
| [18](18-second-environment.md) | A second environment | **seeded** as `sere*` — archive after absorb | VPS, local VM, or neither yet. |
| [19](19-fable-review-2.md) | Fable review, second pass | **record** | Open asks already have `loop-*` slugs. |
| [20](20-devops-security-skills-read.md) | DevOps-security skills read | **record** — seed `compose-hardening` | Adopt none as a sweep. |
| [21](21-mariadb-tls-ladder.md) | MariaDB TLS ladder | **seeded** `sec-transport-mariadb*` — cite target | Remaining cliff is the seed, not this essay. |


## How to use this

**A document here earns its place by being actionable.** If it cannot say what
would be built next and what would prove it worked, it belongs in the archive.

**Every claim cites something that exists** — a file, a test, a measured number,
a REM id. This is not a style preference: the surface this replaced contained 38
documents planning work on a branch that had no commits, and nobody noticed for
seven weeks because nothing had to be checked against reality.

**The roadmap table is the state; these documents are the argument.** The KEAP
`nOS Roadmap` DataTable (`tools/roadmap-seed.py`) holds dates, statuses and
nesting. Do not duplicate them here — they will drift.

## What happened to the rest

- **`docs/archive/v07-overnight/`** — 38 plans, 11 230 lines, none implemented.
  See the README there for what survived and where it went.
- **`docs/archive/`** — nine plans that genuinely shipped, kept for archaeology.
- **At the next release**, reconcile the archive too and delete what has no
  successor. That is a decision to take deliberately, not a cleanup to drift into.
