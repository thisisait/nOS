# The first bound night, simulated — four runs, measured

Fired on 2026-08-28 via `POST /api/v1/pulse_jobs/<id>/run-now`, so the Pulse
daemon dispatched them with every guard intact. This is not a full night: it
does not exercise the cron schedule or the jitter, and the runs serialised on
the N=1 lock instead of being an hour apart. Everything after dispatch is real.

| session | agent | job | wall | in / out | tool calls | POSTs | outcome |
|---|---|---|---|---:|---:|---:|---|
| `505e0f11` | surveyor | surface-survey | 114 s | 257 953 / 7 728 | 22 | 0 | `outcome_failed` |
| `df2a5477` | librarian | describe-taxonomy | 20 s | 22 868 / 1 659 | 4 | 3 | **`outcome_satisfied`** |
| `eda9929a` | librarian | judge-lint-queue | 85 s | 241 292 / 5 721 | 18 | 0 | `outcome_failed` |
| `5fd9074a` | surveyor | surface-survey (re-run) | 88 s | 221 415 / 5 160 | 16 | 1 (**failed**) | `outcome_satisfied` |

The fourth run was fired AFTER the converge that deployed the §5 fixes, as a
clean test of one change. It is the run that matters most, for a reason nobody
was looking for — see §6.

## 1. The HMAC fix is PROVEN, and that is the good news

`df2a5477` posted `POST /api/v1/events` three times: **400** (`Missing required
field: ts`), **400** (`Missing required field: run_id`), **201** (event 373987).
A 400 is the proof — it means `EventsPresenter::checkHmac()` verified the
signature and the payload was parsed. Before 2026-08-28 the same call was a 401
at that gate, and every ceremony died on its rubric because of it.

It is also the first AgentKit session in this estate's history to reach
`outcome_satisfied` — and, read against §6, the only one so far whose
deliverable actually exists. Several answers in `03-questionnaire.md` (Q8, Q10)
named that event as their unblocking condition; it is met, by one run, under a
marker §6 shows to be unsound.

## 2. What `satisfied` did NOT mean here

The describe queue was **empty** (`total: 0`). The grader marked the run
satisfied for handling an empty intake honestly — correct, and doctrine-aligned:
the agent did not fabricate work. But the ceremony did no describe work, and the
outcome does not say so. `satisfied` on an empty intake is today
indistinguishable from `satisfied` after work.

Measured against KEAP the same hour: describe pending **0**, brief pending
**1281**, lint findings open **121** (3 HIGH), unpromoted captures **198**. So
`describe-taxonomy` is a job whose backlog is finished and which will run empty
every night at 02:10; the work is in the other two.

## 3. THE FINDING: the bound loop reads and does not write

Across the two runs with real intake, the model made 40 tool calls, all reads,
all HTTP 200, and issued **zero** writes. `eda9929a` fetched the lint queue,
paged through 198 unpromoted captures, ran five semantic searches, read four
taxonomy nodes — and then produced no verdict, no promotion, no proposal and no
report. The grader's own words:

> 198 unpromoted captures exist, agent browsed them but issued no POST to
> `/agent/v1/promotions`

The one run that wrote anything was the one where reading returned nothing, so
the report was the only remaining action.

This sharpens the shape recorded on 2026-08-17 (`test_the_bound_agent_loop_is_unproven.py`:
"a one-line preamble, a tool call, repeated until the budget ends"). It is not
that the model stops producing. It is that **it does not transition from reading
to writing**. Token ratios say the same thing from another angle: 241k in
against 5.7k out, ~40:1.

That transition is a harness problem, not a prompt typo, and it is the thing to
fix before any layer is built on this runtime.

## 4. Bound agents have no principal

`McpBoneTool` sends **no `Authorization` header at all** (`McpBoneTool.php:63-68`),
so every Bone endpoint behind `require_scope()` (`bone/auth.py:180-205`) answers
401 — which is what `505e0f11` got on `/api/state/services`.

It is not a bug in one tool. The CLI path performs an Authentik
`client_credentials` exchange and requests the agent's declared scopes
(`pulse-run-agent.sh:232-252`); the bound path performs **none** — neither
`tools/run-agent.sh` nor `bin/run-agent.php` contains the string. So a bound
agent presents nothing to Bone, and presents the daemon's shared
`WING_API_TOKEN` to Wing rather than an identity of its own.

`actor_id` on a bound run is therefore an assertion, not a proof — exactly the
distinction `00-terminology.md` reserves the word **principal** for. That
document inferred it from reading the code; these runs measured it.

## 5. Why the model guessed API paths

`505e0f11` called `/api/v1/systems` and `/api/v1/health`; neither is routed. The
surveyor's `system.md` names **no API routes at all**, so the model invented
plausible ones from `McpWingTool`'s prose description ("health probes, event
queries, pulse-job lookups, system listings"). Every other agent's prompt
enumerates its routes and none of them guessed.

## 6. `outcome_satisfied` does not require the deliverable to exist

`5fd9074a` is the run to read twice.

The §5 fixes worked exactly as intended: **zero invented routes**. All seven Wing
calls hit real endpoints, and the model went straight to `/api/v1/hub/health`,
`/api/v1/dashboard/summary`, `/api/v1/pulse_jobs`, `/api/v1/hub/systems`,
`/api/v1/dashboard/timeline`, `/api/v1/agents`. It also transitioned from reading
to writing — it attempted `POST /api/v1/events`, which the previous surveyor run
never did.

**The POST failed: HTTP 400, `Invalid JSON body`.** No `conductor_report` event
exists for this session. The survey was never filed.

**The grader returned `satisfied`, with empty feedback.** `files/anatomy/agents/surveyor/rubric.md`
does not mention filing, posting or `/api/v1/events` anywhere — so the grader
scored the prose in the transcript and never asked whether the artifact exists.

That is the estate's oldest defect in its newest place: a success marker written
by something that did not check the work. It is worse than the three failures
above, because a failure is legible and this reads green. Any surface counting
`outcome_satisfied` today counts this run.

Two corollaries:

- **Q9 now has live evidence.** The deliverable was lost to malformed JSON, not
  to a wrong judgement — precisely the case the operator's answer specifies:
  hardcoded shape repair first, one bounded format-only re-ask, else UNPARSEABLE.
  A missing bracket cost a whole survey.
- **A filed report is not joinable to its session.** The librarian's successful
  201 (event 373987, `type=conductor_report`, `source=librarian`) carries
  `actor_action_id` NULL. `docs/ait-runtime-architecture.md` promises that one
  `SELECT WHERE actor_action_id` reconstructs a run; for agent-filed reports it
  does not. Across the table: 7 `conductor_report` rows, 1 with no session id —
  and it is the only one an AgentKit session ever wrote.

## 7. One more 401

`GET /api/v1/state` answered 401 to `mcp_wing`, which does send the bearer. Not
diagnosed here; noted so it is not rediscovered. It is not the Bone gap of §4 —
different door, different cause.

## Disposition

Fixed before the next converge, because none of it collides with the planned
build workflow:

- **§5** — a 404 from `mcp_wing` now answers with the live route table, read
  from `RouterFactory` so the hint cannot drift (`403b2be9`, gate
  `test_bound_agent_can_file_its_report.py`).
- **§5** — the surveyor's prompt names its routes. VERIFIED by run `5fd9074a`:
  zero invented routes, and the model reached the write step for the first time.
- **§1** — `/api/v1/events` names every missing field at once instead of one per
  round trip; the agent spent two calls discovering the contract one field at a
  time.

Handed to the build workflow, because fixing it here would collide:

- **§6** satisfied-without-the-artifact → the Oracle phase, and it is now that
  phase's first job rather than a refinement. `gate_run_id` is the mechanism; the
  rule is that a ceremony whose deliverable is an event may not be satisfied
  unless that event EXISTS and names the session.
- **§6** the report/session join → the Ledger phase (`actor_action_id` on
  agent-filed events, same provenance problem as `loop_proposals.session_uuid`).

- **§3** read-without-write → the Oracle phase (best-of iteration and the
  three-stage output contract are aimed at exactly this).
- **§4** no principal → the Grant phase (per-agent principals and scoped tokens).
- **§2** satisfied-on-empty → the Oracle phase (who writes satisfaction, and
  from what evidence).
- **§2** `describe-taxonomy` runs empty nightly — an operator decision about the
  job, not a defect to patch.
