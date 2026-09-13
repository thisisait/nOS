# Layers — what breaks when this stops

> Canonical. This document owns one axis (`layer`) and settles what the word
> **tier** may mean. Numbered headings are the addresses; citations elsewhere
> keep `§N`.

## 1. The problem this exists to remove

Measured 2026-08-07: **tier** carried four unrelated meanings, two in data,
one in prose only, one proposed.

| what it meant | what it actually measures | where it lives |
|---|---|---|
| RBAC tier 1–4 | **who may reach a service** | `rbac_tier` in `state/manifest.yml`, `authentik_rbac_tiers`, per-plugin `authentik.tier` |
| Delivery tier 1–2 | **how a service ships** — full `pazny.*` role vs a manifest in `apps/` | prose only |
| face-app tier F1–F4 + H | **how complex an agent-built app is**, which selects its build recipe | [`face-app-tiers.md`](../../docs/doctrine/face-app-tiers.md) |
| (proposed) | **what else breaks when this stops** | nowhere |

The collision was already paid for once: `sso_autologin_min_tier_<N>` in
`default.config.yml` was named to dodge `authentik_app_tiers` /
`authentik_rbac_tiers`. `face-app-tiers.md` solved its own axis by prefixing
**F1–F4**, **H**. This document generalises that.

## 2. The vocabulary, settled

- **tier** SHALL mean **RBAC tier** and nothing else. It is 1–4, it is about
  access, and it is declared as `rbac_tier`.
- **F1–F4 / H** mean face-app build complexity. Unchanged, already prefixed.
- **layer** is this document's axis: dependency depth, blast radius. Its four
  values live in the genome's `axes` facet (`state/genome/entity.schema.json`,
  `definitions.axes`) beside `form` and `build`, generated into both runtimes
  by `tools/genome-codegen.py`. This section is prose about a vocabulary it
  does not own. `null` — the refusal to place a service — is a legal value
  and MUST travel with a written reason.
- **Delivery tier is RETIRED.** Say **role service** (`roles/pazny.<name>/`)
  or **manifest app** (`apps/<name>.yml`). No code branches on the old phrase.

## 3. The layers

`layer` answers one question: **if this stops, what else stops?** Consequence,
not importance and not privilege.

| layer | what it is | examples |
|---|---|---|
| **L0 substrate** | Nothing in the estate runs without it. The container runtime, the databases, the host daemons that carry state and telemetry. | Docker, PostgreSQL, MariaDB, Redis, Wing, Bone, Pulse |
| **L1 platform** | Services that other services consume. Their failure is felt somewhere other than themselves. | Authentik, Traefik, Grafana, Prometheus, Loki, Infisical |
| **L2 application** | Leaf services with users but no dependents. Their failure is felt where it happens. | Jellyfin, Firefly, Paperclip, WordPress, n8n |
| **L3 custom** | Small per-tenant apps, manifest-shipped, individually disposable. | the `*.apps.<tld>` set |

The example lists are a reading, not a declaration. §5 records where
derivation disagrees; §4.2c says L3 is never emitted.

## 4. Layer is DERIVED, and until 2026-08-07 it could not be

A hand-written layer list MUST NOT ship. `layer` is longest path over the
service projection of the dependency edges
(`tools/anatomy-graph-gen.py::derive_layers`, gate
`tests/anatomy/test_service_layer_is_derived.py`). Consumer-side `depends_on:`
on the service plugin; equivalence with the auto-enable blocks is
`tests/anatomy/test_service_dependency_edges.py`.

The completeness side is derived from the estate, not a seed. Each performing
pair MUST be declared or refused by name. An edge that is neither an
`Auto-enable` block nor otherwise enforced is `unenforced:` —
`install_woodpecker: true` with `install_gitea: false` is a green converge
with a Woodpecker nobody can log into.

The same facts already existed as behaviour: `main.yml` auto-enable for
MariaDB/PostgreSQL/Redis, `CREATE DATABASE` loops, `requires.plugin`. Two
representations is the defect; the working one MUST NOT be removed before the
declared one is load-bearing. OnlyOffice's Redis block gated on
`install_redis`, a variable no config file defines — written up, not
declared. That is §4.1.

### 4.1 — Repair before declare

A hand-written layer table is a fifth place the same fact is written and the
first one that nothing compares. Make the service→service edges real first —
consumer-side, `measured:` — then DERIVE `layer` from them and compare. Where
they disagree, that is the finding.

### 4.2 — What the derivation may be spent on, and what it may not

Three standing constraints follow as 4.2a–4.2c.

The ceiling: the edge set answers *which service do I need*, not yet *what
breaks when this stops*. Reachability is absent — `service:traefik` can
carry zero edges and read `not-surveyed`, and when Traefik stops every
role-service and manifest-app route stops with it. A longest path over
today's edges MUST NOT be presented as a blast radius.

### 4.2a — A node nobody surveyed gets NO layer

`layer` runs on edges. An unsurveyed node contributes nothing. Withheld nodes
MUST carry `layer: null` plus a `layer_withheld` reason
(`counts.services_layer_withheld`). Measured with the refusal disabled:
`service:traefik` derived L2 about the process that binds 80/443;
`service:grafana`, equally unsurveyed but depended on by `mcp_gateway`,
derived L0. Same absence of evidence, opposite verdicts.

### 4.2b — The SSO chain is part of the projection

An `authentik:<slug>` node is a provider+application object inside Authentik,
not an actor. `service:authentik → authentik:<slug> → service:<x>` SHALL
collapse onto its endpoints. Without it, Authentik derived as a leaf: its
provider objects edged to their services and had no in-edge, so the graph
answered "nothing depends on Authentik".

### 4.2c — L3 is not this axis and is never emitted

§3 defines L3 by *delivery* — the retired delivery-tier distinction wearing
a layer's name. It is not derivable from dependency depth.
`services_layer_L3` is 0 on purpose.

## 5. Where the derivation will disagree with intuition, and that is the point

`layer` measures blast radius, not stature. A service can be the most
valuable thing on the box and still be a leaf. If the derived answer is
unwelcome, argue with the edges, not the arithmetic.

Nextcloud has no dependents here: it is L2, beside Jellyfin — not L1 by
feel. That prediction held (R2, 2026-08-07). Census numbers MUST NOT be
copied forward; ask the graph.

| service | §3 says | derives | why |
|---|---|---|---|
| Nextcloud | L1 by feel | **L2** | 4 upstreams, 0 dependents — exactly §5's case |
| Infisical | **L1** (listed) | **L2** | nothing declares a dependency on it; a leaf that holds secrets |
| Wing | **L0** (listed) | **L1** | 4 upstreams of its own — something is underneath it |
| Gitea | (root, `depends_on: []`) | **L1** | `[]` is scoped to *no data upstream*; auth reaches the arithmetic through the Authentik chain |
| Traefik, Grafana, Prometheus, Loki, Jellyfin, … | L0/L1 by feel | **withheld** | unsurveyed — §4.2a |

Infisical and Wing are the rows to argue with. The honest repair is to
declare the missing edges. `layer` will move when they land, and that
movement is the finding.

## 6. What layer is for

- **Harness and gates.** "Which layer may this touch" is a bound that can be
  enforced.
- **Removal.** *"What breaks if this service is removed"* is a graph query
  once the edges exist.
- **Visualisation.** Layer is the missing depth between service nodes.
- **Bring-up.** infra→observability→rest is already a layering; it is simply
  not named or checkable.

## 7. Migration

1. Retire "Tier-1/Tier-2 service" wherever it means delivery. Replace with
   role service / manifest app. Prose only.
2. Declare service→service dependencies consumer-side, seeding from the
   auto-enable blocks and `requires`.
3. Emit `layer` into `state/anatomy-graph.json` as a DERIVED fact.
   **Done 2026-08-07 (R2)** — `derive_layers`; `layer:` is refused at every
   declaration site by `test_layer_is_absent_from_every_declaration_site`.
4. Gate the derivation against any declaration, once one exists. Not before:
   with zero edges, a gate would pin an empty answer.
5. Survey remaining withheld nodes. Traefik first: zero edges, largest blast
   radius on the box.
