# Phase 5 ceremony — operator-driven conductor self-test

> **Status:** CLI shipped 2026-05-17. **Anatomy gate:**
> `tests/anatomy/test_phase5_ceremony.py` (8 tests).
> **Source-of-truth for the ceremony task:**
> `files/anatomy/agents/conductor.yml::pulse.jobs[0]`.

## Why

The conductor `self-test-001` Pulse job runs Sundays at 04:00 UTC by
default. **Phase 5** — the operator's milestone gate proving the
conductor agent can write to `wing.db` end-to-end without operator
input — historically meant "wait until Sunday or fudge the cron." This
CLI lets the operator fire that ceremony on demand, any time, with the
same env Ansible rendered into `pulse_jobs.env_json`.

It's also useful for routine verification: after a blank, after a
contracts-drift PR, before pushing — a 60-second smoke that the
conductor still works end-to-end.

## Usage

```bash
# Standard run
bash tools/run-phase5-ceremony.sh

# Pre-flight checks only (no subprocess fire)
bash tools/run-phase5-ceremony.sh --dry-run

# Custom report destination
PHASE5_REPORT_FILE=/tmp/my-report.md bash tools/run-phase5-ceremony.sh

# Non-default Bone port (defaults to 8099)
BONE_API_URL=http://127.0.0.1:8088 bash tools/run-phase5-ceremony.sh

# Non-default Wing DB path (defaults to ~/wing/app/data/wing.db)
WING_DB_PATH=/elsewhere/wing.db bash tools/run-phase5-ceremony.sh
```

Exit codes:

| Code | Meaning |
|---|---|
| `0` | Ceremony exit 0 — operator can move on |
| `1` | Ceremony exit ≠ 0 — operator review needed (read the report) |
| `2` | Pre-flight failed (missing dep / unreachable Bone / no pulse_jobs row) |

## Output

Markdown report written to `~/.nos/phase5-report-<ISO timestamp>.md` and
also tee'd to stdout. Sections:

- **Pre-flight** — Bone health, pulse_jobs row presence, Authentik
  reachability (when applicable)
- **Post-flight** — Δ event count + Δ notification count + the
  `actor_action_id` that groups the run's events
- **Event lineage** — table of `(type, ts, exit_code, summary)` for
  every event sharing the run's `actor_action_id`
- **Ceremony stdout/stderr** — last 60 lines of subprocess output
- **Verdict** — `GREEN` (exit 0 AND ≥2 events written) or `RED` with a
  triage checklist

## How env vars get resolved

The script reads `pulse_jobs.env_json` from `wing.db` for the conductor
self-test row. Ansible already rendered all `{{ global_password_prefix }}`
+ `{{ tenant_domain }}` + `{{ bone_secret }}` references when the plugin
loader registered the job (`POST /api/v1/pulse_jobs` after the
playbook's `tasks/stacks/core-up.yml` ran). So the wrapper doesn't need
to know the prefix — it just exports whatever Ansible wrote.

This matters for two reasons:

1. **Single source of truth.** If the operator rotates
   `global_password_prefix`, re-running the playbook updates
   `pulse_jobs.env_json` automatically; this CLI inherits the new value
   on the next invocation.
2. **No secrets-on-CLI.** The script never reads `default.credentials.yml`
   directly; the resolved values live in SQLite which is mode 0640
   under `~/wing/`.

## What constitutes a GREEN verdict

```
ceremony exit == 0  AND  events_after - events_before >= 2
```

The "≥2 events" floor is the minimal start+end pair `pulse-run-agent.sh`
emits (`agent_run_start` + `agent_run_end`). A successful ceremony also
writes intermediate `conductor_self_test_step` events and a final
`conductor_report` event, so a real green run typically shows
`event_delta ≥ 4`.

A non-zero exit with `event_delta == 2` (start+end but the in-between
work failed) emits the A9 notification path the conductor wires up —
check `notification_delta` in the post-flight section and inspect
`~/wing/app/data/wing.db` for the `origin_agent='conductor'` rows.

## When to run it

- **After every blank reset** — confirms the conductor can authenticate
  via Authentik client_credentials and write to wing.db. If RED,
  `tasks/stacks/core-up.yml::Plugin loader — pulse-job registration` is
  the most likely culprit.
- **Before a `git push origin master`** — proves the trunk is shippable.
- **After an upstream Claude CLI bump** — claude releases occasionally
  change `--print` / `--system-prompt` flags; this catches breaks
  before they hit the Sunday cron.
- **As a Wing /audit feed** — every manual run leaves a clean
  `actor_action_id` cluster in `events` + `notifications` (when
  conductor exits non-zero).

## Triage when RED

1. Read **Ceremony stdout/stderr** at the bottom of the report — the
   conductor's own stdout names the failing step.
2. `sqlite3 ~/wing/app/data/wing.db "SELECT severity, title, body FROM
   notifications WHERE origin_agent = 'conductor' ORDER BY id DESC LIMIT 5;"`
   — A9 notification routing emits a `critical`/`high` for env/auth
   errors vs. actionable findings.
3. `sqlite3 ~/wing/app/data/wing.db "SELECT type, ts, result_json FROM
   events WHERE source = 'conductor' ORDER BY id DESC LIMIT 10;"` —
   timestamps + result blobs for the most recent run.
4. Check Wing OpenAPI in the browser (`https://wing.<tld>/agents`) for
   the AgentKit-side view of the same run.

Common causes:

| Symptom | Likely cause | Fix |
|---|---|---|
| Pre-flight: pulse_jobs row not found | Plugin loader didn't register the conductor job | Re-run `--tags anatomy.plugins,post_compose` |
| Pre-flight: Bone returns 5xx | Bone daemon down or wedged | `launchctl bootout gui/$(id -u)/eu.thisisait.nos.bone && launchctl bootstrap …` |
| Pre-flight: Authentik unreachable | DNS / Tailscale split-horizon | `nslookup auth.<tld>` from the host |
| Ceremony exit 2 — env error | `WING_EVENTS_HMAC_SECRET` empty | re-run playbook; the Wing plist export pulls from `bone_secret` |
| Ceremony exit 1 — claude exits non-zero | Conductor reported actionable findings | Open Wing /inbox; the A9 notification routing surfaced the details |

## Anatomy gates pinned

`tests/anatomy/test_phase5_ceremony.py`:

- Script is present + executable + bash-lint-clean.
- Pre-flight probes Bone /api/health + pulse_jobs row + dep guards.
- Env resolution reads `env_json` from `pulse_jobs`, exports vars,
  overrides `PULSE_RUN_ID=phase5-manual-…`.
- Post-flight queries `wing.db` for conductor events + notifications +
  the run's `actor_action_id`.
- Markdown report has `## Pre-flight / Post-flight / Verdict`; GREEN
  predicate is `event_delta ≥ 2`.
- `--dry-run` flag exists.
- Empty-args bash regression (`${arr[@]+...}` under `set -u`) pinned.
