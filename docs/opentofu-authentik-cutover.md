# OpenTofu Authentik cutover runbook (ADR-0001 Phase 1)

How to move the Authentik consumer from the imperative blueprint engine
(`ak apply_blueprint`) to OpenTofu authority — **safely, reversibly, gated on a
proven no-op plan.** Read [ADR-0001](adr/0001-opentofu-for-autowiring.md) first.

## The two switches

| Var | Default | Meaning |
|---|---|---|
| `manage_authentik_with_tofu` | `false` | Opt-in: run the OpenTofu task at all (Phase 0 drift detector + Phase 1 apply). |
| `authentik_engine` | `"blueprint"` | Authority: `blueprint` = `ak apply_blueprint` is the source of truth (OpenTofu is plan-only/advisory). `tofu` = OpenTofu applies; the imperative blueprint reapply + the MTI footgun handler are **skipped**. |

Phase 0 = `manage_authentik_with_tofu: true`, `authentik_engine: blueprint`
(drift detector). Phase 1 cutover = flip `authentik_engine: tofu` — **only after
the whole tenant is authored + imported and `tofu plan` is no-op.**

## The safety rail: the destroy guard

`tasks/tofu-authentik.yml` parses `tofu show -json tfplan` and **refuses to
apply if the plan contains ANY delete action.** The danger it blocks: importing
the full tenant into state but authoring HCL for only some services makes the
un-authored ones plan as destroys → catastrophic SSO outage. The guard makes
the engine flip a no-op-or-nothing operation. You cannot accidentally nuke
providers.

## Cutover procedure

1. **Adopt the whole tenant** (one-time, SAFE — import + plan only, never applies):
   ```bash
   tools/tofu-authentik-adopt.sh --plan
   ```
   This enumerates every live proxy/oauth2 provider + application (live count:
   ~22 proxy + ~50 oauth2 + ~50 apps), writes `import {}` blocks, and runs
   `tofu plan -generate-config-out=generated.tf` to bootstrap HCL from live
   state. Both files are gitignored until reviewed.

2. **Refactor + reconcile to no-op.** Review `generated.tf`; move flat resources
   toward `module "nos-authentik-app"` calls where they fit (keep raw HCL for
   the exotic). Iterate `tofu plan` until it reads **0 to add, 0 to change, 0 to
   destroy**. The usual deltas (learned in Phase 0): `access_token_validity` /
   `access_code_validity` timings, `redirect_uri_type: authorization` on oauth2
   redirect URIs, `internal_host_ssl_validation` on proxies, and the tier RBAC
   `policy_binding`s (20-rbac-policies uses expression policies — model or
   accept a one-time normalizing change). Outpost-provider attachment import id
   format is an open mechanics item — see Known gaps.

3. **Custody the secret-bearing artifacts** BEFORE flipping: `nos.auto.tfvars.json`
   and `terraform.tfstate` are `0600`, gitignored, and must join Infisical
   custody + the 3-2-1 backup set + a `restore-verify` floor.

4. **Flip authority** (reversible):
   ```bash
   # config.yml:  authentik_engine: "tofu"
   ansible-playbook main.yml --tags tofu-authentik \
     -e manage_authentik_with_tofu=true
   ```
   The task plans, runs the destroy guard, and applies **only if zero destroys**.
   The imperative `Reapply authentik blueprints` + `Reconcile providers` handlers
   are now skipped (gated on `authentik_engine != 'tofu'`).

5. **Verify** the live tenant: SSO login on a forward_auth service (infisical)
   and a native_oidc service (grafana); `tofu plan` reads no-op.

6. **Drift job:** a read-only `tofu plan` Pulse job → W6.1 "Authentik drifted"
   notification (wire after the flip).

## Rollback

Flip `authentik_engine` back to `"blueprint"` and re-run — the imperative
blueprint reapply + MTI reconcile handlers re-engage. The blueprint render
(`10-oidc-apps.yaml`) is kept for at least one release; do not delete the
renderer until the tofu engine has held no-op across several converges.

## Known gaps (do not flip until closed)

- **Outpost-provider attachment import id format** is unconfirmed — Phase 0
  imported the proxy/oauth2/app cleanly but not the `outpost_provider_attachment`
  (it shows as `1 to add`). Either crack the import id, or manage the embedded
  outpost's provider list via a single `authentik_outpost` resource instead of
  per-service attachments (pick ONE — both fighting over the list is drift).
- **Tier RBAC expression policies** (20-rbac-policies) are not yet modeled in
  HCL; reaching no-op on them needs either modeling or a one-time normalize.
- **Agents** (oauth2 client_credentials clients, no app/outpost) are a distinct
  shape; author them as bare `authentik_provider_oauth2` (no module).
- **Tier-2 apps** authentik wiring: thin `authentik:` stanza in `apps/<name>.yml`
  → module instantiation render (ADR-0001 §8), landing in the same TF root.

Until these are closed and `tofu plan` is no-op across the full tenant, leave
`authentik_engine: "blueprint"`. The destroy guard enforces this — apply refuses
while any destroy remains.
