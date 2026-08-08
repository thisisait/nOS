# docs/idea — the ten things nOS is actually trying to do

> Consolidated 2026-08-02 from 69 plan documents. Nine of them shipped, 38 never
> ran, and the rest overlapped each other. This directory is the living surface;
> `docs/archive/` holds the detail and the history.
>
> **Ceiling: twenty documents** — ten until 2026-08-02, raised the same day the
> first new idea arrived, because forcing a merge nobody wanted is not what the
> constraint is for. At the ceiling one absorbs the next or one is finished. The
> previous surface reached 20 390 lines because nothing ever forced that choice.

## The set

| | idea | status | the one sentence |
|---|---|---|---|
| [01](01-secrets.md) | Secrets — kill the blast radius | **active** | One leaked string yielded 103 credentials; the fix is one-way derivation, not a safer cupboard. |
| [02](02-cortex-lang.md) | cortex-lang — an ontology-typed IR | design frozen | The LLM emits a typed plan; execution is local, and a capability can never be added by data. |
| [03](03-cortex-corpus.md) | The corpus, and what it can honestly recall | partly built | Parity is measured nightly; the user tree is one document, so recall is thin by *input*, not by design. |
| [04](04-one-filesystem.md) | One filesystem | measured | The same document can live in three places and nothing decides which is real. |
| [05](05-per-user-isolation.md) | Per-user isolation | measured, queued | Per-user prices concurrency, not headcount — and the secret scope must be built before the containers are. |
| [06](06-genome.md) | The genome and its organelles | L1 shipped | One declaration the runtimes inherit, instead of the same law restated in five languages. |
| [07](07-face.md) | face — the desktop and its tables | active | Four render styles ship; the settings surface is the open half. |
| [08](08-lifecycle.md) | Lifecycle — blank, upgrade, coexist | mid-build | The install↔leave loop closes; the upgrade engine's headline claim is still unexercised. |
| [09](09-hidden-fees.md) | Hidden fees | a ledger, always open | The costs paid without a decision. Thirteen entries; two closed. |
| [14](14-notification-spine.md) | One notification spine | **half built** | One abstract channel; chats, mail and approval surfaces are implementations. The write half ships and no channel carries an answer back. |
| [12](12-state-surface.md) | The state surface | design | One artifact every model reads first — and 81 058 of 81 098 events have no actor, which is the real gap behind "show the session in Wing". |
| [11](11-agentic-loop.md) | The agentic loop | design | The propose→judge loop exists per session; nothing carries between them, and no judge is addressable. |

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
