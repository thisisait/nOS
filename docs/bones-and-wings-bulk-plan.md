# Bones & Wings bulk implementation plan

> **Purpose:** coordination plan for a larger parallel agentic implementation batch after the current security-hardening full-blank gate is green or explicitly waived by the operator.
>
> **Primary sources:** `docs/active-work.md` for the live gate, `docs/bones-and-wings-refactor.md` for architecture and phase tracker, `files/anatomy/docs/plugin-loader-spec.md` for plugin-loader contracts, and `files/anatomy/docs/role-thinning-recipe.md` for Track Q migrations.
>
> **Current state (2026-05-04 evening):** A0, A1, A2, A3a, **A3.5**, A4, A6 foundation, and **A6.5** have landed. **Track Q is now UNBLOCKED.** Next implementation is A5 (contracts), A7 (gitleaks), A8/A9/A10 in parallel with the Track Q sweep. **Tune-and-thin doctrine validated on 5 pilots** (Woodpecker / Qdrant / Portainer / Grafana / Vaultwarden) under `files/anatomy/plugins/<service>-base/`; Lane D's plugin loader side-effects (`render_compose_extension`, `bootstrap_collections`, `register_*`, `import_grafana_dashboard`) remain the gate. Track Q can start incrementally after Lane D, OR per-role as each one is touched (current pattern: every role ladene this batch got harvested into a draft).

---

## 0. Gate before starting the bulk job

Do not start code changes until one of these is true:

- **Preferred:** operator runs full blank + post-blank wet tests and they are green.
- **Explicit waiver:** operator says to proceed despite the gate.

Gate commands from `docs/active-work.md`:

```bash
ansible-playbook main.yml -K -e blank=true
bash tools/post-blank.sh
```

Expected pre-bulk baseline:

- Full blank succeeds.
- Wet tests are green.
- `tests/anatomy tests/wet tests/apps -q` remains green.
- `ansible-lint` remains green.
- `docs/active-work.md` is updated with the fresh result.

---

## 1. Parallelization rules

### Hard rules

- **One agent owns one surface.** Avoid multiple agents editing the same file set.
- **No Track Q before A6.5.** Thin-role mass migration is blocked until Grafana proves the doctrine.
- **No A8 production agent loop before A5 contracts.** Conductor needs reliable API/schema contracts.
- **No A7 scheduled plugin before Wing Pulse API exists.** Pulse can idle, but real jobs need Wing endpoints.
- **Docs must be updated with every phase.** `docs/active-work.md` and `docs/bones-and-wings-refactor.md` Appendix B are the state handoff.

### Shared files requiring lock discipline

Only one agent at a time should edit these:

- `main.yml`
- `tasks/stacks/core-up.yml`
- `tasks/stacks/stack-up.yml`
- `tasks/blank-reset.yml`
- `default.config.yml`
- `default.credentials.yml`
- `state/manifest.yml`
- `CLAUDE.md`
- `docs/active-work.md`
- `docs/bones-and-wings-refactor.md`

### Recommended branch/commit shape

Use one branch for the bulk batch, but one logical commit per phase/surface:

- `feat(anatomy): run wing via frankenphp launchd (A3.5)`
- `feat(wing): expose pulse job API (A4/A7 prerequisite)`
- `feat(anatomy): export wing and bone contracts (A5)`
- `feat(anatomy): make grafana-base plugin real (A6.5)`
- `feat(anatomy): add gitleaks plugin (A7)`
- `feat(anatomy): add conductor runner and inbox flow (A8)`
- `feat(anatomy): add notification fanout (A9)`
- `feat(anatomy): add actor audit trail (A10)`
- `docs(anatomy): refresh bulk status handoff`

---

## 2. Agent lanes

## Lane A — A3.5 Wing host-revert via FrankenPHP — ✅ DONE 2026-05-04

**Status:** landed in a single commit. Wing now runs as
`eu.thisisait.nos.wing` launchd daemon backed by FrankenPHP (PHP 8.5 +
Caddy 2.x in one binary). The wing FPM container + wing-nginx sidecar
are reversed (Track-A teardown). Traefik file-provider auto-derives
`wing.<tld>` → `http://nos-host:9000` via the same uniform code path as
every other host-mode service. The wing-nginx stale-IP 502 bug class is
structurally closed — no sidecar = no Docker DNS cache to go stale.

**Owner:** one agent only.

**Goal (achieved):** remove Wing container/FPM + nginx sidecar and run Wing as host FrankenPHP launchd service on `127.0.0.1:9000`.

**Primary files:**

- `roles/pazny.wing/`
- `files/anatomy/wing/`
- `state/manifest.yml`
- Traefik dynamic service inputs if needed
- launchd plist template for Wing
- blank-reset cleanup paths

**Deliverables:**

- `frankenphp` installed by Homebrew role or Wing role requirements.
- `roles/pazny.wing` creates runtime dirs, syncs source, runs composer, initializes DB, reconverges token.
- launchd plist `eu.thisisait.nos.wing` runs FrankenPHP from `~/wing/app`.
- legacy `wing`/`wing-nginx` containers and compose override are stopped/removed idempotently.
- Traefik routes `wing.<tld>` to host port `9000`.
- Logs are tailed by existing observability or a documented TODO is left for A6.5/Q1.

**Exit checks:**

- `wing.<tld>` returns expected authenticated UI path.
- `/api/v1/*` endpoints still work with Bearer token.
- `bin/init-db.php`, `bin/migrate.php`, and token provisioning still work.
- Blank reset is idempotent.

**Risks:** PHP extension drift, FrankenPHP command syntax, path assumptions from FPM/nginx sidecar.

---

## Lane B — Wing Pulse API + first non-agentic job prerequisites

**Owner:** one Wing/PHP-focused agent. Can start after or alongside A3.5 if it avoids role files.

**Goal:** make Pulse able to poll and record runs through Wing API.

**Primary files:**

- `files/anatomy/wing/app/Presenters/Api/`
- `files/anatomy/wing/app/Model/`
- `files/anatomy/wing/app/Core/RouterFactory.php`
- `files/anatomy/wing/db/schema-extensions.sql`
- `files/anatomy/pulse/pulse/wing_client.py` only if contract changes are needed

**Endpoints:**

- `GET /api/v1/pulse_jobs/due`
- `POST /api/v1/pulse_jobs` for idempotent plugin registration
- `POST /api/v1/pulse_runs/start`
- `POST /api/v1/pulse_runs/finish`

**Deliverables:**

- Repository for `pulse_jobs` and `pulse_runs`.
- Due-job calculation using materialized `next_fire_at` or a simple first implementation compatible with current schema.
- Pause flag honored.
- Run start/finish writes are idempotent enough for retries.
- Bearer-token auth path matches existing Wing API style.

**Exit checks:**

- Pulse can poll without 404/302.
- Posting start/finish creates/updates rows in wing.db.
- Empty job set returns `[]`.
- Invalid job payloads return 4xx, not 500.

---

## Lane C — A5 contracts: OpenAPI + DB schema exports

**Owner:** one agent. Can work in parallel after Wing runtime shape is stable enough to run scripts.

**Goal:** commit machine-readable contracts for agents and plugins.

**Primary files:**

- `files/anatomy/wing/bin/export-openapi.php`
- `files/anatomy/wing/bin/export-schema.php`
- `files/anatomy/skills/contracts/wing.openapi.yml`
- `files/anatomy/skills/contracts/bone.openapi.yml`
- `files/anatomy/skills/contracts/wing.db-schema.sql`
- test/CI drift check files

**Deliverables:**

- Wing OpenAPI export from router/presenter metadata or a deterministic manually curated exporter.
- Bone OpenAPI artifact generated from FastAPI `/openapi.json` or direct app import.
- wing.db schema export generated from initialized DB.
- Drift test that fails when exports differ from committed artifacts.

**Exit checks:**

- Generated files are deterministic.
- CI/local test can regenerate and diff cleanly.
- Contracts include Pulse endpoints once Lane B lands.

---

## Lane D — A6.5 Grafana thin-role pilot + real plugin side effects — ✅ DONE 2026-05-04

**Status:** landed. Plugin loader actions (`render`, `render_compose_extension`,
`copy_dashboards`, `wait_health`, `conditional_remove_dir`) implemented with
Jinja2 backing. Manifest dotted-path resolver walks `provisioning.datasources`-
style refs into the plugin manifest's nested dict. `nos_plugin_loader` Ansible
module wrapper accepts `template_vars: "{{ vars }}"` and threads it through
to action params + plugin templates. Grafana role thinned: provisioning
artifacts moved into the plugin dir; OIDC env block + mkcert CA + plugin
install + extra_hosts authentik moved to a compose-extension template.
core-up.yml + observability.yml drop the obsoleted render/copy tasks.
7 new tests added (48/48 anatomy suite green). **Track Q is now unblocked
to proceed.**



**Owner:** one agent initially; split only after inventory is frozen.

**Status (2026-05-04):** `files/anatomy/plugins/grafana-base/plugin.yml`
draft promoted to **live-now map** — every block tagged with its
current pre-Q home (which file/stanza realizes it today). All wiring
already factored into the role compose env block + observability tasks
+ `authentik_oidc_apps`; Lane D narrows from "factor wiring out" to
"make plugin loader actually consume the manifest". Same pattern was
validated on 4 sibling drafts in this session
(woodpecker-base, qdrant-base, portainer-base, vaultwarden-base) so
the manifest schema is stable across all 5 plugin shapes before Lane D
implementation starts.

**Goal:** prove tendons/vessels doctrine by thinning `pazny.grafana` and making `grafana-base` perform real autowiring.

**Primary files:**

- `roles/pazny.grafana/`
- `files/anatomy/plugins/grafana-base/`
- `files/anatomy/module_utils/load_plugins.py`
- `files/anatomy/library/nos_plugin_loader.py`
- `files/anatomy/docs/grafana-wiring-inventory.md`
- `files/anatomy/docs/role-thinning-recipe.md`
- tests under `tests/anatomy/`

**Deliverables:**

- Loader implements real `render`, `render_compose_extension`, `copy_dashboards`, and `wait_health` actions.
- `grafana-base` has actual templates/provisioning files, not only draft manifest.
- `pazny.grafana` keeps only install-internal responsibilities.
- Existing Grafana dashboards, datasources, OIDC, alerts, and scrape behavior are preserved.

**Exit checks:**

- Fresh blank with thinned Grafana is functionally equivalent.
- Grafana OIDC works.
- Dashboards and datasources are present.
- Tests cover plugin render/copy/wait behavior.
- `role-thinning-recipe.md` is revised with real edge cases.

**Blocker:** Track Q cannot start until this exits green.

---

## Lane E — A7 gitleaks plugin

**Owner:** one agent after Lane B and the necessary A6.5 loader side effects exist.

**Goal:** first real skill/scheduled-job/ui plugin.

**Primary files:**

- `files/anatomy/plugins/gitleaks/`
- Wing plugin presenter/view files
- Wing schema extension for findings
- Grafana dashboard if in scope
- notification templates
- Pulse job registration path

**Deliverables:**

- `plugin.yml` with `skill`, `scheduled-job`, `ui-extension`, `notification`, `gdpr`, and `schema` blocks.
- `skills/run-gitleaks.sh` normalizes output JSON.
- Wing API endpoint for findings.
- Wing UI route `/plugins/gitleaks`.
- Pulse job registration via plugin loader.

**Exit checks:**

- `ansible-playbook --tags anatomy.plugins` registers the plugin.
- Manual run or `run_now=gitleaks` path creates findings.
- Wing UI shows findings.
- GDPR row exists.

---

## Lane F — A8 conductor + agent runner

**Owner:** one agent after A5 contracts and basic Pulse API are present.

**Goal:** first agentic loop: scheduled check, drift report, approval-gated apply.

**Primary files:**

- `files/anatomy/agents/conductor/`
- `files/anatomy/pulse/` agent runner code
- Wing `/inbox` and `/approvals` UI/API
- Bone run-tag/check-mode integration if needed

**Deliverables:**

- `profile.yml` for conductor.
- prompt/system instructions.
- Pulse runner supports `runner: agent`.
- Token/context assembly from contracts.
- Wing inbox stores drift reports and pending approvals.
- Approval-gated apply uses Bone, not shelling directly from Wing/Pulse.

**Exit checks:**

- Dry-run conductor reports drift without applying.
- Approval object can be created and consumed.
- Guardrails prevent unapproved apply.
- Logs redact tokens.

---

## Lane G — A9 notifications

**Owner:** one agent after inbox shape exists.

**Goal:** route high/critical plugin/agent events to Wing inbox, ntfy, and mail.

**Primary files:**

- Wing notification dispatcher implementation
- plugin notification templates
- ntfy/mail integration files
- tests for severity routing

**Deliverables:**

- Unified notification model.
- Severity-to-channel routing.
- Template rendering.
- ntfy and mail delivery with local-safe defaults.

**Exit checks:**

- Synthetic critical event reaches Wing inbox and ntfy.
- Mail path works where SMTP/Mailpit/Stalwart is enabled.
- Medium/low events do not spam external channels.

---

## Lane H — A10 audit trail + per-actor identity

**Owner:** one agent, likely after A7/A8 data models settle.

**Goal:** make the compliance promise real: every wing.db write has actor attribution.

**Primary files:**

- Wing DB schema migrations/extensions
- Wing repositories write paths
- Authentik client mappings for agents/plugins
- Wing `/audit` view/API
- GDPR aggregation

**Deliverables:**

- `actor_id`, `actor_action_id`, `acted_at` on write tables.
- Request actor extraction from token/UI context.
- `/audit` filters by actor, data category, and time range.
- Plugin/agent writes use distinct actors.

**Exit checks:**

- Representative writes from operator, Pulse, gitleaks, and conductor are attributable.
- GDPR Article 30 view uses plugin/agent metadata.
- No write path silently drops actor data.

---

## 3. Recommended execution waves

### Wave 0 — gate + docs freeze

- Run full blank and wet tests.
- Refresh `docs/active-work.md` with real result.
- Declare ownership of lanes.

### Wave 1 — runtime and contracts foundation

Parallel lanes:

- Lane A: A3.5 Wing FrankenPHP runtime.
- Lane B: Wing Pulse API.
- Lane C: A5 contract exporters, with final contract regeneration after Lane B merges.

Merge order:

1. A3.5
2. Pulse API
3. A5 contracts regenerated with final API surface

### Wave 2 — plugin doctrine proof

Primary lane:

- Lane D: A6.5 Grafana thin-role pilot.

Optional support:

- A second agent may write tests/docs for loader side effects after the first agent locks expected behavior.

Merge gate:

- Functional Grafana parity on blank.
- Updated `role-thinning-recipe.md`.

### Wave 3 — first real plugin and first real agent

Parallel lanes after Wave 2:

- Lane E: A7 gitleaks plugin.
- Lane F: A8 conductor runner and inbox/approvals.

Shared dependency:

- Both need stable contracts and Pulse API.

### Wave 4 — compliance and fanout

Parallel lanes after basic plugin/agent data flows exist:

- Lane G: A9 notifications.
- Lane H: A10 audit trail.

Merge gate:

- End-to-end gitleaks critical finding appears in inbox/ntfy/mail.
- Conductor write path is actor-attributed.

### Wave 5 — Track Q kickoff

Only after A6.5 exits green:

- Start Q1 observability: Grafana already done, then Prometheus, Loki, Tempo, Alloy.
- Do not start Q2 IAM until Q1 proves source/consumer composition patterns.

---

## 4. Minimum test matrix per merge

Run the smallest relevant set before each lane merge:

```bash
python3 -m pytest tests/anatomy -q
python3 -m pytest tests/apps -q
ansible-playbook main.yml --syntax-check
```

For runtime-affecting lanes, add:

```bash
ansible-playbook main.yml -K --tags wing,bone,pulse,anatomy
bash tools/post-blank.sh
```

For final wave gates, run full blank:

```bash
ansible-playbook main.yml -K -e blank=true
bash tools/post-blank.sh
```

---

## 5. Bulk-job handoff checklist

Before launching agents, paste each lane owner this checklist:

- Read `docs/active-work.md`.
- Read `docs/bones-and-wings-refactor.md` §1.1, §3, §6, §8, Appendix B.
- Read this file and claim exactly one lane.
- Do not edit shared lock files without coordination.
- Update tests with implementation.
- Update `docs/active-work.md` and Appendix B when your lane changes status.
- End with exact verification commands and results.

---

## 6. Definition of done for the whole PoC

- Wing runs via FrankenPHP launchd.
- Bone runs via Python launchd.
- Pulse runs via Python launchd and executes at least one registered non-agentic job.
- Wing/Bone/OpenAPI/DDL contracts are committed and drift-checked.
- `grafana-base` proves thin-role doctrine.
- `gitleaks` proves plugin scheduling + UI + GDPR path.
- `conductor` proves agentic scheduled work + approval gate.
- Notifications reach Wing inbox and configured push/mail channels.
- Audit trail attributes representative writes by actor.
- Full blank + wet tests pass.
