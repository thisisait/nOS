# KEAP self-model — nOS architecture as a knowledge tree

> Status: design + implementation, 2026-07-17; **real-state refinement 2026-07-18**
> (cards now carry each service's actual version/image/port/domain/… resolved from
> the live vars, not generic prose). Role: `pazny.keap`
> (`tasks/selfmodel.yml` + `files/anatomy/scripts/keap_selfmodel_gen.py`).
> Gate: `tests/anatomy/test_keap_selfmodel.py`.

## Goal

Make the playbook idempotently write a knowledge tree describing **nOS's own
architecture** (platform → stack → service) into the KEAP-mounted filesystem, as
`dataPoint` files, so KEAP's `server/fs-sync.ts` mirror ingests them "almost by
itself": the cards appear in the `/explore` ring (files core) as a standalone **nOS**
constellation, are embedded into vector space (found by `/agent/v1/search/semantic`),
and each card is anchored into the KEAP taxonomy so it gets its own rays.

## What KEAP v1.7.0 actually does with a file (the contract we build to)

Verified against `keap_repo_ref: v1.7.0` (`/Users/pazny/keap/src`, byte-identical to
the tag). Source: `server/fs-sync.ts`, `server/objects.ts`, `server/graph.ts`, `db.ts`,
`src/game/data/taxonomy.ts`.

A file at `KEAP_USER_FILES_DIR/<uid>/<top>/<rel>` becomes one knowledge object **iff**
`<top> ∈ KEAP_FS_SYNC_DIRS` (default `documents,library,inbox` — a **hard filter**,
`fs-sync.ts:167-172`). The object is:

| field | value | drives |
|---|---|---|
| `id` | `fs:<uid>:sha1(relPath)[:16]` | identity (hashed uid-relative path, `fs-sync.ts:187`) |
| `title` | `basename(relPath)` (incl. `.md`) | label |
| `description` | `dirname(relPath)` (uid-relative) | **embedding** + label |
| `tags` | `[relPath.split('/')[0]]` (the top dir) | **embedding** (not appearance) |
| `body` | text excerpt ≤4000B (md/txt/rst/adoc/csv/tsv only) | **embedding** |
| `type` | by extension (`.md`→`page`) | **appearance** (form/glyph/hue) |
| `frontmatter` | `{source:'fs', path, size, mtime}` | idempotency |
| `links` | `prev.links ∪ extractRefs(body)` | relations (see below) |
| `visibility` | **hardcoded `'private'`**, owner = the `<uid>` dir | **who sees it** |

**Idempotency:** a pass skips a file when `size` **and** `mtime` are unchanged
(`fs-sync.ts:190`). The generator's compare-and-skip preserves mtime on unchanged
content → no re-embed storm.

**What renders as connection in the ring** (`graph.ts` `/api/graph`):
1. **Taxonomy anchors** — `extractRefs` (`objects.ts:37-49`) parses `[[ref]]` from the
   **body**; `classifyRef` promotes a dotted 2-digit id (`NN.NN`) to a **taxonomy node**
   anchor iff `getNode(id)` exists. `graph.ts:194` emits those as **rays** tethering the
   card to its taxonomy star. **This is the relation model we use** (operator decision 2).
2. **Folder constellations** — the files-core view folds objects into `dir:` clusters by
   `frontmatter.path`. Our `nOS/<stack>/<service>.md` shape gives each stack its own
   cluster for free.
3. **Semantic proximity** — `objectText = type+title+description+tags+body` is embedded
   (nomic-embed-text 768-d) by the host `keap-embed-sync` Pulse job.

> **Note — object→object links don't draw (yet):** `[[object:<id>]]` refs are extracted
> and **stored** in `o.links` (survive the curation union, show in the DetailPanel data-
> links + the object API AgentKit reads) but `/api/graph` only surfaces `kind:'node'`
> anchors as drawn edges. We author the `belongs-to`/`depends-on` cross-links as
> `[[object:fs:<uid>:<hash>]]` anyway — correct forward-compatible OKF encoding that
> lights up as ring edges the day KEAP surfaces object-links, and useful in the detail
> panel + agent API today. Visible connectedness today = taxonomy rays + folder fold +
> semantic proximity.

## Decision — class-2 shared storage + taxonomy-node anchors (operator override)

**Storage = doctrine class-2 shared content**, not a per-user tree and not a fake user on
disk. The tree is generated to:

```
{nos_data_root}/tenants/{nos_tenant_slug}/shared/nos-docs/nOS/
├── _platform.md                       # platform root card
└── <stack>/
    ├── _stack.md                      # per-stack card
    └── <service>.md                   # per-service card
```

This matches `docs/doctrine/filesystem.md` class 2 ("app-managed multi-user content →
`tenants/<t>/shared/<svc>/`"): role-generated, regenerable, belongs to the tenant, not to
any one user. **Nothing is written under `users/<uid>/`.**

**Reaching fs-sync without a KEAP source change.** KEAP v1.7.0 has exactly **one** file-
scan root (`KEAP_USER_FILES_DIR`) and **one** shape (`<uid>/<top>/…`) — there is **no**
`KEAP_SHARED_FILES_DIR` env and **no** folder-mapping admin API (only the single-capture
`/ingest/v1/capture` device route). So the class-2 tree is **presented** to fs-sync as a
reserved uid via a nested read-only bind-mount (`compose.yml.j2`):

```yaml
- {{ keap_selfmodel_root }}:/user-files/{{ keap_selfmodel_uid }}:ro   # nos-docs
```

and `KEAP_FS_SYNC_DIRS` gains the top-class `nOS` (`keap_fs_sync_dirs` default now
`documents,library,inbox,nOS`). fs-sync then walks `/user-files/nos-docs/nOS/**`, tags
every card `nOS`, and files them into a standalone `nos-docs`-owned constellation.
**No KEAP source change, no manual admin step** — a blank ingests it automatically.

### Relations — taxonomy-node anchors (real KEAP node-ids)

The nOS constellation anchors into the **Computer Science** branch of the KEAP taxonomy
(`src/game/data/taxonomy.ts`, all ids verified real):

| node-id | name | used for |
|---|---|---|
| `02.02` | Computer Science | **whole-map anchor on every card** |
| `02.02.04` | Software Engineering | devops (gitea, gitlab, woodpecker, code-server, paperclip) |
| `02.02.05` / `.01` / `.02` | Databases / Relational / NoSQL | mariadb, postgresql, influxdb / redis |
| `02.02.06` | Operating Systems | infra substrate, storage |
| `02.02.07` | Computer Networks | traefik, tailscale, bluesky_pds, voip |
| `02.02.07.04` | Web Technologies | iiab/b2b web + content services |
| `02.02.08` | Computer Security | authentik, infisical, vaultwarden |
| `02.02.09` | Artificial Intelligence | open-webui, n8n, mcp_gateway, hermes, openclaw, opencode |
| `02.04` | Information Theory | observability / metrics / telemetry |

Each `<service>.md` body carries `[[02.02]]` (whole-constellation ray) **plus** one
category ray (mapped by manifest `category` → stack → CS root). Stack/platform cards
anchor at `[[02.02]]`. Plus the forward-compatible `[[object:…]]` `belongs-to`
(service→stack), `depends-on` (service→authentik when `oidc ∈ native|proxy`, extensible
via `keap_selfmodel_deps`), `part-of` and `contains` cross-links.

### Metadata source — role-owned, real playbook state (operator refinement 2026-07-18)

Three role-adjacent sources join into each card, so the tree reflects the **real** state
of the playbook, not generic prose:

1. **Spine** — `state/manifest.yml` per-service row: `stack` (the only machine-readable
   stack membership), `rbac_tier`, `oidc`, `category`, `image`, and the **var-name
   declarations** `version_var` / `port_var` / `domain_var` / `data_path_var` (each
   service declares where its own facts live — a role-adjacent pointer, no naming
   guesswork).
2. **Prose** — per-plugin `files/anatomy/plugins/<svc>-base/plugin.yml`
   (`ui-extension.hub_card.title` → display name, `hub_card.description` /
   top-level `description` → the human sentence). Role-owned: each service's plugin owns
   its own card prose. 55/60 carry a plugin; the 5 host-native tools synthesize one.
3. **Real deployed state** — `roles/pazny.keap/tasks/selfmodel.yml` resolves the actual
   values in **Ansible/Jinja** against the live var hierarchy via
   `lookup('vars', <manifest var name>)` (version/port/domain/data-path) + the
   `<id>_mem_limit`/`<id>_cpus` convention, and passes them as `--facts-json`. The card
   gets a **`## State`** section (Image, Version, Domain, Port, Data path, Memory/CPU
   limit — only those present) **and** a real-state sentence folded into the description
   (`… Deployed as gitea/gitea:1.26.4, https://git.pazny.eu.`), so the ACTUAL deployment
   is in the embedded body and found by semantic search. A fact that is unset on this
   host's config resolves to `''` and is simply omitted.

Why Ansible resolves the facts (not the Python generator): the values are Jinja-only
(`{{ gitea_domain | default('git' ~ …) }}`) — only Ansible sees the full var hierarchy.
The generator stays offline/deterministic and just embeds what it's handed.

**All 60 services** are emitted (full architecture, toggle-independent → stable content);
`stack: null` host-native services bucket under a `host` pseudo-stack.

## Idempotency

`keap_selfmodel_gen.py` writes a card only when its rendered bytes differ (compare-and-
skip) and prunes stale `.md` under `nOS/` it no longer generates. Content is fully
deterministic (sorted, no timestamps/random) — and the real-state facts are resolved
config values (pinned versions, ports, domains), stable across runs — so a re-run against
an unchanged catalog + facts writes zero bytes → fs-sync's `size+mtime` check skips every
file. (Bump a version pin / port / domain and only that service's card rewrites.) `ansible.builtin.command`
`changed_when` keys off the generator's `created+updated+removed` JSON summary.

## OPEN KEAP-side decision — all-tenant-user ring visibility (Option C)

**What ships today (no KEAP change):** the self-model is auto-ingested, taxonomy-anchored,
and embedded. It is visible in `/explore` to the **operator/admin** (`getObjects` runs
with `seeAll`) and reachable by any **agent token that carries `seeAll`**, and its text is
in the embedding for search.

**What it CANNOT do without a KEAP source change:** render in **every non-admin tenant
user's** ring as a shared constellation. Two v1.7.0 facts block it, and no env/API/mount
works around them:

1. `fs-sync.ts` hardcodes `visibility:'private'`, owner = the `<uid>` dir (`fs-sync.ts:214`).
2. `db.getObjects(userId, seeAll)` — the `/api/graph` **list** — returns only
   `user_id = requester` for non-admins; it does **not** include `visibility='shared'`
   (`db.ts:765`). (Search's `canReadObject` *does* honor `'shared'`, but the ring list
   does not, and nothing sets `'shared'` anyway.)

So "class-2 shared, visible to **all** tenant users" (the operator's framing) requires a
small **KEAP change** — Option C — roughly:

- teach `fs-sync.ts` a system/shared root (or a `visibility:'system'` for a reserved uid),
  **and**
- include system/shared objects in `getObjects` / the `/api/graph` payload for every user.

That is ~2 focused edits in the KEAP repo (`thisisait/nos-keap`), not an nOS change. It is
**reported, not implemented** here per the design-first brief (no KEAP source change in
this task). Until then, the nOS-side generator + mount deliver the admin/agent-visible
self-model; the moment KEAP surfaces system-owned objects to all users, the exact same
tree renders for everyone with **zero nOS change**.

## Files

- `files/anatomy/scripts/keap_selfmodel_gen.py` — the generator (offline-testable).
- `roles/pazny.keap/tasks/selfmodel.yml` — thin wrapper, included from `tasks/main.yml`
  behind `keap_selfmodel | default(true)`.
- `roles/pazny.keap/templates/compose.yml.j2` — the reserved-uid bind-mount.
- `roles/pazny.keap/defaults/main.yml` — `keap_selfmodel*`, `keap_fs_sync_dirs` (+`nOS`).
- `tests/anatomy/test_keap_selfmodel.py` — offline gate.
