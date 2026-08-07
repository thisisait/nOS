# 13 — Relations: making the estate's edges real

> The estate declared 191 nodes and 151 edges, and **not one edge between two
> services**. Everything below follows from that single measurement.
>
> **R1 closed it on 2026-08-07** and **R2 landed the same day**, after three
> adversarial reviews took R1 apart: 196 nodes, 232 edges, **35** of them
> between services, and `layer` derived on 25 of 63 — the other 38 withheld
> rather than guessed. R3 shipped; R4 stands open.

## The problem it exists to remove

Three questions the estate cannot answer today, all of them the same question:

1. *"What breaks if I remove ERPNext?"* — asked 2026-08-07, answered with a
   guess, because nothing records what depends on what.
2. *"Which layer is this service?"* — `docs/doctrine/layers.md` defines the axis
   and refuses to ship an inventory, because `layer` must be derived and the
   derivation has no input.
3. *"What kind of thing is this face app?"* — answered today by a **complexity**
   scale (`F1`–`F4`) that also decides the build recipe, so two unrelated facts
   share one field.

The dependency exists. It is written as **behaviour**, not as data:
`main.yml:1221` (`Auto-enable MariaDB for services that require it`, a `when:`
over seven `install_*` flags), `main.yml:1234` for PostgreSQL, `requires.plugin`
on 9 of 71 manifests, and the standing infra→observability→rest bring-up order.
Four expressions of one fact, none of them queryable.

## R1 — service→service edges

Consumer-side, in the plugin manifest, exactly as `depends_on` was done for
Pulse jobs: same slot, same harvest path, `measured:` on every edge.

Seed from what already exists rather than authoring from memory — the
auto-enable blocks ARE the declaration, and transcribing them is a
transformation, not an opinion. Then:

- the generator emits `service→service` edges of kind `data`;
- the soundness gate refuses a cycle per kind, as it already does;
- **repair before declare**: an edge whose dependency the code does not actually
  enforce is not declared, it is written up.

**Refusal:** do not delete the auto-enable blocks in the same change. Two
representations is the defect, but removing the working one before the declared
one is load-bearing is how an estate loses a dependency entirely.

**SHIPPED 2026-08-07.** 23 service→service edges, all transcribed: 22 from the
three auto-enable blocks (corroborated against
`roles/pazny.postgresql/tasks/post.yml`'s `CREATE DATABASE` loop and
`default.config.yml`'s `mariadb_databases`) and one from
`woodpecker-base`'s `requires.peer_service: gitea`. The slot is a **top-level
`depends_on:`** on the service plugin — same key, shape and refusals as a pulse
job's, one level up — and it did NOT need the two Wing allow-lists: those gate
the *pulse catalog* POST, and a service edge is read straight off the manifest
by `tools/anatomy-graph-gen.py`. No auto-enable block was touched.

Two things the change deliberately did not do, both §4.1:

- **`(onlyoffice → redis)` is written up, not declared.** `main.yml:1259`
  auto-enables Redis for OnlyOffice; `roles/pazny.onlyoffice/templates/compose.yml.j2:38`
  gates the whole `REDIS_SERVER_*` block on **`install_redis`, which no config
  file defines** — so it has never rendered. Same phantom flag at
  `roles/pazny.uptime_kuma/tasks/monitors.yml:302`, `state/manifest.yml:76` and
  `state/gdpr-erasure-map.yml:171`. Repairing it turns Redis on for a live
  service, which is a runtime change and belongs in its own diff.
- **The observability flows are not dependencies.** Alloy→Prometheus/Loki/Tempo
  and the exporter sidecars in `roles/pazny.grafana/templates/compose.yml.j2`
  are producer→sink, and gated on the provider's own flag: removing Prometheus
  does not stop Alloy. Declaring them under the same `kind` would make R2's
  longest path answer a different question.

**Absence is a state, not a gap in the data.** Every service node carries
`dependency_survey`: `declared` (25), `not-surveyed` (34), `no-manifest` (4).
The remainder is published in `counts`, not rounded away.

### What three adversarial reviews of R1 changed (2026-08-07)

All three opened on the same measurement and it was correct: **`service:authentik`
had out-degree 0** while reading `dependency_survey: declared`. Its 38 provider
objects edged to their services and had no in-edge at all, so the graph — asked
the question at the top of this document — answered *"nothing depends on
Authentik"* in the voice of a surveyed node. Fixed by
`derive_authentik_hosting`: the provider object is an object **inside** the
service, and now says so.

Four more survived scrutiny and are fixed:

- **The completeness side could not find what `main.yml` had not heard of.** It
  iterated the three auto-enable blocks, so `mcp_gateway → postgresql` — a
  rendered DSN plus a live `psql` exec, default-ON — was outside the derivation.
  It is now a **sweep** over the service registry: 30 undeclared pairs found,
  **12 declared**, 18 refused by name with reasons.
- **The reachability probe was a substring grep.** It certified
  `gitlab → postgresql` on GitLab Omnibus configuring its *own* bundled
  Postgres, and `onlyoffice → postgresql` on a `/var/lib/postgresql` volume;
  it never popped the Jinja guard stack on `{% else %}`, so moving a live line
  into an else-branch produced a **false RED phrased as an outage**; and it read
  one file per role. Rewritten as `tests/anatomy/service_edge_probe.py` — host
  positions only, full control-flow walk, manifest `domain_var` aliases, every
  template plus `tasks/{main,post}.yml`. Its own failure modes are fixture-tested.
- **23 edges carried identical fields and non-identical backing.**
  `install_gitea` appears in `main.yml` zero times. The compiler now refuses a
  service edge that is neither auto-enabled nor carrying an `unenforced:`
  sentence; 13 of 35 say so.
- **`gitea-base: depends_on: []` claimed to make the node "a root of the layer
  derivation"** while the same artifact carried `authentik:gitea → service:gitea`
  and `roles/pazny.gitea/tasks/post.yml:117-137` guarded the case it calls
  LOCKOUT. Scoped to *no data upstream*; Gitea derives **L1**.

Two more phantom identifiers the R1 sweep found and its write-up did not name —
`freepbx_lan_access` and `sso_autologin_min_tier_2` — are now pinned beside
`install_redis`.

## R2 — `layer`, derived — **SHIPPED 2026-08-07**

`layer` (L0 substrate · L1 platform · L2 application · L3 custom,
`docs/doctrine/layers.md` §3) is longest path over the **service projection** of
the dependency edges — the same arithmetic `graphLayout.ts::rankNodes` runs for
the canvas, with the SSO chain `service:authentik → authentik:<slug> →
service:<x>` collapsed onto its endpoints.

Emitted as a **derived** fact by `tools/anatomy-graph-gen.py::derive_layers`;
`layer:` in a plugin manifest or in `state/manifest.yml` is a gate failure.

**Census: L0 3 · L1 4 · L2 18 · L3 0 · withheld 38.** The refusal is the field's
whole point — a node nobody surveyed contributes nothing to a longest path, and
the arithmetic answers anyway. Measured with it disabled, `service:traefik`
derives **L2** ("failure felt where it happens") about the only edge proxy on
Linux, and `service:grafana` derives **L0 substrate**: same absence of evidence,
opposite verdicts, both stated calmly. **L3 is never emitted** — §3 defines it by
delivery, which is a different axis.

Disagreements, reported rather than tuned away: Nextcloud **L2** exactly as
`layers.md` §5 predicted; **Infisical L2** where §3 lists it L1; **Wing L1**
where §3 lists it L0. In the last two the honest repair is to declare the
missing edges, not to overrule the arithmetic — see `layers.md` §5.

## R3 — face apps: form, not complexity

Split the one overloaded field into two independent ones.

**`form`** — what the thing IS on screen. Four values, and an app has exactly one:

| form | what it is | today |
|---|---|---|
| `view` | a full window over estate data | Anatomy, Tables, Explore, Files |
| `utility` | a focused tool with its own state | Sticky Notes; a finder, a planner |
| `widget` | a small surface that lives inside another | 1 — Anatomy at a glance (2026-08-07) |
| `frame` | a service rendered in an iframe | ~37 hub services |

**`build`** — how hard it is to build, i.e. which organs and which recipe. This
is what `F1`–`F4`/`H` already measures well (`docs/doctrine/face-app-tiers.md`);
it keeps its prefixes and stops pretending to be a taxonomy of form.

The two axes are **independent, and only loosely correlated**. A `frame` will
usually be the cheapest thing to build, but that is a tendency, not a
definition — and the moment the estate has one expensive frame or one trivial
utility, a field that conflated them is wrong about both.

Until 2026-08-07 the face recorded only a binary (`isNative`, "a nos-native
API-calling app rather than an iframe"; plus a `HubApp.native?: boolean` with
zero producers and zero consumers). `form` replaced it — `isNativeApp` is
deleted, `appForm(slug)` is the successor, and the shell's window-body switch
branches on the form.

**SHIPPED 2026-08-07 — `widget` is no longer empty.** It was written above as a
design target with the note that a gate must not assert membership of an empty
set; that is now moot, because the set has one member and it is not a token.
`faceapp:anatomy-widget` ("Anatomy at a glance") reads the seven highest-degree
nodes out of the same graph artifact the Anatomy view uses, joins the live Pulse
state onto them, and opens the Graph view on the node you click. It is itself a
node — `faceapp:anatomy-widget`, degree 3 — with three edges the code performs:
`service:face →` it (mounted at the desktop root),
it `→ faceapp:anatomy` (the click-through), and
`daemon:eu.thisisait.nos.wing →` it (the /bff/pulse projection it polls).
Doctrine: `docs/doctrine/face-app-tiers.md` §Form. Gate:
`tests/anatomy/test_face_app_form_axis.py`.

## R4 — the ontology

R1–R3 all add facts to nodes. They are only worth the effort if the facts are
addressable — that is the difference between a graph and a picture.

- **Every node already carries `anchor` + `description`** (shipped 2026-08-06),
  validated against the 362-anchor spine. New kinds inherit that requirement;
  the gate refuses a dangling anchor.
- **`form`, `layer`, `build` are FACETS of one entity**, not three parallel
  registries. They belong in the genome's entity schema
  (`docs/idea/06-genome.md`), composed with `allOf`, so a fourth adjective
  cannot be added by inventing a fifth file.
- **KEAP import stays blocked on one thing** and it is not effort: a neutral
  object still gets its own line in the nightly corpus diff, so 191 nodes means
  191 benign findings a night until the harness folds them into one counted
  line — and harness changes land after a completed streak, never during one.

## R5 — gotchas, triaged

`CLAUDE.md`'s "Operator gotchas" are six rules of three different kinds, which
is why they read as noise: they are not one category.

| gotcha | kind | disposition |
|---|---|---|
| `{{ vars }}` eager-resolve, stock filters only | **ours, already gated** (`test_config_stock_jinja_only.py`) | **delete from CLAUDE.md now** — the gate is more authoritative than the paragraph. The strategic fix (stop passing `{{ vars }}` wholesale) stays on the 2.24 track. |
| Run removals outside the IDE | **operational, about the human** | move to the operator runbook; it is not a code rule and cannot be gated |
| Rust-slim images ship no `wget`/shell | **foreign property** — no fix exists | doctrine paragraph, citable. Half-covered already: the health probe now separates "the check could not run" from "the service is down" |
| LSIO code-server is HTTP-only on 8443 | **foreign property** | doctrine paragraph; add the gate that `traefik_https_upstream_ids` only names services that actually bind TLS |
| Mkcert CA mount must be guarded | **ours, fixable** | **SHIPPED 2026-08-07** — `tests/anatomy/test_mkcert_ca_mount_is_guarded.py`; the rule is no longer a thing to remember |
| Forward-auth ≠ native-OIDC double-protection | **ours, derivable** | **SHIPPED 2026-08-07** — `tests/anatomy/test_forward_auth_does_not_stack.py`, expressed against today's storage because the `access` facet does not exist yet |

Two die now, two become doctrine, two become work.

### The two work items, shipped 2026-08-07

**Mkcert CA — one real defect, found by writing the gate.** `n8n-base` guarded
its CA mount (line 13) and `NODE_EXTRA_CA_CERTS` (line 37) on
`tenant_domain_is_local` **alone**, with no `install_authentik`. The TLD half is
the one every fragment's comment explains; the missing half is the one that
bind-mounts `{{ stacks_dir }}/shared-certs/rootCA.pem` — a path
`tasks/stacks/core-up.yml:60-69` writes only `when` `mkcert -CAROOT` returned 0
— into a container that had no reason to trust the estate CA. Latent rather than
live: the estate runs a public TLD, so the block does not render there today.
Repaired in the same commit, per repair-before-declare.

The gate keys on the **container path**, derived from the mount lines
themselves, not on an env-var name. The estate already spells this variable six
ways (`NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`,
`AIOHTTP_CLIENT_SESSION_TOOL_SERVER_SSL`, `GF_AUTH_GENERIC_OAUTH_TLS_CLIENT_CA`),
and a name allow-list is the same "remember to add yours" the gate exists to
delete. It also refuses an `{% else %}`/`{% elif %}` branch of a correct guard,
which is the inverse of the guard and would otherwise read as guarded.

**Forward-auth stacking — nothing to fix, and that is the measurement.** 45
routed services, 19 declaring `native_oidc`, 19 carrying edge mode `oidc`.
Corroborated against the running estate rather than the source alone:
`~/stacks/infra/traefik/conf.d/services.yml` renders 42 routers of which 19 carry
`authentik@file`, and the two sets are disjoint. The gate therefore ships GREEN;
it was shown RED by two seeded mutations, one per failure shape — deleting
`grafana: oidc` (the *omission*, which the `proxy` fall-through at
`services.yml.j2:54` silently punishes) and writing `gitea: proxy` (the wrong
entry).

**`access.gate` does not exist**, so the check reads what IS declared:
`traefik_auth_modes` + the plugin `authentik:` blocks + Tier-2 `nginx.auth`, and
it models **all four** attachment paths including the two defaults. Four things
it cannot yet cover are named in its header rather than left to be discovered:
the missing facet itself; a runtime opt-in that flips a service's real mode
without moving either declaration (`paperclip_native_oidc_enabled`, inert
upstream today per `roles/pazny.paperclip/tasks/post.yml:170`); a `native_oidc`
claim whose upstream OIDC **does not exist**, which is the OPPOSITE defect and
leaves the service UNGATED (FreeScout — `freescout-base/plugin.yml:48` against
CLAUDE.md's measured HTTP 404 on both module sources); and auth that Authentik
does not issue (Woodpecker's Gitea OAuth).

Both files refuse their own empty case. The population floors — 20 CA
references, 40 routed services, 15 `native_oidc` declarations, 18 live
attachments — are the 2026-08-07 census minus headroom, so a glob typo or a
rename reports scope loss instead of a green.

## Order, and why

```
R5 (delete + runbook)   ── minutes, no dependencies
R1 service edges        ── everything else waits on this
  └─ R2 layer derived
  └─ R5 mkcert + forward-auth gates
R3 face form/build      ── independent of R1, can run beside it
R4 facets into the genome ── last: it schematises what R1–R3 produced
```

R1 is the bottleneck and it is also the risky one: 71 manifests, a live
bring-up order, and a working imperative declaration that must not be deleted
until the declared one carries weight.

## What this is NOT

- Not a rename sweep. `layer` and `form` are new axes; `tier` keeps its one
  surviving meaning (RBAC) and delivery tier is already retired.
- Not a KEAP import. That is gated on the corpus-diff fold, which is gated on a
  completed agreement streak.
- Not an inventory. No hand-written table of which service is which layer —
  `layers.md` §4.1 refuses it, and this document inherits the refusal.
