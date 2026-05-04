# authentik-base

> **Status:** live (Anatomy P0.3, 2026-05-04). The P0 blocker that unblocks
> all of Q2 (per-plugin `authentik:` blocks).

Wiring layer for Authentik — Identity Provider + SSO foundation for the
nOS stack. This is a **source plugin** (aggregator type): it harvests
`authentik:` blocks from every loaded peer plugin and merges them into
the OIDC blueprint render. Q2 migrates the central `authentik_oidc_apps`
list out of `default.config.yml` and into per-plugin manifests; until
that lands both sources feed `10-oidc-apps.yaml.j2`.

## What lives here

```
files/anatomy/plugins/authentik-base/
├── plugin.yml                       # manifest + aggregator + lifecycle
├── README.md                        # this file
└── blueprints/
    ├── 00-admin-groups.yaml.j2      # akadmin user, RBAC groups, nos-tester, nos-api token
    ├── 10-oidc-apps.yaml.j2         # OAuth2 + proxy providers + applications
    ├── 20-rbac-policies.yaml.j2     # tier-based expression policies + bindings
    └── 30-agent-clients.yaml.j2     # machine-to-machine OIDC clients (Bone, Pulse, conductor)
```

## Aggregator pattern

```yaml
aggregates:
  - from: consumer_block
    block_path: authentik
    output_var: clients
  - from: agent_profile
    block_path: authentik
    output_var: agent_clients
```

The plugin loader's `run_aggregators()` walks every loaded peer plugin
and copies any top-level `authentik:` block into this plugin's
`inputs.clients`. Agent profiles (A8 conductor / A7 gitleaks) feed
`inputs.agent_clients` analogously.

When the `pre_compose` hook fires `render_dir`, every `.j2` in
`blueprints/` is rendered with the operator's full var scope **plus**:

- `inputs.clients` — list of harvested service `authentik:` blocks
- `inputs.agent_clients` — list of harvested agent `authentik:` blocks
- `plugin_manifest` — this plugin's own manifest (rare)

## Co-existence with `roles/pazny.authentik/templates/blueprints/`

The role-side blueprints task (`roles/pazny.authentik/tasks/blueprints.yml`)
also renders these same four files into the same target dir
(`{{ stacks_dir }}/infra/authentik/blueprints`). The templates here
are byte-identical copies, so both sources produce the same output
(idempotent). Authentik's blueprint engine reconciles either way.

The role-side render gets removed in **Phase 2 C1** of the multi-agent
batch (after Q2 lands per-plugin `authentik:` blocks across 35 services
and the central `authentik_oidc_apps` list goes away). Until then this
plugin overlays without conflict.

## Required operator vars (from `default.config.yml`)

- `tenant_domain` (default `dev.local`)
- `authentik_default_groups` — RBAC groups list
- `authentik_bootstrap_password`, `authentik_bootstrap_email` — akadmin
- `authentik_oidc_apps` — central OIDC client list (deletes in Phase 2 C1)
- `authentik_rbac_tiers`, `authentik_app_tiers` — tier-based policy bindings
- `authentik_agent_clients`, `authentik_agent_scopes` — Track B agent OIDC
- `nos_tester_username`, `nos_tester_password` — Track G smoke identity

## GDPR

| Field | Value |
|---|---|
| Data categories | authentication_credentials, identity_metadata, session_tokens, audit_log_entries |
| Data subjects | operators, end_users, automated_systems |
| Legal basis | contract (auth contractually required for service access) |
| Retention | -1 (active accounts kept indefinitely; deletion via DSAR) |
| Processors | authentik |
| EU residency | true |

## Future work

- **Q2 migration**: replace `authentik_oidc_apps` iteration in
  `10-oidc-apps.yaml.j2` with `inputs.clients` iteration once 35
  consumer plugins declare their own `authentik:` blocks.
- **A8 conductor**: add conductor agent profile under
  `files/anatomy/agents/conductor.yml` with its own `authentik:` block;
  the agent_profile aggregator picks it up automatically.
- **A10 audit trail**: Authentik client_id becomes the `actor_id` FK
  for every wing.db write; this plugin will surface the
  client_id list to the audit-trail schema migration.
