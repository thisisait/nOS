# The agentic night — what can run, what must bound it, what stops it

**Status: runbook, authored 2026-08-16 for the operator's "wild night" ask.**
The design argument lives in the session reports and
`docs/minimax-groundwork.md`; this file is what the operator holds during the
night. §5 of `docs/idea/11-agentic-loop.md` is the governing doctrine:
*"Bounded, because unbounded is the failure mode."* The night is held to it.

## 1. What the night can honestly be — and the two things it cannot

**It cannot be "the whole self-improvement loop", yet.** Measured 2026-08-16:

- ~~**The loop engine has no driver.**~~ **CLOSED 2026-08-19** (`a60516a6`,
  "a cadence, an entry, a named deadlock"). It was true when measured on
  2026-08-16 — nothing invoked the weakness→propose→judge surface. Today
  `loop:propose` runs nightly at 01:30, `loop:drive` at 06:10 judges what
  nobody ruled on (`f3b34a19`), and `loop:review` merges behind three YES
  answers at 06:50. The roadmap row `loop-driver` was closed 2026-08-22 on
  its own probe.

  Kept struck through rather than deleted because the sentence outlived its
  measurement in THREE places — here, the roadmap row, and
  `tools/loop-status.py --gap`'s own output — and each reader found it
  independently and believed it. What replaced it is a rate: the entry half
  takes one weakness per night, so the gap is a backlog in nights, and the
  thing that actually stops a night is uncommitted evidence.
- **AgentKit's tool surface cannot reach the loop even by accident.**
  `McpBoneTool` is GET-only and requires an `/api/` path prefix; the loop
  routes are POST `/v1/*`. Double-walled off.

**It also cannot be Pulse-scheduled.** All ten ceremonies' `command` points at
`pulse-run-agent.sh` (the shell bridge → claude CLI); the `runner: agent`
enum in the pulse_jobs schema has no implementation in the daemon. A binding
on an agent changes what `bin/run-agent.php` does — it changes NOTHING about
what the Pulse job runs. So the night is **supervised invocations of
`php files/anatomy/wing/bin/run-agent.php --agent=<name>`**, one at a time,
not an unpausing of the Sunday fleet (which stays paused; only
`conductor:self-test-001` is live, on the shell bridge, untouched).

What the night IS: the first real AgentKit sessions — tools driven by the
Runner, MiniMax serving the eligible tier, sessions/iterations/audit lineage
finally written by the runtime that owns them.

## 2. Who may run, by ruling 1's own two axes

| agent | output axis | data axis | verdict |
|---|---|---|---|
| librarian (brief/describe/judge-lint) | text | public knowledge corpus | **eligible — already bound** |
| curator | text (proposals via describe seam) | knowledge corpus | **eligible** (needs its 3 edits) |
| conductor | text report | estate metadata (events, job catalog) | eligible, operator's eyes on the transcript |
| migration-author | **authors code** | repo | **excluded** (output axis) |
| upgrade-architect | **authors code** | repo | **excluded** (output axis) |
| inspektor | — | — | **excluded** (`runner_status: deferred`; its register entry depends on it) |

(The 2026-08-26 roster close retired scout / remediator / upgrade-advisor and
parked curator / migration-author — rows here describe only agents that still
exist; ask `tools/agent-status.py` for the live roster.)

Every "eligible" beyond librarian needs its own three edits BEFORE its first
routed run: primary → `anthropic-claude-sonnet-4-5`, `backend: minimax`,
MiniMax processor entry in its own `gdpr:` block — and carries the disarm
consequence: an `anthropic-*` primary unbound demands an `ANTHROPIC_API_KEY`
the estate does not set, so **disarming = putting `claude-sonnet` back
deliberately, per agent**. The excluded three stay on the shell bridge and
are not touched that night.

## 3. Bounds — what exists, what is missing

**Exists, enforced:**
- per LLM call: SDK timeout 600 s (`RequestOptions.php:38`)
- per iteration: ≤ 30 LLM calls (`Runner::MAX_LLM_CALLS_PER_ITERATION`)
- per session: ≤ `max_iterations` (3 default, 10 hard schema cap)
- per token: `CLAUDE_CODE_MAX_OUTPUT_TOKENS`-equivalent via `maxTokens`
- resolver gates: per-agent binding, register agreement, tier carve-out,
  protocol match — a session that should not exist refuses at open
- loop side (if a driver ever fires): deny-by-default path budget,
  fingerprint dedup, one change per cycle — already live in Bone

**Missing, and named as pre-night work rather than assumed:**
1. **Session wall-clock ceiling.** Worst case today: 3 iterations × 30 calls
   × 600 s ≈ 15 h for ONE stuck agent. The night needs a Runner-level
   deadline (kill the session, `stop_reason: timeout`, session terminated
   honestly) — without it, "supervised" means the operator is the timeout.
2. **Session token ceiling.** Tokens are counted and recorded but nothing
   stops a session at N. MiniMax cost is unpriced by design (`cost_basis`),
   so TOKENS are the honest budget unit.
3. **The agent-run mutex does not cover API sessions.** `agent-run-lock.sh`
   serializes *claude CLI* spawns; `bin/run-agent.php` on the API path never
   takes it. One-at-a-time is operator discipline for this night — fine
   supervised, a gap before anything is scheduled.

## 3b. The CLI entry point does not inherit the daemon's environment

Measured 2026-08-16 while landing the first real session: `bin/run-agent.php`
runs in whatever shell invoked it, NOT under wing.plist — so the two envs the
binding layer depends on are simply absent unless exported:

- **`NOS_REPO_ROOT`** absent → the DI container dies with a TypeError (the
  neon's fail-soft promise cannot hold when `::getenv()` yields `false`).
- **`NOS_ARMED_BACKENDS`** absent → a bound agent resolves DISARMED. For an
  ordinary agent that silently serves the default; for a
  `transfers_outside_eu: false` agent, gate 8 refuses the run outright —
  correct, but confusing if you forgot the export.
- The tier envs (`NOS_MINIMAX_MODEL`, `NOS_MISTRAL_MODEL`, …) follow the
  same rule: armed-without-a-model-id refuses at session open.

Before any supervised invocation, export the trio (values from wing.plist —
`plutil -p ~/Library/LaunchAgents/eu.thisisait.nos.wing.plist | grep NOS_`),
or wrap the call in `launchctl print`-derived env. A future
`tools/run-agent.sh` wrapper that reads the plist and refuses to start
without them is the structural fix; until it exists, this section is it.

## 4. Observability — what the operator watches

- `sqlite3 -readonly ~/wing/app/data/wing.db "SELECT agent_name, status,
  model_uri, tokens_input, tokens_output FROM agent_sessions ORDER BY id
  DESC LIMIT 5;"` — the session row, live.
- The events stream for this run's `actor_action_id`: `agent_session_start`
  (carries `backend` + `model_effective` — MiniMax runs must say so),
  `agent_message`, `agent_tool_use`/`agent_tool_result`,
  `agent_model_fallback` (if the primary failed, WHO answered),
  `agent_binding_disarmed` (the ask-but-not-armed shape), `agent_session_end`.
- Wing `/agents/<name>/sessions/<uuid>` — transcript, iterations, trace link.
- **Stop signals:** a fallback event on the first call (backend broken — stop,
  don't retry into it); tool_result errors repeating (prompt written for the
  CLI runtime, not the AgentKit tool shape — stop, fix the prompt, one
  ceremony at a time); tokens climbing without tool calls (loop-shaped
  chatter — stop).

## 5. The kill path, in escalation order

1. **One session:** wait out the 600 s call timeout, or kill the
   `run-agent.php` process — the session row stays `running` (orphan);
   record it, that is A8's known orphan shape.
2. **The backend:** `minimax_enabled: false` + converge (or edit
   `NOS_ARMED_BACKENDS` out of the wing plist + `launchctl` reload — note
   `e98313a1`: bootout, WAIT, then bootstrap). Every bound agent then
   REFUSES at session open (`anthropic-*` unbound demands a key that is not
   set). That refusal is the kill switch working, not a defect.
3. **The key:** remove `minimax_api_key` from `credentials.yml` + converge;
   the resolver refuses at "auth_secret resolves to nothing".
4. **Everything:** the ceremonies were never unpaused, so there is nothing
   scheduled to stop. The shell-bridge fleet is untouched by all of the
   above.

## 6. After the night

Per routed run: verify `model_effective` in the start event, tokens > 0 in
the end event, `cost_basis` handling on any CLI-path comparison runs, and
whether the session's tool calls matched what the ceremony's system.md
promised — the prompts were written for the CLI runtime, and the night's
most likely finding is prompt/runtime mismatch, which is a per-ceremony fix,
not a platform one.
