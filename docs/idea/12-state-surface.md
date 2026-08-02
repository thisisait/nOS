# 12 — The state surface: one file every model reads first

**Status: design, 2026-08-02.** Companion to [11](11-agentic-loop.md) — the same
engine serves it, because a weakness reader and a state reader are the same
reader with different framing.

---

## 0. The idea

A model arriving at this estate — Claude Code, Hermes, an AgentKit agent, the
future Rust brain — should not have to *hunt* for what is true, and must not
fall back on what it remembers. It reads one artifact:

- what the system **is** right now (services, versions, health, open findings)
- **where it is** on the roadmap: a few steps behind, the current one, a few ahead
- a `refresh` it can call to be sure the artifact is current

Regeneration budget: **under 3 seconds, no model in the path.**

## 1. The budget is a specification, not a limit

Measured on this estate, 2026-08-02:

| | |
|---|---|
| cached-only state read (git + `~/.nos/*.json` + queue + `docker ps`) | **0.52 s** |
| `ansible-lint main.yml` | 25.2 s |
| `pytest tests/anatomy` | 183 s |

So the three-second rule **forces the correct architecture**: the state surface
**reads verdicts; it never produces them.** It is a projection over artifacts
that already exist — the ledger, `~/.nos/cortex-corpus-diff.json`,
`backup-status.json`, `remediation-queue.json`, `git status`, `docker ps`, and
the roadmap table.

That is the same separation as judge-versus-proposer, one level out: **the thing
that reports state must not be the thing that determines it.** A state file that
ran the judges would take four minutes and would be, in effect, a judge that
answers to whoever asked for context.

Hourly regeneration is therefore free. Per-request would also be free; the
`refresh` endpoint exists so a model can be *certain*, not because an hour is
too stale.

## 2. The leak question, answered structurally rather than carefully

The operator's instinct is right, and the precedent is specific: **REM-144 was a
rendered artifact disclosing the password prefix.** A state file is a rendered
artifact by definition, so "we will be careful about what goes in it" is exactly
the assurance that failed then.

**The rule: the generator refuses to write a state file containing any known
secret.** Not review — refusal.

Concretely, and cheaply:

1. Build the candidate state document.
2. Scan it for every value in `~/.nos/secrets.yml`, for `global_password_prefix`,
   and for the `_pw_` marker.
3. **Any hit → refuse to write, exit non-zero, name the field.** Never write a
   redacted version: a redaction that silently succeeds trains everyone to stop
   looking.
4. A gate retro-verifies this by planting a known secret in a source and
   asserting the generator refuses.

What the file may hold: service names, versions, health, ports **that are already
loopback-published**, open finding *ids and severities*, roadmap rows,
verdict summaries. What it may never hold: any value that is or derives from a
credential, and any full path outside `nos_data_root` that would map the host.

Reconnaissance value is real but bounded — everything in it is derivable by
anyone who already has host access, which is the only audience. It stays
loopback-bound and out of `state/manifest.yml`, so no Traefik router is ever
derived for it (constraint E of the loop engine).

## 3. The Wing question — and the number that reframes it

The operator asked for the **master session** (the Claude Code session driving
the work) to appear in Wing's `/agents`. Before adding it, two measurements:

```
agent_sessions:  2 rows           — both `conductor`, both via pulse
events:      81 098 rows          — of which 81 058 have actor_id = NULL
```

**Attribution is 99.95 % empty.** Four actors have ever been recorded:
`apps_runner` (24), `nos-conductor` (10), `agent:devlog` (6).

So "show the master session in `/agents`" would add one row to a table holding
two, while eighty-one thousand events say nothing about who caused them. **The
missing surface is not the session — it is the attribution.**

### And it is an actor, not an agent

`agent_sessions` requires `agent_name` matching `files/anatomy/agents/<name>/`
and an `agent_version` pinned at session start. This session has no definition
directory, no version, no `rubric.md`, no outcome contract. Forcing a row in
would make `/agents` **lie about what it is showing** — a catalogue of defined,
versioned, graded agents would silently contain something that is none of those.

The estate already has the right primitive: `actor_id` / `actor_action_id`, the
audit lineage where `actor_action_id == agent_sessions.uuid` reconstructs a run.
A Claude Code session is an **actor** — `operator:claude-code` — not an agent.

**Order of work:**

1. **Populate `actor_id`.** 81 058 unattributed events is the real defect; the
   callback plugin and the Bone events path both already accept the field.
2. **Wing gains an actor view** — "what did this actor do", spanning events and
   sessions.
3. *Then* the master session appears there naturally, alongside every other
   actor, without pretending to be a graded agent.

## 4. Shape

`GET /v1/state` on the loop engine ([11](11-agentic-loop.md)), plus a file at a
stable path so a model with no network can still read it.

```
identity      tenant, host, nos version, git ref + dirty?
services      name, image tag, health          (docker ps)
findings      open ids + severities            (remediation-queue, hidden_fees)
verdicts      last known, per judge + when     (ledger — never re-run here)
roadmap       3 behind · current · 3 ahead     (the nOS Roadmap table)
freshness     generated_at, per-source age, and WHO generated each source
```

The last row carries the lesson of `scan-state.json`, whose `last_full_scan` was
written by the scan itself and then read as proof of freshness — the alarm was
fed the value that silenced it. **Every source in the state file declares whether
its freshness is self-reported.** A model reading `corpus-diff: 6 h old
(self-reported)` knows to weigh it differently from `git: 0 s (observed)`.

## 5. What would prove it works

Not "the file exists". **A model that has never seen this estate answers three
questions correctly from the file alone** — what is broken, what shipped last,
what is next — and a fourth incorrectly on purpose: something the file does not
claim to know, where it says so rather than guessing.
