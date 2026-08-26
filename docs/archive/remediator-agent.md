# nOS Remediator — security-finding triage agent

> **Status: RETIRED 2026-08-26 (roster close)** — shipped 2026-05-17, one
> live run (2026-05-17), zero events in the wing.db epoch that followed. Its
> brief lives on as the loop's `rem` weakness source, which filed every real
> proposal the loop has made. Profiles, launcher, gates, Authentik client and
> secrets were all removed; git history keeps them. The generic
> pulse-run-agent.sh gates it earned moved to
> `tests/anatomy/test_pulse_run_agent_contract.py`; the retirement itself is
> pinned by `tests/anatomy/test_agent_roster_close.py`. The rest of this
> document is HISTORY.

## What it is

A read-only security-triage agent that runs on demand (or via webhook,
post-A14.5). For every open `gitleaks_findings` row, the remediator:

1. Fetches surrounding file context (`bash-read-only`).
2. Proposes ONE specific remediation per finding: file path, line, snippet,
   operator action verb-noun.
3. Writes a markdown `## Remediation report` event to `wing.db`.
4. Fires an A9 notification with severity = max severity analyzed.

The remediator does **not** auto-resolve findings, auto-fix files, or
auto-commit. Operator reviews proposals via Wing /inbox and marks
findings resolved manually.

## Why a second agent instead of more conductor scope

Conductor verifies platform health end-to-end (read-only diagnostics
across every surface). Remediator focuses tightly on one surface
(security findings) and produces ONE artifact per run (a markdown
triage report). Keeping them separate means:

- **Different schedules.** Conductor runs Sunday 04:00 UTC; remediator
  runs ad-hoc right after gitleaks emits findings.
- **Different RBAC.** Conductor has `authentik_agent_scopes` (full
  operational). Remediator has read-only scopes only — explicitly NO
  `nos:security:write` or `nos:security:scan`.
- **Different prompts.** Conductor's evidence-discipline rubric covers
  "is the platform healthy"; remediator's covers "is each finding
  triaged with a concrete next step."

## Usage

```bash
# Pre-flight + interactive run + markdown report
bash tools/run-remediator.sh

# Pre-flight only
bash tools/run-remediator.sh --dry-run

# Custom report destination
REMEDIATOR_REPORT_FILE=/tmp/triage.md bash tools/run-remediator.sh
```

Exit codes:

| Code | Meaning |
|---|---|
| `0` | Triage exit 0 — typically no open findings; nothing to review |
| `1` | Triage exit 1 — findings need operator attention (read the report) |
| `2` | Pre-flight failed |

The report lands in `~/.nos/remediator-report-<ISO timestamp>.md` and is
tee'd to stdout. Sections:

- **Pre-flight** — Bone health, pulse_jobs row, Authentik liveness, open
  findings count snapshot at start.
- **Post-flight** — Δ events + Δ notifications + the run's `actor_action_id`.
- **Event lineage** — every event emitted under that `actor_action_id`.
- **Remediator's own report** — the model's markdown extracted from the
  `conductor_report` event's `result_json.report_markdown`.
- **Triage stdout/stderr** — last 60 lines of subprocess output.
- **Verdict** — `GREEN` (exit 0, clean) / `REVIEW` (exit 1, findings to
  triage) / `RED` (exit ≥2, env error).

## How env vars get resolved

Same pattern as `tools/run-phase5-ceremony.sh` (see
`docs/phase5-ceremony.md`): the wrapper reads `env_json` from
`pulse_jobs` for the `triage-open-findings` row. Ansible already rendered
all `{{ global_password_prefix }}` + `{{ tenant_domain }}` references at
plugin-loader time, so the script doesn't reload secrets — it just
exports whatever's in the DB row.

## Authentik client

`nos-remediator` registered in `default.config.yml::authentik_agent_clients`.
Capabilities (intentionally minimal):

- `nos:state:read`
- `nos:security:read`
- `nos:migrations:read`
- `nos:upgrades:read`
- `nos:patches:read`

**No write/scan scopes.** This is enforced by an anatomy gate
(`test_remediator_pulse_profile_capabilities_read_only` +
`test_authentik_client_nos_remediator_registered`) so a future config
change can't silently widen the surface.

## Notification routing

Per the `notification:` block in `files/anatomy/agents/remediator.yml`:

| Severity (max analyzed) | Channels |
|---|---|
| `critical` | `wing-inbox`, `ntfy`, `mail` |
| `high`     | `wing-inbox`, `ntfy` |
| `medium`   | `wing-inbox` |
| `low`      | (silent — wing-inbox floor) |
| `info`     | (silent) |

The runner picks the max severity automatically — operator gets exactly
one notification per remediator run, not one per finding.

## Pulse-runner ⇄ AgentKit relationship

There are two agent representations:

| File | Used by | Purpose |
|---|---|---|
| `files/anatomy/agents/remediator.yml` | `pulse-run-agent.sh` (A8 path) | Pulse subprocess runner — claude CLI invocation |
| `files/anatomy/agents/remediator/agent.yml` (+ `system.md` + `rubric.md`) | AgentKit runtime (A14 path) | PHP runner — Wing /agents UI, outcome iteration, dreams |

They share the same identity (Authentik `nos-remediator`, A10
`actor_action_id`) and the same notification routing (Bone aggregator
keys by `origin_agent: remediator`). The system prompts overlap but
the AgentKit-side is richer (rubric-driven grader loop). Either runner
fires the same operator-facing report shape, so the wrapper script
treats them interchangeably.

## Generic `pulse-run-agent.sh`

As part of A9.3, `files/anatomy/scripts/pulse-run-agent.sh` was
genericized from conductor-only to multi-agent:

- Reads `NOS_AGENT_*` env (canonical): `NOS_AGENT_NAME`,
  `NOS_AGENT_CLIENT_ID`, `NOS_AGENT_CLIENT_SECRET`, `NOS_AGENT_PROFILE`,
  `NOS_AGENT_TASK`.
- Backward-compat: `NOS_CONDUCTOR_*` still works (conductor's existing
  Pulse env_json keeps functioning unchanged through one re-run).
- Wing event source/origin/actor_id auto-tag from `NOS_AGENT_NAME`.
- A9 notification on non-zero exit uses the agent's profile for routing
  (Bone aggregator looks up `origin_agent: <NOS_AGENT_NAME>`).

Both anatomy gates pin this contract:
`test_pulse_run_agent_reads_nos_agent_env` +
`test_conductor_uses_nos_agent_env`.

## When to run it

- **After a gitleaks Pulse run that emits findings.** The natural pair:
  gitleaks finds → remediator triages → operator acts. The A9
  notification from gitleaks tells the operator a triage is needed.
- **After resolving a batch of findings.** Run again to verify "no
  open findings" + clean inbox state.
- **Before pushing a fix to production.** If you just rotated a leaked
  credential, the remediator's empty-findings case confirms the cleanup
  was complete.

## Out of scope (post-A9.3)

- Auto-fanout (A14.5): the gitleaks notification webhook triggers the
  remediator without operator action. Today operator triggers manually.
- Per-finding model-grader iteration: the AgentKit profile has the
  outcome-rubric loop, but `tools/run-remediator.sh` uses the Pulse
  runner (claude CLI, one-shot). Wire `php files/anatomy/wing/bin/run-agent.php
  --agent=remediator` for the AgentKit path.
- Patch suggestion as a `patches_applied` candidate row (Track P
  follow-on).
- Cross-finding correlation engine (the rubric already calls for it in
  the `Recommendations` section, but model does it ad-hoc per run).
