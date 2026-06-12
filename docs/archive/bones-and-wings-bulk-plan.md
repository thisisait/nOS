# Bones & Wings bulk implementation plan

> Coordination plan for parallel agentic implementation of the
> remaining anatomy phases. Authoritative status pointer:
> [`docs/active-work.md`](active-work.md). Architecture + phase
> tracker: [`docs/bones-and-wings-refactor.md`](bones-and-wings-refactor.md).
>
> **Current state (2026-05-05):** Lanes A (A3.5 Wing host-revert) and D
> (A6.5 Grafana thin-role pilot) shipped and are deleted from this
> plan — see git history for the original lane specs. Track Q (Q1+Q2)
> + D-series (central authentik retirement) + β1 (SSO trichotomy)
> shipped post-Lane-D. **Forward lanes:** B (Pulse Wing API), C (A5
> contracts), E (A7 gitleaks), F (A8 conductor), G (A9 notifications),
> H (A10 audit). Worker doctrine: [`docs/multi-agent-batch.md`](multi-agent-batch.md).

---

## 0. Pre-launch gate

Before spawning workers:

- `python3 tools/aggregator-dry-run.py` exits 0.
- `python3 -m pytest tests/anatomy tests/callback -q` green.
- `ansible-playbook main.yml --syntax-check` clean.
- Operator's last full blank passed (or explicit waiver).

Push pending commits if depth > 30 — keeps each worker close to origin.

---

## 1. Parallelization rules

### Hard rules

- **One agent owns one surface** — no parallel edits to the same file set.
- **Worker prompts use relative paths only** (per `docs/multi-agent-batch.md`)
  — absolute paths bypass git worktree isolation.
- **No A8 production loop before A5 contracts** — conductor needs
  reliable schemas.
- **No A7 plugin scheduling before Lane B (Pulse Wing API)** — Pulse
  can idle but real jobs need endpoints.
- Docs update with every lane: `docs/active-work.md` punch-list +
  `docs/bones-and-wings-refactor.md` Appendix B.

### Shared lock files (one editor at a time)

`main.yml` · `tasks/stacks/core-up.yml` · `tasks/stacks/stack-up.yml` ·
`tasks/blank-reset.yml` · `default.config.yml` · `default.credentials.yml` ·
`state/manifest.yml` · `CLAUDE.md` · `docs/active-work.md` ·
`docs/bones-and-wings-refactor.md` · `files/anatomy/module_utils/load_plugins.py`.

---

## 2. Forward lanes

### Lane B — Pulse Wing API endpoints (P0.2 carryover)

**Owner:** one Wing/PHP agent.
**Goal:** Pulse can poll due jobs and record runs through Wing API
(today: 404s on every poll, idle-tolerated).

**Files:**
- `files/anatomy/wing/app/Presenters/Api/PulsePresenter.php` (new)
- `files/anatomy/wing/app/Model/PulseJobsRepository.php` (new)
- `files/anatomy/wing/app/Model/PulseRunsRepository.php` (new)
- `files/anatomy/wing/app/Core/RouterFactory.php` (route registration)
- `files/anatomy/wing/db/schema-extensions.sql` (tables already exist
  per `schema-extensions.sql:176-218`, just verify)

**Endpoints:**
- `GET /api/v1/pulse_jobs/due`
- `POST /api/v1/pulse_jobs` (idempotent plugin registration)
- `POST /api/v1/pulse_runs/start`
- `POST /api/v1/pulse_runs/finish`

**Exit checks:** Pulse polls without 404; start/finish round-trip in
`wing.db`; bearer-token auth matches existing presenter style.

---

### Lane C — A5 contracts (OpenAPI + DDL drift gate)

**Owner:** one agent. Can run after Lane B for final regen.
**Goal:** committed machine-readable contracts for plugins/agents +
CI drift gate.

**Files:**
- `files/anatomy/wing/bin/export-openapi.php` (extend)
- `files/anatomy/wing/bin/export-schema.php` (verify)
- `files/anatomy/skills/contracts/{wing,bone}.openapi.yml`
- `files/anatomy/skills/contracts/wing.db-schema.sql`

**Deliverables:**
- `--check-summaries` mode flips from advisory (P0.4) to error.
- Bone OpenAPI from FastAPI `/openapi.json`.
- `contracts-drift` CI job fails on uncommitted regen diff.

**Exit checks:** generated files deterministic; drift gate red on
synthetic API change; green after regen.

---

### Lane E — A7 gitleaks plugin (first scheduled-job consumer)

**Owner:** one agent after B + C land.
**Goal:** first real `skill + scheduled-job + ui-extension + notifier`
plugin via the loader.

**Files:**
- `files/anatomy/plugins/gitleaks/{plugin.yml,skills/run-gitleaks.sh}`
- `files/anatomy/wing/app/Presenters/Plugins/GitleaksPresenter.php`
- `files/anatomy/wing/app/templates/Plugins/Gitleaks/default.latte`
- `files/anatomy/wing/db/schema-extensions.sql` (`gitleaks_findings` table)
- `files/anatomy/plugins/gitleaks/provisioning/dashboards/gitleaks.json`
- `files/anatomy/plugins/gitleaks/notifications/{ntfy.txt,inbox.html}`

**Deliverables:** Plugin schedules a scan via Pulse; output normalized
to JSON; findings land in `gitleaks_findings`; Wing `/plugins/gitleaks`
renders results; ntfy + Wing inbox notify on critical finding; GDPR
seed row.

**Exit checks:** `ansible-playbook --tags anatomy.plugins` registers
the job; manual trigger creates findings; UI route renders; one
high-severity finding fires the notification fanout end-to-end.

---

### Lane F — A8 conductor + agent runner

**Owner:** one agent after Lane C contracts stable.
**Goal:** first agentic loop — scheduled check, drift report,
approval-gated apply.

**Files:**
- `files/anatomy/agents/conductor/{profile.yml,system_prompt.md}`
- `files/anatomy/scripts/pulse-run-agent.sh` (token mint → exec
  claude → POST /events)
- `files/anatomy/pulse/pulse/agent_runner.py` (extend Pulse runner
  with `runner: agent`)
- Wing `/inbox` + `/approvals` presenters + Latte views

**Deliverables:** Conductor agent profile registered with Authentik
(Track B client_credentials); Pulse runner exec's claude with prompt
+ contracts; outputs land in Wing `/inbox`; approval object can be
created/consumed; guardrails block unapproved apply.

**Exit checks:** Dry-run conductor reports drift without applying;
operator approval flips one queued action through Bone, not direct
shell from Wing/Pulse.

---

### Lane G — A9 notifications

**Owner:** one agent after Lane E inbox shape exists.
**Goal:** route high/critical plugin/agent events to Wing inbox + ntfy
+ mail (Mailpit dev / SMTP prod).

**Files:**
- `files/anatomy/wing/app/Service/Notifications/Dispatcher.php` (new)
- per-plugin `notifications/*.{txt,ntfy}` templates
- ntfy + mail integration code
- severity-routing tests

**Deliverables:** unified notification model; severity → channel
routing; Latte template rendering; ntfy + mail delivery with
local-safe defaults.

**Exit checks:** synthetic critical event reaches Wing inbox + ntfy;
mail path works behind Mailpit; medium/low events do not spam external
channels.

---

### Lane H — A10 audit trail (per-actor identity)

**Owner:** one agent after Lane E + F data models settle.
**Goal:** every wing.db write attributes the actor (operator, plugin,
or agent).

**Files:**
- `files/anatomy/wing/db/schema-extensions.sql` (migration: `actor_id`
  FK authentik_clients + `actor_action_id` UUID + `acted_at`)
- All `app/Model/*Repository.php` write paths
- Authentik blueprint additions for plugin/agent clients
- Wing `/audit` presenter + Latte view

**Deliverables:** schema migration; request actor extraction from
token/UI context; `/audit` filters by actor + data category + time
range; plugin/agent writes use distinct actors.

**Exit checks:** representative writes from operator + Pulse +
gitleaks + conductor are attributable; GDPR Article 30 view consumes
plugin/agent metadata; no write path silently drops actor data.

---

## 3. Execution waves

### Wave 1 — runtime + contracts foundation
- Lane B (Pulse API) → Lane C (A5 contracts regen)
- Merge order: B → C; Lane C re-runs after B lands so Pulse endpoints
  are in the contract.

### Wave 2 — first real plugin + first real agent
- Parallel: Lane E (A7 gitleaks) + Lane F (A8 conductor)
- Shared dependency: B + C merged.

### Wave 3 — compliance + fanout
- Parallel: Lane G (A9 notifications) + Lane H (A10 audit)
- Merge gate: synthetic gitleaks critical finding traverses inbox →
  ntfy → mail; conductor's write is actor-attributed.

### Wave 4 — Phase 5 ceremony
- Operator gate (full blank + smoke + Wing tests + drift CI green).
- Pulse one-shot `conductor-self-test-001` job.
- Pass criteria: ≥1 row each in `pulse_runs`, `gitleaks_findings`,
  `audit`; events with `actor_id=conductor`. **First non-operator
  identity end-to-end write to wing.db.**

---

## 4. Minimum test matrix per merge

```bash
python3 tools/aggregator-dry-run.py            # must exit 0
python3 -m pytest tests/anatomy tests/callback -q
ansible-playbook main.yml --syntax-check
```

For runtime-affecting lanes, add:

```bash
ansible-playbook main.yml -K --tags wing,bone,pulse,anatomy
bash tools/post-blank.sh
```

For Wave 4 ceremony only: full `ansible-playbook main.yml -K -e blank=true`.

---

## 5. Worker prompt template

Per `docs/multi-agent-batch.md` doctrine. Worker MUST:

1. Open with **relative paths only** (not `/Users/.../nOS/...`) — git
   worktree isolation is filesystem-isolated, not namespace-isolated.
2. Pre-flight: `pwd` + `git worktree list` to verify isolation.
3. Edit `docs/active-work.md` punch-list + `docs/bones-and-wings-refactor.md`
   Appendix B as part of the lane commit.
4. End with exact verification commands + results.

---

## 6. PoC definition of done

- Wing runs via FrankenPHP launchd ✅ (A3.5 done).
- Bone runs via Python launchd ✅ (A3a done).
- Pulse executes ≥ 1 registered non-agentic job (Lane B + E gate).
- OpenAPI + DDL contracts committed + drift-checked (Lane C gate).
- `grafana-base` proves thin-role doctrine ✅ (A6.5 done).
- `gitleaks` proves plugin scheduling + UI + GDPR (Lane E gate).
- `conductor` proves agentic scheduled work + approval gate (Lane F gate).
- Notifications reach inbox + ntfy + mail (Lane G gate).
- Audit trail attributes representative writes (Lane H gate).
- Full blank + Phase 5 ceremony ceremony pass.
