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

## Blank-run cutover (the clean-slate path — recommended for the first test)

A `blank=true` run wipes the Authentik DB, so the tenant comes up **empty** —
no MTI-drifted providers, no orphans, nothing to import. OpenTofu then just
**creates** the full SSO graph (`98 add / 0 change / 0 destroy`, verified). This
is the safest cutover: there is nothing for the destroy guard to trip on.

The data-driven HCL is **ready**: `state/tofu-authentik-services.yml` (39
services, regenerated from the aggregated `authentik:` blocks by
`tools/tofu-authentik-gen-registry.py`) → tfvars → `for_each` module. A blank
with `authentik_engine: tofu` drops `10-oidc-apps` from the imperative loop
(the other six blueprints — groups/MFA/RBAC/agents/enrollment/brand — still
apply) and OpenTofu provisions providers+apps+outpost attachments.

**Two test paths — pick by appetite:**

### Path A (recommended): blueprint blank → prove tofu parity → flip
1. `ansible-playbook main.yml -e blank=true` (engine stays `blueprint`,
   default). Clean fresh tenant; validates the whole session's work end-to-end.
2. On the clean tenant, prove tofu matches it:
   `ansible-playbook main.yml --tags tofu-authentik -e manage_authentik_with_tofu=true`
   (plan-only drift detector; import the freshly-created objects; iterate to
   no-op). This is the parity proof the ADR sequenced.
3. Flip `authentik_engine: tofu` and re-converge (no blank needed) once parity
   holds. Reversible.

### Path B (bold): tofu-engine blank in one shot
Set BOTH `manage_authentik_with_tofu: true` and `authentik_engine: tofu`, then
`ansible-playbook main.yml -e blank=true`. The empty tenant means tofu's plan is
all-create / zero-destroy → the destroy guard passes → OpenTofu provisions the
SSO graph directly; the imperative `10-oidc-apps` is skipped. **Higher stakes:**
if a per-service attribute is wrong, SSO for that service is misconfigured until
fixed — but the OTHER blueprints + a re-converge recover it, and flipping
`authentik_engine` back to `blueprint` + re-converge fully restores the
imperative path. Known gaps below still apply (outpost attachment, tier RBAC,
agents, Tier-2).

> **The blank itself is operator-run** (interactive sudo via `vars_prompt`,
> maximally destructive — wipes all data + DBs). Trigger it yourself; this
> runbook is the map.

## Cutover procedure (existing-tenant, no blank)

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

## Edges to smooth before a Path-B (tofu-engine) blank

- **Converge ordering.** The tofu task lives in the `tasks:` section (runs after
  roles). On a blank, `20-rbac-policies` (still applied by the blueprint loop)
  binds tier groups to apps by slug via `!Find` — those apps must EXIST when it
  runs. If tofu creates the apps AFTER the blueprint handler flushes, the RBAC
  `!Find` finds nothing. Verify the ordering (or re-converge once: the second
  pass binds RBAC to the now-existing tofu apps). Path A sidesteps this entirely
  (blueprint creates everything, then tofu adopts).
- **Per-service attribute correctness.** The module's fixed timings
  (`access_token_validity` etc.) + `redirect_uri_type` were tuned to two
  services in Phase 0. A blank creates all 39; a wrong attribute misconfigures
  that one service's SSO until corrected (recoverable).
- **Agents + groups + MFA + enrollment + brand** are created by the SIX
  blueprints that STILL apply under engine=tofu — tofu only owns
  providers/apps/outpost-attachments. Confirm `30-agent-clients` etc. land.

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
