# nOS SSO + identity attribution — doctrine + audit

> **Status:** doctrine locked 2026-05-17 by `tests/anatomy/test_sso_doctrine.py` (7 gates).
> **Companion docs:** [native-sso-survey.md](native-sso-survey.md) (per-service verdicts), [bones-and-wings-refactor.md §11](bones-and-wings-refactor.md) (audit-trail spec).

## Mode trichotomy (post-β1.A)

Every Authentik-wired service falls into exactly one of three buckets,
declared in its plugin manifest as `authentik.mode` (and pinned by the
[`test_every_plugin_uses_canonical_authentik_mode`](../tests/anatomy/test_sso_doctrine.py)
anatomy gate):

| Mode | Meaning | Operator UX | Live probe (unauth GET /) |
|---|---|---|---|
| **`native_oidc`** | Service consumes OIDC at app level — has its own login UI surface with "Sign in with Authentik" button. Per-user identity flows into the service. | One extra click on the service login page | 200 (own login) or 302 → self/login |
| **`header_oidc`** | Authentik proxy outpost forwards `X-Authentik-Username` / `X-Authentik-Email` headers; service auto-creates the local user from headers. True SSO. | No extra click | 302 → auth.{tld} |
| **`forward_auth`** | Pure access gate — Authentik session means "you're in"; service has no per-user state. | No extra click | 302 → auth.{tld} |
| (`none`) | Substrate / no-SSO service (PostgreSQL, MariaDB, Redis, etc.) | n/a | n/a |

**Anti-canon (caught by gate):** `oauth2`, `proxy_auth`, missing mode.
The blueprint's default-expression chain used to accept all of them
silently — pre-2026-05-17 cleanup. Now `mode:` and `provider_type:` MUST
be one of the canonical four.

## Live state (2026-05-17 audit)

20 services declare an Authentik client; **all 17 currently installed
return the expected response shape for their mode**:

```
forward_auth: kiwix · mail · bi · paperclip · os(puter) · uptime · wing
              all → HTTP 302 → auth.pazny.eu ✓
native_oidc:  helpdesk · git · grafana · vault · n8n · cloud · wiki ·
              portainer · superset · pass
              all → HTTP 200 (own UI) or 302 → self/login ✓
```

## Identity attribution chain (A10)

Every wing.db write that records agent / plugin / operator action must
be attributable. The chain has **three layers**:

### Layer 1 — Authentik mints the identity

- Operators authenticate via the OIDC flow → Authentik issues a session.
- Forward-auth services see `X-Authentik-Username` / `X-Authentik-Groups`
  on every request (Traefik middleware injects from the outpost).
- Agents authenticate via `client_credentials` → JWT bearer with
  `name = <client_id>` (e.g. `nos-conductor`, `nos-remediator`).

### Layer 2 — Wing API stamps actor_id from the token

`BaseApiPresenter::getActorId()` reads `$validatedToken['name']` — the
**cryptographically-verified** identity. Privileged write endpoints
(`AgentsPresenter::actionStart`, `GitleaksPresenter::actionResolve`,
`RemediationPresenter::actionBulkStatus`, etc.) MUST use this rather
than reading attribution from the request body. Anatomy gate
[`test_no_body_supplied_attribution_anti_pattern`](../tests/anatomy/test_sso_doctrine.py)
sweeps every presenter for the `$body['resolved_by']` / `$body['created_by']` /
`$body['approved_by']` / `$body['reported_by']` anti-pattern.

**Live incident (2026-05-17):** the audit surfaced two endpoints
silently trusting body attribution:

- `GitleaksPresenter::actionResolve` — pulled `$body['resolved_by']`
- `RemediationPresenter::actionBulkStatus` — same

Either could let an LLM agent write `resolved_by: 'operator'` and the
audit trail would believe it. Both fixed in the same commit; gate now
prevents recurrence.

### Layer 3 — wing.db rows carry actor_id

The **four attribution-backbone tables** carry `actor_id` directly
(`text` column, nullable for pre-A10 rows):

| Table | Source | Coverage |
|---|---|---|
| `events` | Bone POST `/api/v1/events` (callback plugin, agent runners, presenter writes) | actor_id supplied by emitter via payload OR derived from bearer token |
| `pulse_runs` | Pulse subprocess fires (start + finish) | Pulse-side env var |
| `notifications` | Bone POST `/api/v1/notifications` | actor_id from payload (agents + plugins) |
| `agent_sessions` | AgentKit runner | `agent:<name>` derived from agent profile |

**Indirect attribution** (other "domain" tables) link to the backbone
via foreign keys:

| Domain table | Link | Reverse lookup |
|---|---|---|
| `gitleaks_findings` | `scan_id` → `pulse_runs.run_id` | who ran the scan |
| `gitleaks_findings.resolved_by` | direct text field | who resolved it (post-fix: only from bearer token) |
| `remediation_items.resolved_by` | direct text field | who resolved it (post-fix: only from bearer token) |
| `migrations_applied.event_run_id` | → `events.run_id` | who initiated the migration |
| `upgrades_applied.event_run_id` | → `events.run_id` | who initiated the upgrade |
| `patches_applied.event_run_id` | → `events.run_id` | who applied the patch |

Direct columns are sturdier than soft FKs but more invasive to add.
Today's policy: backbone tables MUST have `actor_id`; domain tables MAY
add `<verb>_by` columns for high-traffic events (resolve, approve);
all other attribution flows via the soft-FK chain to events/pulse_runs.

## Agent runner contract

`pulse-run-agent.sh` is the canonical pattern for any agentic LLM run.
Its identity flow:

1. **Mint Authentik token** via `client_credentials` grant (the agent's
   `nos-<name>` client_id + secret from default.credentials.yml).
2. **Generate `actor_action_id`** — UUID4 grouping every event emitted
   by this single run.
3. **POST `agent_run_start`** event with HMAC + sorted-keys JSON body
   carrying `source: <agent_name>`, `actor_id: <client_id>`,
   `actor_action_id: <uuid>`.
4. **Exec `claude`** with the agent's profile + the Authentik token in
   `NOS_AUTHENTIK_TOKEN`. Claude's own tool calls inherit the token →
   every Wing/Bone hit from within the agent carries the same
   actor_id.
5. **POST `agent_run_end`** event with same `actor_action_id` → start +
   end + everything between → one `SELECT WHERE actor_action_id=?`
   reconstructs the entire run.
6. **POST `/api/v1/notifications`** on non-zero exit, also under the
   same `actor_action_id` → audit trail includes the operator-facing
   page.

The agent profile MUST have a matching `nos-<name>` row in
`default.config.yml::authentik_agent_clients` (anatomy gate
[`test_agent_clients_in_authentik_blueprint_register_all_runners`](../tests/anatomy/test_sso_doctrine.py)
catches future remediator-class registration gaps).

## What "bulletproof identity for agentic access" means here

1. **No plaintext attribution acceptance** — Wing API never trusts a
   body-supplied actor_id / resolved_by / approved_by. Always the
   bearer-validated identity. Anti-pattern gate enforces.
2. **Every write reachable via one query** — `SELECT * FROM events
   WHERE actor_action_id = ?` returns the entire lineage of one run.
   Domain tables that don't carry actor_id link via soft FK.
3. **Canonical mode trichotomy** — operators + auditors know exactly
   what to expect from each service (own login UI vs proxy redirect).
   Non-canonical mode labels rejected at gate-time.
4. **nos-<slug> client_id convention** — every Authentik client uses
   the same shape; log line `actor=nos-conductor` resolves to exactly
   one client row in Authentik + one row in `authentik_agent_clients`.
   Gate enforces.

## What's NOT bulletproof yet (deferred)

- **Domain-table `actor_id` direct columns** — gitleaks_findings,
  remediation_items, pentest_findings still rely on soft-FK indirect
  attribution. Cheap fix is one ALTER per table + a `created_by =
  getActorId()` plumbing pass. Not blocking ops; nice to have.
- **Per-action signed log envelope** — A14 AgentKit has `actor_action_id`
  + trace_id (W3C). The audit trail is INTERNALLY consistent but doesn't
  sign rows. A future tamper-evident-log layer would HMAC each event row
  on insert.
- **Conductor / inspektor / scout agents not yet running on schedule** —
  remediator + conductor profile shipped; the others (inspektor, scout,
  librarian) have Authentik clients + capability scopes pre-provisioned
  but no Pulse jobs. They join the audit surface when their runners
  land.
