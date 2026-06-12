# OpenTofu Authentik cutover runbook (ADR-0001 Phase 1)

> **STATUS: CUTOVER COMPLETE (2026-06-12).** Path B (tofu-engine blank)
> executed and converged: `tofu plan` reads no-op across the full tenant,
> smoke catalog 48/48 URLs OK, all 39 enabled apps carry their RBAC tier
> binding, agent clients (`30-agent-clients`) landed. `authentik_engine: tofu`
> is the live authority. This document is now the operating reference +
> archaeology of the five traps the cutover surfaced. Read
> [ADR-0001](adr/0001-opentofu-for-autowiring.md) for the why.

## The two switches

| Var | Default | Meaning |
|---|---|---|
| `manage_authentik_with_tofu` | `false` | Opt-in: run the OpenTofu task at all (Phase 0 drift detector + Phase 1 apply). |
| `authentik_engine` | `"blueprint"` | Authority: `blueprint` = `ak apply_blueprint` is the source of truth (OpenTofu is plan-only/advisory). `tofu` = OpenTofu applies; the imperative blueprint reapply + the MTI footgun handler are **skipped** and the `10-oidc-apps` blueprint renders as a no-op. |

Ownership split under `engine=tofu`: **OpenTofu owns providers + applications
+ outpost attachments** (the `10-oidc-apps` layer). The other six blueprints —
groups / MFA / RBAC policies / agent clients / enrollment / brand — **still
apply imperatively** and that is by design, not a gap.

## The safety rail: the destroy guard

`tasks/tofu-authentik.yml` parses `tofu show -json tfplan` and **refuses to
apply if the plan contains ANY delete action.** The danger it blocks: a
partially-authored tenant plans un-authored providers as destroys →
catastrophic SSO outage. The guard makes any engine flip a no-op-or-nothing
operation.

## The five traps (all fixed + gated — archaeology)

Every one of these surfaced live during the 2026-06-11/12 cutover blanks and
is pinned by a CI gate. If you touch this layer, read them first.

1. **Authentik auto-applies mounted blueprints** (container start + inotify on
   `/blueprints/custom`) — gating the `ak apply_blueprint` loops is NOT
   enough. Blank #1 died on 36× "provider already exists": the rendered
   `10-oidc-apps.yaml` had already created everything before `tofu apply`.
   *Fix:* under `engine=tofu` the template renders ZERO client entries, and
   the embedded-outpost entry keeps `config:` but OMITS `providers:` (a
   blueprint apply must never unbind tofu-attached providers).
   *Gate:* `tests/anatomy/test_tofu_engine_blueprint_noop.py`.
2. **`lookup('file') | from_yaml` never resolves nested Jinja** (post-2.19
   trust model). Blank #2 died on 22× `external_host: "Enter a valid URL"` —
   tfvars carried literal `https://{{ x_domain }}`. *Fix:* the registry loads
   via `lookup('template', ...)` so the FILE renders first.
   *Gate:* `tests/anatomy/test_tofu_registry_bridge.py`.
3. **`authentik_outpost_provider_attachment` races at default parallelism** —
   the resource is a read-modify-write over the outpost's providers LIST (no
   row-level m2m API). Blank #3 created 20 attachments in parallel;
   last-writer-wins kept 11 and 9 forward_auth services 404'd at the outpost.
   *Fix:* `tofu apply -parallelism=1` (serial, ~60s).
   *Gate:* `test_tofu_registry_bridge.py::test_apply_is_serial`.
4. **The registry generator was Tier-1-only** — `apps/<name>.yml` `authentik:`
   blocks (documenso/roundcube/twofauth) had NO creator under `engine=tofu`
   (blueprint no-op'd, registry missed them) → 404, no provider at all.
   *Fix:* `tools/tofu-authentik-gen-registry.py` harvests app manifests like
   the live loader does, plus slug dedupe (qdrant lives in BOTH tiers).
   *Gate:* `test_tofu_registry_bridge.py::test_registry_covers_tier2_app_manifests`.
5. **`internal_host_ssl_validation=false` never converges** — Authentik
   normalizes the field back to `true` whenever `internal_host` is empty
   (all our forward_single proxies route via Traefik), producing a perpetual
   23-provider in-place diff. *Fix:* module default flipped to `true`.

## Operating the tofu engine (steady state)

- **Full converge** (`ansible-playbook main.yml`) re-renders tfvars, plans,
  destroy-guards, applies. **Layer-only converge** (sudo-free, agent-friendly):
  `tools/nos-stacks.sh tofu-authentik`.
- **Add a Tier-1 service:** plugin `authentik:` block →
  `python3 tools/tofu-authentik-gen-registry.py` → commit the registry diff.
- **Add a Tier-2 app:** `authentik:` stanza in `apps/<name>.yml` → same
  regenerate + commit.
- **Verify after any change:** `tofu plan` must return to no-op;
  `python3 tools/nos-smoke.py` must stay green.
- A blank with `authentik_engine: tofu` provisions the whole SSO graph from
  scratch (validated: blank #3 + fixes → 48/48).

## Rollback

Flip `authentik_engine` back to `"blueprint"` and re-run — the imperative
blueprint reapply + MTI reconcile handlers re-engage and `10-oidc-apps.yaml`
renders its full client list again. Keep the blueprint renderer until the tofu
engine has held no-op across several releases.

## Open items

Punch list items #1–#3 (extracted 2026-06-12) **shipped the same day**:

- ~~Secrets custody (P1)~~ — `run_tofu_state()` in `backup.sh` puts
  `terraform.tfstate` (+`.backup`) + `nos.auto.tfvars.json` into the nightly
  AES-256 set (Restic off-site copy #2 rides the bucket mirror); the generic
  restore stage recovers them to the restore workdir (re-seating into the git
  checkout is deliberately manual). Gate: `test_backup_restore_contract.py`.
  Infisical custody skipped deliberately — no playbook-level infra-secret push
  precedent exists, and tfstate is a rotating document, not a KV secret.
- ~~Disabled-service filtering (P2)~~ — the registry carries each client's
  `enabled` Jinja expr verbatim; the tfvars template filters falsy services
  after the `lookup('template')` render. **Operational consequence:** on an
  already-provisioned tenant a service flipping `enabled→false` plans as a
  DESTROY and the guard refuses — review the plan and run `tofu apply tfplan`
  supervised, or let the next blank converge it. Gate:
  `test_tofu_registry_bridge.py` (enabled-carry + filter semantics).
- ~~Drift Pulse job (P2)~~ — plugin `authentik-tofu-drift-base` runs
  `tofu plan -detailed-exitcode -lock=false` daily (05:30, plan-only, never
  applies — pinned by a mutating-verb sweep); drift → medium A9 notification,
  error/timeout → high. Skips cleanly pre-cutover. Gate:
  `test_tofu_drift_pulse_job.py`.

Still open:

- **Adopt-path attachment import id (P3, existing-tenant only):**
  `tools/tofu-authentik-adopt.sh` imports proxy/oauth2/app cleanly but the
  `outpost_provider_attachment` import id format is unconfirmed (shows as
  `1 to add`). Irrelevant for the blank path (fresh creates land in state);
  matters only when adopting a long-lived tenant without a blank.
