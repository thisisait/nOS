# ADR-0001 — OpenTofu (HCL) for the autowiring substrate

- **Status:** Proposed (2026-06-11) — decision pending operator approval
- **Context trigger:** an Infisical SSO gate outage (MTI provider collision in
  Authentik) that took hand-`ak shell` reconciliation to fix — and during the
  fix, deleting the OAuth2 sibling cascade-deleted the working Proxy provider.
  The operator asked: should autowiring be declarative in OpenTofu instead?
- **Scope of this ADR:** whether to adopt OpenTofu/HCL **generally, for as many
  services as possible**, or narrowly, or not at all. Project is in beta — the
  cheapest time to lock the architecture.

> **TL;DR recommendation:** Do **not** rewrite the autowiring into HCL broadly —
> the surface is dominated by nOS-internal consumers no provider can touch, and
> the one broad provider (Docker) would force abandoning the compose-override
> pattern. **Do** adopt OpenTofu as the reconcile **engine for the Authentik
> layer only**. **Authoring model (revised 2026-06-11, §9):** services declare
> their Authentik wiring as **hand-authored HCL** — a thin `nos-authentik-app`
> module for the common case, raw resources for the exotic — with VALUES bridged
> from the playbook via a generated `tfvars.json` and the nOS-required shape
> enforced by a **conformance policy** over `tofu plan -json` (NOT a YAML→HCL
> generator — that is the inner-platform trap). Start **plan-only** as a
> zero-risk drift detector (it would have caught the incident that triggered
> this ADR), then flip the apply path. **OpenTofu, never Terraform** (BSL
> conflicts with the all-FOSS principle).

---

## 1. What the autowiring actually produces (measured, not assumed)

The plugin loader (`files/anatomy/module_utils/load_plugins.py`) harvests
per-plugin manifest blocks via three aggregators and renders **seven classes of
live artifact**. The provider-coverage reality:

| # | Artifact class | Source block(s) | Apply mechanism today | Mature OpenTofu provider? |
|---|---|---|---|---|
| 1 | **Authentik** providers/apps/outposts/groups/flows/policies | `authentik:` (+ agent `authentik:`) → authentik-base | `ak apply_blueprint` (imperative, non-diffing) | **YES** — `goauthentik/authentik`, 96 resources, `provider_oauth2`/`provider_proxy` **distinct**, `outpost_provider_attachment` |
| 2 | **Pulse jobs** (cron catalog in wing.db) | `pulse:` → pulse-base | Wing API POST (`discover-pulse-catalog.py`) | **NO** — nOS-internal |
| 3 | **Notification routing** (Bone JSON) | `notification:` → wing-base | file render, Bone reads at insert | **NO** — nOS-internal |
| 4 | **Hub cards** (wing.db systems) | `ui-extension:`/`hub_card:` → wing-base | Wing systems ingest | **NO** — nOS-internal |
| 5 | **Compose services** (containers) | `compose_extension:` + role `compose.yml.j2` | `docker compose up` (override merge) | **partial/disruptive** — `kreuzwerker/docker` manages containers directly, **not compose** |
| 6 | **Observability** (Grafana dashboards/datasources, Prometheus rules) | `observability:` | file drop into provisioning dirs | **partial** — `grafana/grafana` covers dashboards/DS/alerts; Prometheus scrape config is file-based (no) |
| 7 | **Lifecycle hooks** (post-API setup, admin init) | `lifecycle:` | imperative shell/API calls | **NO** — imperative by nature |

**The decisive fact:** of seven artifact classes, **four are nOS-internal
systems with no provider** (Pulse, notifications, hub, lifecycle), the **one
broad provider (Docker) would require abandoning compose-override** — a core
nOS pattern (merge semantics, `depends_on`, healthcheck DSL, profiles, the
`-f override` orchestration in `core-up.yml`/`stack-up.yml`) — and only
**Authentik (1) + a Grafana subset (6)** map cleanly.

### Tier-2 apps_runner — the proposed pilot, measured

A single Tier-2 deploy (`roles/pazny.apps_runner/tasks/post.yml`) fans out to
~10 post-hooks: compose render+up, service-registry re-render, **Wing systems
ingest**, **Authentik reconverge**, **Bone HMAC events**, JSONL mirror,
**Portainer endpoint reg**, **Uptime-Kuma monitors**, **GDPR upsert**, smoke
catalog. **Exactly one** (Authentik) has a clean TF provider; the rest are
nOS-internal or weak-provider. So Tier-2 is **not** the clean pilot it looks
like — it is the most nOS-internal-heavy layer we have.

---

## 2. What OpenTofu/HCL genuinely buys — and precisely where

OpenTofu's value is **a state file + a planned diff + typed resource identity**:
`plan` computes create/update/delete/**replace** against prior state, orders a
dependency DAG, and detects drift. This is worth real money in exactly one
place in nOS today: **Authentik**, because it is the only substrate that is
simultaneously (a) backed by a rich typed API with a mature provider, and (b)
the source of drift we cannot hand-reconcile.

Evidence — the incident that triggered this ADR:
- Authentik's `OAuth2Provider` and `ProxyProvider` are Django **multi-table-
  inheritance** subclasses sharing one globally-unique base `Provider` row. On
  this tenant they shared **one** base row; `ak shell` deleting the oauth2
  sibling **cascade-deleted the working proxy** + its outpost binding.
- The TF provider models `provider_oauth2` and `provider_proxy` as **distinct
  resources with distinct addresses**, plus `application` and
  `outpost_provider_attachment`. A `native_oidc → forward_auth` flip is a clean
  planned **`destroy provider_oauth2` + `create provider_proxy` + update
  `application.provider_id` + create `outpost_provider_attachment`** — ordered,
  idempotent, reviewable in `plan`. The cascade roulette is structurally
  impossible.
- `tofu plan` is a **free drift detector**: the orphan oauth2 (invisible today
  until login broke) would surface as planned drift. This composes with the
  W6.1 notification emitters — a Pulse `tofu plan` job → "Authentik drifted".

---

## 3. What it costs / where it does not fit

1. **Second source of truth.** nOS doctrine: *the Ansible playbook is the single
   source of truth.* A `tfstate` is a second authoritative store — must be
   locked, backed up, and reconciled. It is **secret-bearing** (provider
   client_secrets) → it joins the 3-2-1 backup set + Infisical custody (the DR
   surface just hardened in S4). Split-brain risk is real if both Ansible and
   TF believe they own a resource.
2. **Docker is a trap.** `kreuzwerker/docker` models `docker_container`
   resources — it does **not** speak compose. Adopting it means rewriting the
   entire compose-override layer as per-container TF resources, losing compose
   merge / `depends_on` / healthcheck DSL / profiles and the `find -f override`
   orchestration. This is a large regression for zero correctness gain (compose
   is already declarative + idempotent).
3. **Four consumers have no provider.** Pulse, notifications, hub, lifecycle are
   nOS-internal. "Covering them in HCL" means **writing a Terraform provider in
   Go** for each — a multi-month effort to replace working idempotent renders.
4. **Bootstrapping / ordering.** TF needs the target API up at apply time
   (Authentik running, token minted). We already mint `authentik_bootstrap_token`;
   reusable. But it interleaves `ansible` (brings up) and `tofu` (configures) —
   more moving parts, made explicit.
5. **Toolchain + offline story.** A new binary (`tofu`) + provider downloads.
   The frozen-CI 1:1 toolchain (just built: `requirements.lock.yml` +
   `ci-freeze.env`) gains a `.terraform.lock.hcl` peer — which OpenTofu does
   well, so this cost is low.
6. **HCL as a third authoring language** (alongside Ansible/Jinja, PHP, Python)
   — **only if hand-authored**. Mitigated entirely by *generating* HCL from
   `plugin.yml` (same as the blueprint is generated today).

---

## 4. The architectural insight

`plugin.yml` stays the source of truth for the **six nOS-internal consumers**
(pulse, notification, hub, compose_extension, observability, lifecycle). The
**Authentik consumer moves out** to its own representation, managed by a real
engine. This is NOT a new kind of split: a service is *already* defined across a
role (`compose.yml.j2`) **and** `plugin.yml` — adding a `.tf` for the one
substrate with a typed API + mature provider is the same multi-file reality, one
file per concern, each in its native engine.

**Authoring model — revised (see §9):** the first draft of this ADR proposed
*generating* HCL from the `authentik:` YAML block. That is the **inner-platform
trap** — the generator's input schema must keep growing to mirror the provider's
96 resources, reinventing HCL in YAML, and the author debugs generated code they
never wrote. The better design (operator's insight, 2026-06-11): **author HCL
directly**, bridge VALUES from the playbook, and assert the nOS-required shape
with a conformance test. nOS already values declarative state — `nos_state`
(`manifest.yml` vs `~/.nos/state.yml`, merge-never-overwrite) is a home-grown
`tfstate`; this is the same instinct with a battle-tested engine.

---

## 5. Options considered

| Option | Scope | Verdict |
|---|---|---|
| **A. Status quo** | imperative `ak apply_blueprint` | Cheap, but today's MTI-drift class recurs; no drift detection |
| **B. OpenTofu — Authentik consumer only, hand-authored HCL + module + conformance** | replace artifact-class #1's engine | **RECOMMENDED.** Highest-value, smallest blast radius; six other consumers stay in `plugin.yml` |
| **C. OpenTofu — Authentik + Grafana + Postgres + GitLab** | #1 + clean-provider subset of #5/#6 | Defensible later, per-consumer; still leaves Pulse/notif/hub/lifecycle in loader |
| **D. Broad rewrite incl. Docker/compose** | "HCL for as many services as possible" | **REJECT.** Kills compose-override; requires building Go providers for 4 internal consumers; 2nd-SoT split-brain |

The operator's framing — "HCL for as many services as possible" — maps to
Option D, and the measured surface (§1) does not support it: most of the
autowiring is nOS-internal plumbing no provider reaches.

---

## 6. Recommended path

Superseded by the detailed phase plan in **§10**. Summary: Phase 0 = author HCL
+ `tofu plan`-only drift detector (zero risk); Phase 1 = flip apply, retire the
MTI footgun; Phase 2 = extend to Grafana/Postgres/GitLab via `import` +
coexistence. **Never:** Docker/compose, Pulse, notifications, hub, lifecycle.

---

## 7. Beta-timing verdict

The cheap, reversible, high-value move (Phase 0 → 1, **Authentik only**) is
worth committing to **now**, while in beta. The broad HCL rewrite is **not**
justified by the evidence: the autowiring surface is dominated by nOS-internal
consumers OpenTofu cannot touch, and the one broad provider would cost us the
compose-override architecture. Lock the architecture as: **`plugin.yml` is the
SoT for the six internal consumers; the Authentik consumer is hand-authored HCL
(module + conformance test), VALUES bridged from the playbook; OpenTofu is its
reconcile engine.**

## 8. Open questions before Phase 1 (not Phase 0)

- `tfstate` storage on a single host: local file + Infisical-backed encryption,
  or a state backend? (Local file + backup set is likely fine for a home-lab.)
- Locking model when both a blank run and a manual `tofu` could race.
- Tier-2 apps' Authentik wiring: a thin `authentik:` stanza in `apps/<name>.yml`
  rendered into a **module instantiation** (lossless — 4 inputs, not the YAML→HCL
  schema treadmill), preserving the "drop a manifest, no raw code" Tier-2 promise
  while landing in the same single TF root as Tier-1.

---

## 9. Authoring model — generated vs hand-authored HCL (decided 2026-06-11)

**Decision: hand-author HCL; do not generate it from YAML.** The operator's
pushback was correct — a YAML→HCL generator is the inner-platform anti-pattern:

| | Generate HCL from `authentik:` YAML | **Hand-author HCL (chosen)** |
|---|---|---|
| Expressiveness | Lossy — capped at whatever the YAML schema mirrors; exotic Authentik (custom flows, property mappings, RAC/SCIM, policy bindings) needs ever-growing schema | Full provider (96 resources) immediately |
| Representations | Two (YAML authored, HCL runs) → debug generated code you didn't write | One — the source IS what runs; native `tofu validate`/`plan`/IDE |
| Maintenance | A generator (Go/Python) + its tests + translation drift | A module + a policy test |
| Ergonomics | "fill a block" (low skill) | "5-line module call" (comparable) or raw HCL (full power) |

**The shape — three layers:**

1. **`modules/nos-authentik-app`** — a reusable OpenTofu module encoding the
   nOS-required wiring so you *cannot* instantiate it wrong: it creates the
   `application`, the right provider for `mode` (`forward_auth`→`provider_proxy`,
   `native_oidc`→`provider_oauth2`), the `outpost_provider_attachment` to the
   embedded outpost, and the tier→group `policy_binding`. The common case is a
   ~5-line call — as ergonomic as today's YAML block, but one representation:
   ```hcl
   module "infisical" {
     source = "../modules/nos-authentik-app"
     mode   = "forward_auth"          # proxy provider; no oauth2 ever created
     slug   = "infisical"
     name   = "Infisical"
     domain = var.infisical_domain    # value from the playbook (see layer 2)
     tier   = 1
   }
   ```
   Because the module *never* creates an oauth2 provider for `forward_auth`, the
   exact orphan-oauth2 / MTI-shared-base cascade that triggered this ADR is
   impossible by construction. A service needing exotic Authentik drops the
   module and writes raw resources — full escape hatch, no schema treadmill.

2. **Values bridge — `tfvars.json` from the playbook.** Ansible owns VALUES
   (domains, client secrets, tenant_domain, tier group names, the
   `authentik_bootstrap_token`); HCL owns STRUCTURE. A playbook task renders
   `terraform/authentik/nos.auto.tfvars.json` from the same vars the blueprint
   uses today; the `.tf` references `var.*`. Clean separation: secrets never live
   in `.tf` (they flow through tfvars.json, which is `0600` + Infisical custody +
   in the backup set, same as `~/.nos/secrets.yml`). **No Jinja inside HCL.**

3. **Conformance policy — assert nOS invariants over `tofu plan -json`.** Instead
   of constraining *how* a service wires Authentik, assert the INVARIANTS every
   service must satisfy, as a test over the plan JSON (pytest, or conftest/OPA):
   - every `authentik_application` has a bound provider;
   - every proxy/oauth2 provider has exactly one `outpost_provider_attachment`
     to the embedded outpost (the today-incident guard);
   - a `forward_auth` service declares **no** `provider_oauth2` (and vice-versa) —
     mode/provider-type coherence;
   - every app has a tier→group `policy_binding` (RBAC never forgotten);
   - provider/app `name`/`slug` are unique (catches the MTI name collision at
     plan time, before apply).
   This replaces "the loader validates the `authentik:` block" with "the plan
   must satisfy the nOS contract" — stronger, because it checks the *realized
   graph*, not the input.

**Cohesion cost, owned honestly:** a service's wiring now lives in role
(`compose.yml.j2`) + `plugin.yml` (6 blocks) + `<svc>.tf` (Authentik). Three
files. Mitigation: the `.tf` sits beside the role (`roles/pazny.<svc>/authentik.tf`)
or in one central `terraform/authentik/services/<svc>.tf`; a `make new-service`
scaffold drops all three stubs. The `plugin.yml` `authentik:` block is **removed**
(no more dual representation); the loader stops harvesting it.

---

## 10. Phase plan (0 / 1 / 2)

### Phase 0 — drift detector, ZERO risk (target: v0.6 spike branch)

Goal: stand up the OpenTofu Authentik root in **read-only `plan`** while
`ak apply_blueprint` stays authoritative. Catches drift; commits to nothing.

1. `terraform/authentik/` root: pin `goauthentik/authentik` provider +
   `.terraform.lock.hcl`; provider configured from `var.authentik_url` +
   `var.authentik_bootstrap_token` (already minted by the playbook).
2. `modules/nos-authentik-app` (layer-1 module) + hand-author HCL for **2–3
   representative services** only: infisical (forward_auth — the incident
   service), grafana (native_oidc auto-redirect), one agent client.
3. Playbook task (tag `tofu-authentik`, default-off flag
   `manage_authentik_with_tofu: false`) renders `nos.auto.tfvars.json` from the
   existing Authentik vars; runs `tofu init` + **`tofu plan -detailed-exitcode`**;
   does **NOT** apply. Plan diff → log + (optional) W6.1 notification.
4. **`tofu import`** the 2–3 live objects so the plan reads as "no changes"
   against reality — this proves the hand-authored HCL matches the running state.
5. Conformance test (layer-3) over `tofu plan -json` in CI (pytest, offline:
   `tofu plan` needs the API, so the CI leg runs `tofu validate` + the policy
   over a fixture plan; the live plan-parity runs in the integration wet-test).

**Acceptance:** `tofu plan` reads no-change against the live tenant for the 3
services across ≥3 converges; a deliberately-seeded orphan (re-add an oauth2 for
infisical) shows up as planned drift; conformance test green. *This alone makes
the triggering incident visible before it breaks login.*

### Phase 1 — flip apply, Authentik fully on OpenTofu (target: post-v0.6)

1. Hand-author HCL for **all** Tier-1 services + agents + Tier-2 (via the thin
   `authentik:`-stanza → module instantiation render, §8). `tofu import` every
   live object first → first `apply` is a no-op (no destroy/recreate of the live
   tenant — the whole tenant is adopted, not rebuilt).
2. Flip `manage_authentik_with_tofu: true`: `tofu apply` becomes authoritative;
   the loader stops emitting `10-oidc-apps.yaml`; **delete the v0.5 MTI reconcile
   handler** (the shared-base footgun) and the `authentik:` harvest in the
   aggregator.
3. `tfstate` → `0600`, Infisical custody, joins the 3-2-1 backup set + a
   `restore-verify` floor (it is now a recovery-critical secret-bearing artifact).
4. A `tofu plan` drift-check Pulse job (read-only) → W6.1 "Authentik drifted"
   notification. State-locking: the blank run and any manual `tofu` serialize on
   a file lock (single host) — documented operator rule, no concurrent apply.

**Rollback:** keep `10-oidc-apps.yaml` render behind the flag for one release;
flipping the flag back restores the imperative path. Reversible until we delete
the renderer.

### Phase 2 — extend per-consumer, WITH coexistence (target: opportunistic, post-1)

Each consumer is an **independent** small TF root, adopted via `import` so live
state is never destroyed — this is the coexistence contract: TF and the existing
Ansible-managed config must not double-manage. The boundary is explicit
("owned-by: tofu" vs "owned-by: ansible") per resource class.

| Consumer | Provider | Coexistence approach |
|---|---|---|
| **Grafana** dashboards/datasources/alerts | `grafana/grafana` | `import` existing dashboards; Ansible KEEPS Prometheus scrape config (file, no provider). TF owns dashboards/DS, Ansible owns the Alloy/Prom wiring — clean split, no overlap |
| **PostgreSQL** roles/DBs/`pgcrypto`/SSL params | `cyrilgdn/postgresql` | `import` existing roles/DBs (created by `postgresql/tasks/post.yml`); flip ownership atomically per-DB; the **coexistence framework** (`nos_coexistence`, pg16+pg17 dual-track) is UNAFFECTED — it operates at the container/data layer, below TF's role/DB layer, so they compose |
| **GitLab** project/CI vars/protected branches (forge) | `gitlabhq/gitlab` | `import` the agent-forge project + tokens; T32.2 forge wiring (currently `post-forge.yml` lineinfile) becomes declarative; coexists with Gitea (separate root) |

Each Phase-2 consumer ships only when: (a) `import` makes the first plan a
no-op, (b) a conformance test pins its nOS invariants, (c) the Ansible path is
flagged off behind `manage_<x>_with_tofu`. No consumer is mandatory; skip any
whose provider proves immature on inspection.

**Never migrated:** Docker/compose (kills compose-override), Pulse jobs,
notification routing, hub cards, lifecycle hooks — all stay in the loader.

### Cross-phase: the frozen-toolchain + DR obligations

- `tofu` binary version + `.terraform.lock.hcl` (provider pins) join the frozen
  CI toolchain next to `requirements.lock.yml` / `ci-freeze.env`.
- `tfvars.json` (secret-bearing) + `tfstate` (secret-bearing) → `0600` +
  Infisical custody + backup set + `restore-verify` floors, BEFORE Phase 1.
- A Linux note like PG-SSL: `tofu` must be installed cross-platform (apt/brew);
  the integration wet-test gains a `tofu plan` parity leg.
