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
> layer only**, keeping `plugin.yml` as the single source of truth and
> *generating* HCL from the harvested `authentik:` blocks. Start **plan-only**
> as a zero-risk drift detector (it would have caught the incident that
> triggered this ADR), then flip the apply path. **OpenTofu, never Terraform**
> (BSL conflicts with the all-FOSS principle).

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

The `plugin.yml` **multi-consumer manifest is the right abstraction** and must
not be replaced: a service declares all seven wiring blocks in one cohesive
place and the loader fans them out. Splitting `authentik:` into a hand-written
`.tf` would tear a service's identity across two files — worse cohesion.

Therefore: **keep the manifest as SoT; swap the reconcile *engine* for the one
consumer that needs it.** Generate HCL from the harvested `authentik:` blocks
exactly as the loader generates `10-oidc-apps.yaml` today. HCL becomes a
**generated render target**, never an authoring surface. nOS already values
declarative state — `nos_state` (`manifest.yml` vs `~/.nos/state.yml`,
merge-never-overwrite) is a home-grown `tfstate`. This is the same instinct with
a battle-tested engine, applied where it pays.

---

## 5. Options considered

| Option | Scope | Verdict |
|---|---|---|
| **A. Status quo** | imperative `ak apply_blueprint` | Cheap, but today's MTI-drift class recurs; no drift detection |
| **B. OpenTofu — Authentik consumer only (generated HCL)** | replace artifact-class #1's engine | **RECOMMENDED.** Highest-value, smallest blast radius; manifest stays SoT |
| **C. OpenTofu — Authentik + Grafana + Postgres + GitLab** | #1 + clean-provider subset of #5/#6 | Defensible later, per-consumer; still leaves Pulse/notif/hub/lifecycle in loader |
| **D. Broad rewrite incl. Docker/compose** | "HCL for as many services as possible" | **REJECT.** Kills compose-override; requires building Go providers for 4 internal consumers; 2nd-SoT split-brain |

The operator's framing — "HCL for as many services as possible" — maps to
Option D, and the measured surface (§1) does not support it: most of the
autowiring is nOS-internal plumbing no provider reaches.

---

## 6. Recommended path (phased, reversible)

- **Phase 0 — spike, ZERO risk (do now, in beta):** loader emits OpenTofu HCL
  for the Authentik layer from the same aggregated `authentik:` blocks, behind a
  feature flag. Run **`tofu plan` only** (no apply) as a read-only drift
  detector; keep `ak apply_blueprint` authoritative. Acceptance: render parity
  with the live blueprint across ≥3 converges + it flags a seeded drift. *This
  alone would have caught the incident that triggered this ADR.*
- **Phase 1 — flip apply (after Phase 0 proves parity):** `tofu apply` becomes
  the Authentik authority; retire `ak apply_blueprint` for that layer; the
  v0.5 MTI reconcile handler (a shared-base footgun) is deleted. `tfstate`
  enters Infisical custody + the backup set. Drift-check `tofu plan` runs as a
  Pulse job → W6.1 notification.
- **Phase 2 — optional, per-consumer:** extend to Grafana (dashboards/DS) and
  Postgres (roles/DBs/`pgcrypto`) and GitLab where the provider is clean and the
  resource count is low. Each is an independent small TF root, gated, reversible.
- **Never:** Docker/compose, Pulse jobs, notification routing, hub cards,
  lifecycle hooks — stay in the loader.

---

## 7. Beta-timing verdict

The cheap, reversible, high-value move (Phase 0 → 1, **Authentik only**) is
worth committing to **now**, while in beta. The broad HCL rewrite is **not**
justified by the evidence: the autowiring surface is dominated by nOS-internal
consumers OpenTofu cannot touch, and the one broad provider would cost us the
compose-override architecture. Lock the architecture as: **`plugin.yml` is the
single declarative SoT; the loader fans out to seven consumers; OpenTofu is the
reconcile engine for the Authentik consumer, generated from the manifest.**

## 8. Open questions before Phase 1 (not Phase 0)

- `tfstate` storage on a single host: local file + Infisical-backed encryption,
  or a state backend? (Local file + backup set is likely fine for a home-lab.)
- Locking model when both a blank run and a manual `tofu` could race.
- Whether Tier-2 apps' `authentik:` blocks generate into the same TF root as
  Tier-1 (they should — one Authentik, one state).
