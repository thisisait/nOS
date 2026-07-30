# nOS genome — organ boundaries, organelles, and a denser corpus

Authored 2026-07-30, out of the morning review of the 07-30 pulse night. Companion to
`docs/plans/cortex-self-core.md` (doctrine) and `docs/plans/cortex-s3-s4-workflow-set.md`
(the v0.10 release lane). Where those disagree with this file, they win and this is
stale.

**Status.** Part 0 code has LANDED (`67792f0c`); its converge is pending. Parts 1–2
are the arc and have not started — nothing in them begins without a separate go.

---


## Part 0 — today, outside the workflow

Two holes, both found by the 2026-07-30 night. Neither waits for the roadmap.

### 0.1 REM-144 — anonymous Traefik API leaks the global password prefix

`vulnerability-scan` (cycle-17 batch-38) found it; I reproduced it by hand from this
session. Unauthenticated `GET`, Host header only:

```
/api/version          → 200   {"Version":"3.6.23","startDate":"2026-07-24T20:34:14Z"}
/api/rawdata          → 200   35 670 bytes — the entire edge topology
/api/http/middlewares → 200   13 middlewares, of which:
      face-edge@file : X-Face-Edge-Token = len 26, begins "kloF"
      wing-edge@file : X-Wing-Edge-Token = len 64, begins "7c62"
```

`X-Face-Edge-Token` is `{{ global_password_prefix }}_pw_face_edge`
(`default.credentials.yml:421`). **It does not leak an edge token — it leaks the
password prefix**, from which every `{prefix}_pw_*` credential in the estate is derived
by construction. `X-Wing-Edge-Token` is 64-hex because `main.yml:1327` regenerates it
away from the prefix template; `face_edge_token` is simply missing from that list,
alongside `bone_secret` and `nos_deploy_hmac_secret` which are both there.

Both tokens exist solely on the premise, written in `middlewares.yml.j2` itself, that
"only Traefik holds this". `X-Face-Edge-Token` is the exact condition under which the
face BFF (`src/hooks.server.ts`) trusts caller-supplied `X-Authentik-*` identity
headers.

**Fixes, in order:**

1. **Take the dashboard off the edge.** Add `traefik` to `traefik_skip_ids`
   (`roles/pazny.traefik/vars/main.yml:119`). `state/manifest.yml:145-153` gives the
   entry both `domain_var` and `port_var`, so `services.yml.j2` auto-derives a
   websecure router with no `authentik@file`, pointed at the Docker host-gateway —
   Traefik proxying around the `127.0.0.1:8082` bind it was meant to be protected by.
   Both gates (`services.yml.j2:35` and `:116`) test `s.id not in traefik_skip_ids`,
   so the id disappears from router *and* service. Fix `vars/main.yml:44`'s comment
   too — "LAN-only via 127.0.0.1 bind" has been false since batch-21.

2. **Stop deriving `face_edge_token` from the prefix.** Added to the `main.yml`
   regeneration group, same guard as its three neighbours.

   **Second half, found while doing it:** `face_edge_token` was also absent from
   `templates/secrets.yml.j2`, so the regeneration alone would have minted a fresh
   token *every run* — churning the middleware render and the face's own env, and
   breaking face auth between renders. Its sibling `wing_edge_token` was in both
   places; this one was in neither. Added to the persistence template too. The
   lesson generalises: "generate it" and "persist it" are two lists, and nothing
   asserts they agree — a Thread D / genome item.

3. **REM-145 rides along.** GHSA-3ccp-42pg-hgv6 (CVSS 4.0 = 7.0, CWE-444 response
   smuggling via proxied CONNECT on the shared keep-alive pool), published 07-27.
   Our `v3.6.23` is the **top of the affected range**; fix is `v3.6.24`. Bump both
   halves — `default.config.yml:1869` and `roles/pazny.traefik/defaults/main.yml:16` —
   per the version-pin-shadow rule.

4. **A gate, so it cannot come back.** SHIPPED as
   `tests/anatomy/test_traefik_exposure_justified.py` (5 assertions). Every routed
   service (`domain_var` + `port_var`, not in `traefik_skip_ids`) that resolves to
   `auth_mode: none` must appear in the new `traefik_auth_none_justification` map —
   a **field**, not a comment. Four entries today (authentik, onlyoffice, rustfs,
   offline_maps), each with a real reason. Three further assertions: the
   fall-through default in `services.yml.j2` must stay `proxy`; justifications for
   services that are no longer routed-and-ungated are rejected as stale; and
   `traefik` must stay in `traefik_skip_ids`.

   **Retro-tested:** removing `traefik` from `traefik_skip_ids` fails two of the
   five — the named regression test *and* the missing-justification test. So the
   gate does catch the exact pre-fix state, which is the only thing that makes it
   worth having. Regenerated from the genome later (§B3).

**Do NOT also set `api.insecure: false`.** `traefik.yml.j2:11` is what creates the
built-in entrypoint on container `:8080`, and `ping: {}` (line 69) rides on it — which
is what `compose.yml.j2:49`'s healthcheck wgets. Turning it off without first
declaring a real ping entrypoint makes the container unhealthy and the STRICT gate
then fails the whole converge. Routing is the correct lever here; a declared ping
entrypoint plus `insecure: false` is a follow-up, not part of this.

**Rotation, honestly.** Both edge tokens regenerate in place. The **global password
prefix cannot rotate without a blank** — every service DB password derives from it.
Fix 2 removes the prefix from the edge surface going forward. Whether the already-
exposed prefix warrants a blank turns on one question I cannot answer from here:
**was 443 reachable from outside this host?** I probed via `--resolve …:127.0.0.1`.
If `pazny.eu` resolves here for anyone but us — Cloudflare origin, LAN, Tailscale —
treat the prefix as disclosed.

### 0.2 The converge

Seven image pins are ahead of the estate, including REM-137 (CRITICAL, the 36-CVE
Gitea 1.27.0 cluster). Order, per the release lane:

```
ansible-playbook main.yml --tags upgrade -e upgrade_service=gitea    # sqlite backup first
ansible-playbook main.yml                                            # the rest
```

Both need the interactive sudo prompt, so they are operator-run — `! <command>` in
this session puts the output here. Run them from Terminal.app or tmux, not the IDE's
integrated terminal (CLAUDE.md run-hardening: RAM pressure from ~50 containers can
kill a GUI app and take the controlling session with it).

**Verify after:** the three anonymous GETs return `404` from the edge;
`127.0.0.1:8082/ping` still `200` and the container healthy; `traefik.pazny.eu` absent
from `/api/rawdata`'s router list (fetched from loopback); `face_edge_token` in
`~/.nos/secrets.yml` no longer matches `_pw_` and is ≥ 32 chars.

### 0.3 Also today, no code

- **Reconcile the security queue.** DONE (`4e19d1b2`). The nightly scan writes into
  whichever checkout it runs in, and batch-38 (REM-144…148) existed only as an
  uncommitted working-tree change in the main checkout — one `git checkout` from
  being gone. *(A correction to the first draft of this section, which claimed two
  divergent **uncommitted** copies: the worktree was clean. The files differed
  because the worktree sits on an older commit. The exposure was real; the
  description was not.)* Still open, and now a Thread D item: decide where the
  scan is allowed to write, deterministically, instead of "wherever it ran".
- **Correct the docs that told us we were fine.** `docs/active-work.md:85-87` and
  CLAUDE.md both claim **"0 CRITICAL pending"**; the live queue has two (REM-137,
  REM-144). Also stale: `cortex-self-core.md:388-393` (sparsity figures) and
  `keap-fable-ontology-review.md` ("PREPARED (not applied)" — it was applied).

---

## Part 1 — the genome

### The problem, in your words

> *Není problém to, že je kód v jiném jazyce a u jiného orgánu, ale to, že nemá
> společného jmenovatele.*

That is the correct diagnosis, and it is measurable. Today the estate has no common
denominator, and the same law is restated by hand in every organ that needs it:

| law | restated in | worst symptom |
|---|---|---|
| RBAC tier → group | **7 places, 5 languages** | `superset_config.py.j2:52-55` reads `.admin` as a dict against a list-of-dicts — a live shape mismatch masked by `\| default()` |
| GDPR Art-30 | 4 declarations | `plugin.schema.json` wants `eu_residency`, `app.schema.json` wants `transfers_outside_eu` — inverse spellings of one fact; `nos_gdpr.py` exists only to paper over it |
| tier visibility enum | 4 copies | `state/keap-tables/*.table.yml` consumes it as an unvalidated string; the test checks only that the key exists |
| face ↔ KEAP contracts | hand-mirrored, **no gate at all** | already drifted: face has 11 `ColumnKind`s to KEAP's 12, every constraint dropped |
| **exposure / gating** | **5 places** | **REM-144** |

Across all eight files in `state/schema/` there is **not one `$ref`, `allOf` or
`$defs`.** Zero composition. The first draft of this plan proposed adding a
`sensitive` boolean — a fifth uncoordinated copy of the same law. Rejected, correctly.

The exposure row is the one that just cost us. "How is service X reached and what
gates it" is declared in `state/manifest.yml` (a router exists), `traefik_auth_modes`
(what attaches), `traefik_skip_ids` (whether to route), the plugin's `authentik:`
block (whether a provider exists to attach), and `authentik_app_tiers` (who may pass).
Nothing compares them. For `traefik` they disagreed, and the only thing tying them
together was a comment that had been wrong for months.

### What the common denominator has to do

Not "be one language" — the estate is deliberately polyglot and will get more so:
PHP in the wing, TypeScript in the cortex organ and face, Python in Bone and the
Ansible modules, a **Rust brain** and a **Python digestion** on the horizon. The
denominator's job is to make those five agree without any of them being authoritative.

Three things, and they are separable:

1. **What an organ is** — its boundary. Declared once, per organ.
2. **What an entity is** — the base nOS entity and the organelles inherited from it.
   Data facets only.
3. **How organs talk** — the wire contract, versioned and gated on both ends.

And a fourth that cuts across all three: **everything gets a taxonomy anchor**, so an
organ, an entity kind and a service are all addressable from cortex-lang. That is what
turns "plugin-like wiring between all services" from a metaphor into an address space.

### The organ boundary

An organ declares:

| field | meaning | precedent that already exists |
|---|---|---|
| `identity` | name, runtime, where it runs (launchd / docker / systemd) | plugin manifests, `state/manifest.yml` |
| `store` | the store it **exclusively** owns | `assertOwnStore()` + `.cortex-store.json` marker — already enforced for the cortex organ, and its e2e asserts it against the **filesystem**, not the server's own account of itself |
| `surface` | routes exposed, and per route: `route` / `gate` / `justification` | **this is the `access` facet — REM-144 lives here** |
| `consumes` | other organs' contracts, at a declared version | `requires.plugin` in plugin manifests; `contracts.selfmodel: 1` handshake |
| `taxonomy` | its anchor node | `ent:`/`org:` namespaces, per `cortex-self-core.md` §6b |

The point of the table is that **none of these five is greenfield**. Each exists as a
working one-off in exactly one place. The genome generalizes four proven mechanisms
rather than inventing a framework.

### The three layers, and what each is written in

**Layer 1 — entity & organelle shapes: JSON Schema, with composition.**
`state/genome/entity.schema.json` declares the base entity via `$defs`; an organelle
is a schema that `allOf`-composes it and adds its kind. Four facets:

- `access` — reachability *and* gating as one fact (route, gate, provider, tier)
- `compliance` — Art-30, **one** spelling, superseding the two divergent copies
- `cortex` — indexed or not, which fields form the embedded body, sensitivity exclusions
- `face` — render hints, today scattered across `hub_card`, table defs and Wing columns

JSON Schema because it is already the estate's format, already gated by the
`contracts-drift` CI job, language-neutral, and `$ref`/`allOf` *is* the inheritance you
asked for. First organelles: `organelle/data-table`, `organelle/row`,
`organelle/service` (which a plugin manifest already half is).

**Layer 2 — organ boundaries: one manifest per organ**, same directory, validated
against `state/genome/organ.schema.json`. This is the layer JSON Schema alone cannot
express, because it describes *interfaces*, not data.

**Layer 3 — the wire.** Generated from layers 1+2 into each runtime, plus a
conformance gate on **both** ends. Per `docs/doctrine/cross-repo-contracts.md`:
*"Symmetry is the whole design. A gate on one side only makes that side the authority
and the other side the supplicant."*

### Why not protobuf / an IDL, and why not a transpiler

An IDL would give real cross-language codegen, and it is the obvious answer. It is
still the wrong one here, for two reasons. It cannot carry the facets — compliance,
tier, cortex indexing, taxonomy anchor are the *whole point*, and in protobuf they
become comments. And it puts a toolchain into five runtimes, one of which (Rust)
does not exist yet, to solve a problem we do not have: we are not optimising wire
bytes, we are trying to stop the same sentence being written five times.

What we should steal from it: **additive-only evolution and an explicit version
handshake.** Both already have a precedent — `contracts.selfmodel: 1` on
`/agent/v1/health`.

A transpiler is likewise the wrong shape, and the estate has already answered this
three times without one:

- KEAP (TS) ↔ Wing (PHP) agree on opcodes via a **hash-compared `cx1:` registry** plus
  a boot gate — Wing *refuses to start* if a published opcode lacks a handler
- error shapes are byte-identical, enforced by
  `tests/anatomy/test_cortex_phase2_uniform_error.py` — **a Python test asserting a PHP
  service matches a TypeScript service's JSON shape**
- `shared/contracts/cortex.ts` is lifted **verbatim** with a provenance header and a
  vendoring gate

The pattern underneath all three is **regenerate-and-diff**, which already runs in four
places (`contracts-drift`, `spine-render.mjs --check`, `lift-xrefs` +
`git diff --exit-code`, `gdpr-dpa-register.py --check`). One declaration, N emitted
artifacts, CI red on drift. Not new machinery — existing machinery, new source.

**The design's own test:** adding a fifth runtime must cost *one emitter*, not a
renegotiated contract. If a Rust brain requires reopening the schema, the genome
failed.

### The one thing that may never be inherited

Both `nos-cortex-lang.md` §2 and the Wing executor §2 state that a capability **must
not be addable by data**. So the organelle splits along the line the language already
draws:

- **facts about an entity** → data, declared once, inherited, generated everywhere
- **what may act on an entity** → code, per runtime, hash-compared, never inherited
  from a manifest and never addable by declaring it

That is exactly the shape you chose — *core generated, edge through a gate*. Our organs
consume generated clients; an external system satisfies the same contract at runtime
through the **Wing executor**, already designed as a capability boundary with
three-axis scoped tokens (`verbs` / `namespaces` / `tenants`).

### The strongest objection, stated fairly

*A generator emitting five languages, gated by drift CI, is a lot of machinery for a
repo that has not shipped its first stable release — and the risk is that the generator
becomes the thing we maintain instead of the estate.*

Real, and it does not win. The machinery is not new (`contracts-drift` already
regenerates and diffs three artifacts across Python and PHP), and the alternative is
not "no machinery" — it is seven hand-kept copies of the tier map, four spellings of
Art-30, and the five-way exposure split that produced REM-144. We already pay the
maintenance; we pay it in incidents instead of in CI.

The mitigation is scope discipline: **B3 migrates one facet**, B5 defers cells
outright. If the generator has not paid for itself after `access`, that is a real
signal and we stop.

---

## Part 2 — threads

Sequencing. Nothing here starts without a separate go.

```
Part 0 (today) ──→ v0.10-beta tag
                       ↓
        A hygiene ─────┐
        B genome       │
        C corpus       ├──→ KEAP tag → pin bump → converge → one night
        D pulse audit ─┘
```

One KEAP tag, one pin bump, one converge — required by C2, and it collapses three
converges into one.

**The streak is not a constraint after the tag.** It was a release gate; it is met at
3. Afterwards it is a regression detector, and B2/C may deliberately zero it once with
a ledger note. The earlier draft treated it as sacred; withdrawn.

### Thread A — hygiene

**A1. The KEAP row-upsert `slug` bug.** `server/agent.ts:731-733` — strip `slug` from
`values` before `upsertRow` **only when** the schema declares no `slug` column.
Unconditional stripping breaks the face config tables, whose `slug` is a real readable
cell (`agent.ts:718-719`). Do **not** reserve `slug` in `validateRowValues`
(`shared/contracts/table.ts:131`) — shared with `/api/tables`, the rustfs driver and
the UI. Human path unaffected. While in the file: `rowSlug` uses `validSlug` (allows
`.`) where the human path uses `assertRowId` (does not) — two id charsets, one column.

**A2. Anchor the seeded fixtures.** `keap-lint` gave an honest verdict on our own test
data: of 27 new findings, **26 are `orphan-object` (info)** — an exact 1:1 match to the
26 fixtures — each *"has no `[[taxonomy]]` anchor — invisible in the universe
(panel/search only)"*. The seeder writes only `fixture`/`title`/`date` frontmatter, so
not one fixture links into the taxonomy. They satisfy the corpus-diff clauses (real
`fs:` objects, 317/317) but exercise only the **flat** corpus, never the
taxonomy-linked path — which is the path Thread C densifies. Add `[[anchor]]`s to
`tools/cortex-seed-fixtures.sh`, `--purge` and re-seed on a converge day.

**A3. `keaptable:business-partners` does not resolve** — the 27th new lint finding,
`broken-content-ref`, medium, unrelated to the fixtures. Diagnose whether the table was
renamed, disabled, or never created.

### Thread B — the genome, built

**B1. Layers 1+2 and the generator.** `state/genome/{entity,organ}.schema.json`, plus
`tools/genome-codegen.py` emitting:

| target | artifact | consumer |
|---|---|---|
| zod | `shared/contracts/entity.gen.ts` | KEAP + the vendored organ |
| TS types | `files/anatomy/face/src/lib/contracts/entity.gen.ts` | face — replaces the mirror that is drifted today |
| PHP | `files/anatomy/wing/app/Contracts/Entity.php` | Wing |
| Python | `files/anatomy/module_utils/nos_entity.py` | the loader, apps_runner |

Gated by regenerate-and-diff inside the existing `contracts-drift` job
(`.github/workflows/ci.yml:267-312`) — it already installs Python 3.13 + PHP 8.5 and
does exactly this for three other artifacts. No new CI infrastructure. Cross-repo
symmetry per `cross-repo-contracts.md`: golden fixture in nOS, consumer gate in KEAP,
version handshake via `/agent/v1/health` `contracts.entity: 1`.

**B2. `syncRows()` — the first organelle, and it is already designed.**
`table-graph-metadata-spec.md` §3.1 carries ratified decision **D3 = materialised**;
`graphMetaSchema` (`shared/contracts/table.ts:291-337`) already accepts
`mode: 'card' | 'rows'` with a full `superRefine`; `server/graph.ts:196-199` states the
gap outright. The work is one function beside `syncCard` (`server/tables.ts:191-233`),
same triggers: `id = table-<slug>:row-<idColValue|rowUuid>`, `type = node.kind`,
`title = row[labelColumn]`, body = compact cell rendering, `visibility = t.visibility`,
`links` via `extractRefs`, `frontmatter = {table,row}`.

Everything downstream is free: `allSources()` (`server/embeddings.ts:63-85`) already
enumerates `db.getObjects` under kind `object`; `hybridSearch` rebuilds FTS from the
same list; `/explore` renders `getVisibleObjects`, which already applies the tier
ladder. Ratify `ROW_OBJECT_CAP` (spec proposes 500, D5-unratified) and reject at enable
time rather than truncating.

**The nightly diff survives it — verified.** `adjudicate_objects` classifies a
KEAP-only object by `if not oid.startswith("fs:")` → `not-a-mirror-row`, withdrawn from
the fs clause. It does *not* key on `type == 'table'`, so row-objects land in the same
neutral class automatically. One follow-up: fold `table-*` and `table-*:row-*` into a
single counted line (as `organ-docs-corpus` already is), or 500 rows means 500 benign
findings. Harness change — land it after a streak completes, never during one.

**B3. Collapse `access` — the exemplary organelle.** RBAC is the right first
organelle, and its exposure half is what REM-144 proved was ungoverned.

*Exposure half, first:* Part 0.4's hand-written gate is regenerated from the schema
instead — every routed service declares `access.route` and `access.gate`
(`none|forward_auth|oidc|header_oidc`), and `none` requires `access.justification`, a
field rather than a comment. `traefik_auth_modes` and `traefik_skip_ids` become
**generated** from those declarations. The gate additionally asserts that a
`forward_auth`/`header_oidc` declaration has a matching Authentik provider in the tofu
registry — the "auth: proxy without a registered provider returns 404" trap that
`vars/main.yml:147` currently warns about in prose.

*Tier half:* generated artifacts replace copies 1–4 (KEAP `rbac.ts`, the vendored organ
copy, Wing's `BasePresenter` constant, face's mirror); `authentik_rbac_tiers` becomes
the declared source with its shape reconciled, fixing the Superset dict-vs-list
mismatch by construction; `state/keap-tables/*.table.yml` `visibility:` becomes
validated.

Compliance, cortex and face facets follow later. Declaring four and migrating one keeps
this reviewable.

**B4. Rows in Grafana — one composition plugin.** Stated plainly because it changes the
estimate: **`observability:` in plugin manifests is 95 % dead metadata.** 41 manifests
declare it; the only atom with a live consumer is `loki.labels.stack`, read by
`_plugin_stack()` (`load_plugins.py:405-416`). `metrics_of_interest`,
`observability.grafana.dashboards`, `alerts`, `prometheus.scrape` — zero consumers
each. Do not plan against it. The path that works is `grafana-wing`'s: mirror it as
`grafana-keap`, `requires.plugin: [grafana-base, keap-base]`, one
`frser-sqlite-datasource` template, mounted read-only. ~60 lines copied from
`plugins/grafana-wing/plugin.yml:60-74`.

**B5. Cells — deliberately not yet.** There is **no per-cell identity in the store**: a
row is one JSON blob in `table_rows.data` read via `json_extract`; history is a
whole-row snapshot per op. The only cell-level addressing is
`table_row_refs.column_key`, and only for `rowRef`. Cells need a new identity scheme
*and* a new history model, with no ratified design. Rows first.

**B6. Two live defects found while surveying.**

- **The `observability.scrape` DAG edge is dead.** `topological_order`
  (`load_plugins.py:203-206`) adds an implicit `prometheus-base` dependency for any
  plugin declaring `observability.scrape`, but reads a *top-level* `scrape`; the only
  declarer nests it as `observability.prometheus.scrape`. Fires for 0 of 41. Fix the
  path or delete the edge.
- **`plugin-wiring-capabilities.md:27` is stale** — records `ui-extension.hub_card` as
  "(none yet)", but `wing-base/plugin.yml:116-118` harvests it, `:136-139` renders
  `hub-cards.json`, and `HubCardRepository.php:8-11` reads it. The document whose whole
  job is truth about live-vs-forward is wrong on one row.

### Thread C — LLM corpus densification

Yes, and it breaks nothing **if it goes through git and lands after the tag**.

**C1. The two branches you named are the sparsest — measured.**

| branch | nodes | authored (`ext`) |
|---|---:|---:|
| `11.01` **File Formats** | **6** | **0** |
| `11.02`–`11.05` (Compression, Encryption, Backup, Recovery) | 5 each | 4 each |
| `02.02` **Computer Science** | 94 | **10** |
| ↳ AI / Security / Databases | 6 each | 0 |
| ↳ Computer Graphics | **1** | 0 |

`11.01` is pure spine — the 2026-07-26 wave filled `11.02`–`11.05` and skipped it
because it already had five seed children, so it never read as "empty". In a knowledge
base *about preservation*, File Formats is the weakest branch in the corpus. Also
sparse: `01.05` Astronomy (6/0), `02.03` Logic (4/0), `03.01` Engineering (51/0).

**C2. The route — git SoT, not the API. This is the hard constraint.** Adding nodes
only via `/agent/v1/taxonomy/propose` makes KEAP's node-id set diverge from the
organ's → `clauses["taxonomy"]` False → **`agreeStreak = 0`**, every node reads as
`keap-ahead-of-pin`, and 300 proposals means 300 moderation rows. The organ never reads
KEAP (`cortex-store.ts:31-32`). So:

1. author into `knowledge/canonical/<L0-dir>/<L1>.json`
2. `node knowledge/lint.mjs` — `en` 20–2000 chars, `cs` ≤ 2000, no Cyrillic,
   `level == id depth`, global id uniqueness
3. `node knowledge/roundtrip.mjs` — ingest ∘ dump byte-identical
4. commit, tag KEAP (**the same tag as A1 + B2**)
5. bump `keap_repo_ref` + `keap_version` (both halves)
6. **re-vendor** into `files/anatomy/cortex/knowledge/canonical/`
7. converge — rebuilds KEAP via `ingest.mjs`, `store:materialise` re-ingests the organ

Steps 6–7 are not separable: the referee is literally the set of node ids in this
checkout's `canonical/` tree (`cortex-corpus-diff.py:598-624`). Skip the re-vendor →
`both-behind-pin`, parity flips to NOT PINNED. Skip KEAP → `keap-ahead-of-pin`, clock
zeroed.

Two traps: **`ingest.mjs` wipes and re-inserts a whole L1 subtree per file** — a partial
patch deletes every `11.01.*` node not in it, including layout points, so files must be
authored complete. And **never touch `spine/`** — L2+ `ext` nodes append safely
(`appendExtNodeToLayout`); a spine edit re-bakes positions and breaks the pinned
`onto1:76d1f3ad728b382b` gate. `11.01.*` and `02.02.*` children are L3/L4, so safe.

**C3. Scope.** Two files, authored complete, ~100–130 new `ext` nodes: `11.01.json`
(5–8 children under each of Document / Image / Audio / Video / Archive, ≈30–40) and
`02.02.json` (depth on AI, Security, Databases, OS, Networks, SE, Graphics, ≈70–90,
matching the shape `02.02.11` established). Each node needs
`id / level / parentId / name / zone / ordinal / kind: ext / en / cs`. The `en`
description is the real work and the real value — it is what gets embedded and what the
router answers from. House style: `files/anatomy/agents/curator.yml`.

The curator agent does **not** do this — P0 emits `desc`-kind proposals only;
`node-edit`/`node-delete`/`relation` kinds are unbuilt (`promotions.ts` `decide()`
dispatches only `node`, `desc`, `brief`).

### Thread D — pulse and scheduled jobs, a full revision

Documented now, planned now, executed as its own arc. The trigger:

**`security-drift-watch` posts its verdict to the wrong service, and this is the third
instance of one defect.** Not a credential problem — `WING_EVENTS_HMAC_SECRET` is
correctly wired to `{{ bone_secret }}` (`files/anatomy/agents/conductor.yml:123`),
identical to the jobs that work. The URL is wrong: `conductor.yml:122` sets
`BONE_API_URL: "http://127.0.0.1:9000"`. **9000 is Wing** (`default.config.yml:816`);
**Bone is 8099** (`default.config.yml:209`), and Bone is what verifies the HMAC on
`/api/v1/notifications`. The signed POST lands on a service with no verifier → 401.
`drift-watch.sh:28`'s own fallback default hardcodes 9000 too.

The same defect was found and fixed **twice on one day** in two other manifests, whose
comments say so: `plugins/gitleaks/plugin.yml:64-77` — *"9000 is WING… it is Bone that
verifies the HMAC… every other caller in the estate already defaults to 8099; this
manifest was the sole outlier"* — and `plugins/authentik-tofu-drift-base/plugin.yml:68-70`
— *"the gitleaks manifest for the same defect, found the same day"*. `security-drift-watch`
was added later and never got the fix. The comment claiming sole-outlier status was
already false when written, and nothing checked.

So this is not a bug to patch, it is a surface to audit. Scope:

1. **Env wiring** — no manifest may hardcode a Bone/Wing port literal; assert every
   `BONE_API_URL` under `files/anatomy/{agents,plugins}/**` renders through
   `{{ bone_port }}`. Three occurrences and two prose warnings did not stop the third.
2. **Failure semantics** — *a step that cannot do its job must not exit 0.* Three
   instances on the books: the drift hook that parsed nothing (fixed 07-28), its
   notification that delivers nothing (this), and the Linux wet-test passing
   `0/0 ready` on an empty stack (`hidden_fees/08`). One paragraph into
   `docs/hidden_fees/07`, which already owns the "messages that outlive their mode"
   class — same disease, wider blast radius.
3. **Delivery** — for every job, who actually receives its output, and is that path
   tested? Two silent-delivery failures in a row says no.
4. **Ordering** — the nightly feeder chain (`keap-consolidate` → `cortex-fs-sync` →
   `keap-embed-sync` → `keap-features-sync` → `cortex-corpus-diff`) is load-bearing and
   encoded only as cron minutes. Make the dependency explicit or prove the spacing.
5. **Paused inventory** — 9 agent jobs sit paused under the on-demand doctrine. Confirm
   that is still the intent per job, or retire them.
6. **A job is an organelle** — it has an owning organ, a schedule, a delivery target
   and an access facet. Once B1 lands, the pulse catalog is a natural second consumer
   of the genome, which is what would have made item 1 structural instead of a lint.

---

## Verification

- **Part 0** — the three anonymous GETs `404` from the edge; `127.0.0.1:8082/ping`
  still `200`, container healthy; `face_edge_token` ≥ 32 chars and free of `_pw_`; the
  manifest↔auth-mode gate goes red if `traefik` leaves `traefik_skip_ids` without
  gaining a gate.
- **A1** — `e2e/agent-tables.spec.ts` keeps passing for the slug-column table; add a
  case for a table without one.
- **A2** — after re-seed, the next `keap-lint` reports **0 new `orphan-object`** and 26
  resolved.
- **B1** — `contracts-drift` regenerates all four artifacts and fails on drift; plus a
  deliberate-drift test (hand-edit one generated file, prove CI goes red). Cross-repo:
  golden fixture + KEAP consumer gate + `contracts.entity` handshake.
- **B2** — `e2e/table-graph.spec.ts:181-185` ("no per-row node objects") inverts and
  becomes the Stage-2 assertion.
- **B3** — one test asserting all four generated tier artifacts agree (the Superset
  mismatch must fail before the fix and pass after), plus the exposure gate
  **retro-tested against the pre-Part-0 `traefik` declaration** — it must fail on that
  input, or it does not do what it claims.
- **B4** — a Grafana explore query against the new datasource returns table rows.
- **C** — `lint.mjs` + `roundtrip.mjs` green before the tag; after the converge,
  `cortex-corpus-diff.py --no-ledger` reports parity **PINNED**, `taxonomy exact`, six
  clauses AGREE, counts moving together (2500 → ~2600 KEAP, 3588 → ~3690 organ).
- **D** — the env-wiring gate goes red against the current `conductor.yml:122`; forcing
  the notification endpoint to 401 makes the job exit non-zero.
- **Estate** — `tools/ci-local.sh` before any release push.

## Not in scope

Cell-level identity (B5). Migrating the compliance, cortex and face facets (B3 does
`access` only, deliberately). Building the Wing executor — organelles need the
*registry* (data) now and the *gate* (executor) only when an external system first asks
to implement one. A full plugins→organelles rename: ~1 000 occurrences and 8
hard-breaking identifiers including two `wing.db` columns and the `pulse_jobs.id`
composite format — the new word applies to the new layer only, and the old name keeps
living meanwhile.
