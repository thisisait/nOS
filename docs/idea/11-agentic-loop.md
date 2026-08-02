# 11 — The agentic loop: recursive improvement on device

**Status: design, not built.** Opened 2026-08-02.
**Shape:** an **on-device deterministic engine** with a thin plugin over it, so
that Claude Code, Hermes and AgentKit are all *clients* of the same loop rather
than three loops that drift.

---

## 0. Where this sits in the field, honestly

"Graph engineering" became a term in July 2026 and covers **three** disciplines,
not one:

| | discipline | nOS |
|---|---|---|
| 1 | **orchestration graphs** — which agent runs next, with what state | workflows + AgentKit (partial) |
| 2 | **graphs of loops** — self-improving cycles | **absent — this document** |
| 3 | **graph-structured knowledge/memory** | cortex/KEAP (strong) |

The distinction that matters: knowledge graphs and GraphRAG model **data**;
graph engineering models **execution**. nos-cortex is (3). It is not the whole
thing, and calling it "our graph-engineering play" overstates by two thirds.

Scored against the five practices the field guide names, measured in the
`relations` schema rather than assumed:

| practice | nOS |
|---|---|
| typed edges | ✓ `type` + `relation_types` |
| entity resolution | ✓ deterministic `id = hash(from\|to\|type)` + `UNIQUE` |
| hybrid retrieval | ✓ `hybridSearch` (RRF) |
| graph validation | ✓✓ keap-lint · `onto1:` hash gate · nightly corpus-diff |
| **temporal supersession** | **✗** — `relations` has `created_at` and nothing else |

And two things nOS has that the guide does not think to ask for: full edge
**provenance** (`source` · `model` · `justification` · `confidence`) and
**moderation** (`status: proposed\|confirmed\|rejected`, nothing auto-applies).

**The one real gap is temporal supersession.** A confirmed fact never expires,
and a superseding fact collides on `UNIQUE (from_ref, to_ref, type)`. There is no
way to say *"this was true until X"*. That is a prerequisite for a loop that
learns, because a loop that cannot retire a belief accumulates them.

## 1. What already exists — do not rebuild it

The propose → evaluate → accept loop is **already running**, at single-session
scope, in AgentKit:

```
agent_iterations(session_uuid, iteration, grader_result, grader_feedback,
                 grader_model, tokens_in, tokens_out, created_at)
grader_result ∈ satisfied | needs_revision | failed
```

A separate Grader call, a `rubric.md`, an isolated context window, max 3
iterations. That is the textbook shape and it is live.

**What is missing is everything between sessions:**

1. **Nothing feeds a session's outcome into the next one's proposal.** Every run
   starts from zero. (`agent_memory_stores` / Dreams is adjacent, not this.)
2. **No weakness mining.** Nothing systematically decides *what to improve next*.
3. **No cross-session proposal ledger.** A rejected proposal can be re-proposed
   forever, and will be.
4. **The judges are scattered.** pytest, ansible-lint, corpus-diff, keap-lint,
   genome-codegen `--check`, nos-smoke are all deterministic judges — and not one
   of them is addressable as *"run this and give me a verdict"*.
5. **Nothing enforces that the judge is not the proposer.** `grader_model` is
   recorded; nothing checks it.

## 2. The rule the whole design hangs on

> **The judge is code. The proposer is a model. They never share an identity.**

This is v0.10-beta's doctrine one level up. *A step may not record its own
success* is bad enough when the record is a log line. In a self-improvement loop
the record **is the reward signal for the next modification**, so a proposer that
can influence its own verdict does not merely lie — it optimises against the lie.

Two consequences that are not negotiable:

- Every accept/reject comes from a **deterministic** run: exit codes, counts,
  diffs. Never from an LLM's opinion about its own work.
- The ledger is written by the **evaluator**, never by the proposer. (`nOS`
  already has the gate for the general case: `test_post_wiring_is_not_self_reporting.py`.)

An LLM judge is permitted only as an *additional, advisory* signal that can veto
but never grant.

## 3. The engine — deterministic, on device

A small host daemon, sibling to Bone/Pulse/Cortex, exposing loopback HTTP + a
CLI. Everything below is code with no model in the path.

| endpoint | does | built from |
|---|---|---|
| `GET /v1/weaknesses` | ranked list of what is wrong right now | pytest failures, `ansible-lint`, `remediation-queue.json`, `docs/hidden_fees/`, corpus-diff verdicts, `nos-smoke --failed-only` |
| `POST /v1/judge` | run a named gate set → verdict + evidence | the six judges above, each already exists |
| `GET /v1/budget` | what a proposal may touch, and how much | paths, max diff size, forbidden files |
| `POST /v1/proposals` | record a proposal (before it is tried) | ledger |
| `POST /v1/verdicts` | record the deterministic outcome | ledger — **evaluator writes, proposer cannot** |
| `GET /v1/history` | has this been tried? what happened? | ledger, keyed by proposal fingerprint |

**Why on device rather than in the harness:** determinism and portability. The
same judge must give the same verdict for Claude Code, for Hermes, for a Pulse
job at 03:00 with nobody watching, and for CI. A judge that lives inside one
harness is a judge that disagrees with itself across harnesses.

**Why it is a plugin and not a library:** three runtimes already exist in this
estate (Claude Code, Hermes, AgentKit/PHP) and a fourth is planned (the Rust
brain). A library would be ported three times and drift; an HTTP+CLI surface is
ported zero times.

## 4. The plugin — thin on purpose

```
.claude/plugins/nos-loop/
  .claude-plugin/plugin.json
  skills/
    weakness-scan/SKILL.md     # ask the engine what is wrong, rank it
    propose/SKILL.md           # ONE bounded change, against the budget
    judge/SKILL.md             # run the gate set, read the verdict
    loop/SKILL.md              # the ceremony: mine → propose → judge → record
  commands/
    loop.md                    # /loop-improve — one full cycle, operator-visible
```

The skills contain **no logic** — they call the engine. That is what makes the
same loop reproducible from Hermes, which will speak to the same endpoints with
no Claude in the picture.

## 5. Bounded, because unbounded is the failure mode

A loop that may change anything will eventually change the judge. Hard limits,
enforced by the engine and not by instruction:

- **The proposal may not touch the gate it will be judged by.** Computed from the
  gate set, refused at `POST /v1/proposals`.
- **A fingerprinted proposal that already failed is rejected without running.**
- **One change per cycle.** Two changes with one verdict teaches nothing.
- **Bounded diff size**, from `/v1/budget`.
- **`docs/`, `.claude/`, and the engine's own source are out of scope** by
  default. A loop that rewrites its own instructions is not improving, it is
  drifting.

## 6. Build order

1. **`POST /v1/judge` over the six existing judges.** No loop, no proposals —
   just one address that runs a named gate set and returns a verdict. Immediately
   useful on its own, and it is the piece every other part depends on.
2. **The ledger** (`/v1/proposals`, `/v1/verdicts`, `/v1/history`) with the
   evaluator-writes rule enforced in the schema, not the prose.
3. **`GET /v1/weaknesses`** — a reader over sources that already exist.
4. **The plugin skills**, thin over 1–3.
5. **Temporal supersession in `relations`** (§0) — needed before the loop's
   findings become knowledge rather than a log.
6. **A Pulse job** running one bounded cycle nightly, once 1–4 have run
   attended enough times to trust them.

## 7. What would prove it works

Not "the loop ran". **A weakness that was on the list, is not on the list, and
the verdict that removed it was produced by a judge the proposer could not
touch.** Anything less is a loop that reports its own success — which is the
defect this estate spent a whole release learning to distrust.
