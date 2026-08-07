# Layers — what breaks when this stops

> Canonical. This document owns one axis (`layer`) and settles what the word
> **tier** may mean. Cited from code; every `§` here is addressable and resolved
> by `tools/doctrine-cite.py`.

## 1. The problem this exists to remove

Measured 2026-08-07: the word **tier** carries **four** unrelated meanings in
this estate, two of them in data, one in prose only, one proposed.

| what it meant | what it actually measures | where it lives |
|---|---|---|
| RBAC tier 1–4 | **who may reach a service** | `rbac_tier` in `state/manifest.yml`, `authentik_rbac_tiers`, per-plugin `authentik.tier` |
| Delivery tier 1–2 | **how a service ships** — full `pazny.*` role vs a manifest in `apps/` | prose only |
| face-app tier F1–F4 + H | **how complex an agent-built app is**, which selects its build recipe | `docs/doctrine/face-app-tiers.md` |
| (proposed) | **what else breaks when this stops** | nowhere |

The estate had already hit the collision once and worked around it locally:
`default.config.yml:528` explains that a variable was named
`sso_autologin_min_tier_<N>` specifically "to avoid collision/confusion with the
unrelated `authentik_app_tiers` / `authentik_rbac_tiers` maps". Someone paid the
cost of the ambiguity and routed around it rather than removing it.

`face-app-tiers.md` had already solved it properly for its own axis, by
prefixing: **F1–F4**, **H**. This document generalises that precedent.

## 2. The vocabulary, settled

- **tier** means **RBAC tier** and nothing else. It is 1–4, it is about access,
  and it is declared as `rbac_tier`.
- **F1–F4 / H** mean face-app build complexity. Unchanged, already prefixed.
- **layer** is this document's axis: dependency depth, i.e. blast radius.
- **Delivery tier is RETIRED.** Say what the thing is: a **role service**
  (`roles/pazny.<name>/`, compose-override) or a **manifest app**
  (`apps/<name>.yml`, apps_runner). Retiring it costs nothing measurable — no
  code branches on it. Grepped 2026-08-07: of ~1080 non-RBAC occurrences of
  "tier" outside `.md`, every one is a comment or a task name. The two that are
  data are an RBAC `visibility` string and a cosmetic Uptime Kuma monitor tag.
  Nothing ever asks "is this Tier-2?" — it asks whether a manifest exists in
  `apps/`, or whether a container carries Traefik labels.

## 3. The layers

`layer` answers one question: **if this stops, what else stops?** It is about
consequence, not importance and not privilege.

| layer | what it is | examples |
|---|---|---|
| **L0 substrate** | Nothing in the estate runs without it. The container runtime, the databases, the host daemons that carry state and telemetry. | Docker, PostgreSQL, MariaDB, Redis, Wing, Bone, Pulse |
| **L1 platform** | Services that other services consume. Their failure is felt somewhere other than themselves. | Authentik, Traefik, Grafana, Prometheus, Loki, Infisical |
| **L2 application** | Leaf services with users but no dependents. Their failure is felt where it happens. | Jellyfin, Firefly, Paperclip, WordPress, n8n |
| **L3 custom** | Small per-tenant apps, manifest-shipped, individually disposable. | the `*.apps.<tld>` set |

## 4. Layer is DERIVED, and today it cannot be

This is the part that must not be skipped, and it is why this document does not
ship a hand-written list of which service sits where.

**The anatomy graph holds zero service→service edges.** Measured on the 191-node
artifact: `pulse→pulse` 66, `authentik→service` 38, `daemon→pulse` 20,
`judge→doctrine` 14, and **none at all between the 63 service nodes**. The graph
knows that a job feeds a job. It does not know that Nextcloud needs Postgres.

That dependency is real and it is already written down — as **behaviour**, not
as data:

- `main.yml:1221` — *"Auto-enable MariaDB for services that require it"*, a
  `when:` over seven `install_*` flags. That is a dependency statement in
  imperative form.
- `main.yml:1234` — the same for PostgreSQL.
- `requires.plugin` in the plugin manifests, present on **9 of 71** and almost
  entirely composition plugins (`alloy-*`, `grafana-*`).
- The bring-up order itself: infra + observability are always first, always.

So the rule, which is this repository's standing one:

> **§4.1 — Repair before declare.** A hand-written layer table is a fifth place
> the same fact is written and the first one that nothing compares. Make the
> service→service edges real first — consumer-side, `measured:`, exactly as
> `depends_on` was done for Pulse jobs — then DERIVE the layer from them and
> compare the derivation against the declaration. Where they disagree, that is
> the finding.

Until those edges exist, §3 is a **design target**, not an inventory, and no
gate may assert membership.

## 5. Where the derivation will disagree with intuition, and that is the point

The examples in §3 came from the operator's own reading, and at least one of
them will not survive derivation: **Nextcloud has no dependents in this estate.**
By consequence it is L2, beside Jellyfin — not L1, where it feels like it
belongs because it is important and widely used.

That gap is the reason to derive rather than to declare. `layer` measures blast
radius, not stature. A service can be the most valuable thing on the box and
still be a leaf. If the derived answer is unwelcome, the correct response is to
argue with the edges, not to overrule the arithmetic.

## 6. What layer is for

- **Harness and gates.** "Which layer may this touch" is a bound that can be
  enforced; "which tier" was three questions at once.
- **Removal.** *"What breaks if this service is removed"* is a graph query once
  the edges exist. Today it is a guess — which is precisely why the ERPNext
  removal question could not be answered with a number.
- **Visualisation.** The estate map draws 63 service nodes with no structure
  between them because there is none to draw. Layer is the missing depth.
- **Bring-up and blast-radius reasoning.** The order infra→observability→rest is
  already a layering; it is simply not named or checkable.

## 7. Migration

1. Retire the phrase "Tier-1/Tier-2 service" wherever it means delivery. Replace
   with role service / manifest app. Prose only, no code path.
2. Declare service→service dependencies consumer-side, seeding from the
   auto-enable blocks and `requires`.
3. Emit `layer` into `state/anatomy-graph.json` as a DERIVED fact, with the
   generator refusing a cycle exactly as it does for the other edge kinds.
4. Gate the derivation against any declaration, once one exists. Not before:
   with zero edges, a gate would pin an empty answer.
