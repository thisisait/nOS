---
id: 2026-07-20-release-v0-9-beta
title: "v0.9-beta — nOS grows a face, and the cortex learns itself"
date: 2026-07-20
namespace: nos-core
summary: "175 commits in the seven days after the cortex GA. Two of them change what nOS *is*: the web-desktop (nOS face) becomes a real window manager with native apps over Bone's VFS, and KEAP gains a self-model — a knowledge tree describing nOS's own deployed architecture, generated from live state and mirrored into the star-map. Around them the lifecycle closes (blank gained a matching uninstall), the constitution layer lands (docs/doctrine/ + a single-source path resolver), a run stops being wedgeable by its own telemetry, and the security queue reaches zero CRITICAL pending."
tags: [release, nos-face, keap, cortex, doctrine, lifecycle, resilience, security]
release: v0.9-beta
actors: [pazny, claude]
related: [RELEASE.md, docs/doctrine/filesystem.md, docs/doctrine/observability.md]
---

`v0.8-beta` shipped the cortex at 1.0 — a knowledge organ, populated and wired,
that nobody could *look at* except through a browser tab. `v0.9-beta` is the
answer to that: nOS grows a **face**, and the cortex grows a model of the
machine it lives in.

## The face — a desktop, not a dashboard

`nOS face` existed at v0.8 as a vendored SvelteKit shell. It ends this arc as a
window manager: snap and tiling (thirds, 2×2, live gutters), a dock unified with
the app list, drag-to-top layout picker, live taskbar thumbnails, a Ctrl+Space
command palette, and a control panel with wallpapers.

What makes it a desktop rather than a launcher is the **native app framework**
sitting over Bone's VFS. Three apps ship on it:

- **Files** — a real file-picker against `nos_data_root`, on VFS copy/delete
  endpoints that are root-guarded and fuzz-corpus tested.
- **Tables** — a DataTable editor with a *gated write layer* (RowEditor, KEAP
  RW token), plus `CreateTableModal` so tables are made from the desktop.
- **Explore** — the KEAP star-map, embedded.

Every other service opens as an **iframe window** (`ServiceFrame`) rather than a
new tab, which is also what fixed the always-empty dock: Wing was being keyed on
`id` where the hub emits `slug`, so the desktop rendered zero of 37 services.

## The cortex learns itself

The knowledge organ turned inward. `keap_selfmodel` generates a deterministic
knowledge tree — platform → stack → service — **from real deployed state**, with
auto-derived SSO→authentik dependency edges, writes it into a doctrine class-2
shared directory, and bind-mounts it as a reserved fs-sync uid. KEAP's fs-sync
mirrors it into a standalone "nOS" constellation in `/explore` and embeds every
card into vector space. nOS's architecture is now a navigable, semantically
searchable region of its own star-map.

Alongside it, the knowledge pipeline matured through nine KEAP releases
(v1.6.2 → v1.17.2):

- **Git-SoT ingest** — the live DB is populated *from git*, idempotently, by the
  role: `knowledge/canonical/` is the source of truth, `ingest.mjs` the single
  import (per-file sha256 markers), round-trip identity CI-gated. Data changes
  ride the git ref; no image rebuild.
- **Semantic lens** — exemplar axes, centrality, clusters, computed by a Pulse
  job into a derived `node_features` layer.
- **Linked data** — a Wikidata resolver landing QID + entity typing + QRank
  scope onto the taxonomy, behind three disambiguation guards (search-description
  allow/deny, P31 publication reject, embedding cosine veto) because the naive
  top-hit approach measured ~40% and was homonym-trapped.
- **Curator + Track R3** — a propose-only taxonomy reconciler agent, then typed
  cross-domain relations with a classifier fed the whole card.

## The lifecycle closes

A blank run could always wipe and reinstall. It could not *leave*. This arc adds
**`uninstall`** — `-e uninstall=true` dry-runs by default, `+ confirm_uninstall=true`
executes, removing source trees and anatomy runtime dirs.

That work started from an operator catching real drift: a 2026-04-20 screenshot
and a duplicate KEAP table survived `blank=true`. Root cause was structural —
the blank allowlist is hand-maintained, never wiped `tenants/` user-files, and
missed services entirely. Fixes: blank wipes KEAP's derived `/data`, removes the
OpenClaw gateway daemon, and — the subtle one — **uids are keyed on username
with a Czech-safe diacritic-folding slug**, because an unstable uid across blanks
orphans the whole tree it owns.

## A run you can't wedge

A callback↔Bone HMAC secret desync made every telemetry event 401, spilling to
an unbounded `/tmp` SQLite that an IDE indexer had locked — and a release blank
crawled for minutes per task. The fix is defensive in three layers: a
**circuit-breaker** (now half-open, so a transient outage doesn't kill the whole
run), a capped ring buffer on the fallback path, and 4xx-no-retry. The root
cause — a callback signing with an un-rendered `{{ … }}` URL and a
self-referential secret template — is fixed, and Bone **self-heals** a stale env
secret inline.

Three more classes of silent wedge closed: an **external-volume mount preflight**
(a remounted SSD leaves Docker's VM a stale `/host_mnt` ref → every bind-mount
fails and the STRICT health-wait hangs ~20 min with no clue; now probed before
the first `compose up`, with a blank-time Docker restart + re-probe), **dnsmasq
actually being started** (a blank had been shipping with DNS down), and a
**systemic-failure smoke gate** that fails a run when the platform is broadly
dead instead of reporting per-service noise.

## The constitution layer

`docs/doctrine/` is new and deliberately different from `docs/plans/`: doctrine
is *law*, not a proposal. It opens with `filesystem.md` (the storage classes) and
`observability.md` (written out of the telemetry incident above). The
code-side counterpart is `nos_data_root` — a **single-source path resolver** that
ends the scattered per-role path guessing, with the service-engine path surface
completed on top of it.

## Hardening, in a list

- **Healthcheck coverage** — 12 health-blind services gained a `HEALTHCHECK`,
  plus a coverage gate so a booted-but-broken container stops passing as ready.
- **macOS 27 "Golden Gate"** — forward-compat preflight and greppable
  `# VFS-DOCTRINE` markers on the three VirtioFS workarounds.
- **Security → 0 CRITICAL pending.** REM-127 (Traefik ForwardAuth underscore-header
  strip bypass — `X_authentik_groups` survives `Header.Del`, i.e. identity forgery
  on the SSO gate) closed at v3.6.23. REM-002 Woodpecker resolved. Pin wave
  batches 1–3. `wing.db` "database is locked" fixed by a `busy_timeout` on all 13
  writers. WordPress CVE-2026-63030 mitigated by blocking the REST batch endpoint
  after the fixed upstream turned out not to be dockerized yet.
- Fixes worth naming: Nextcloud's OIDC provider registered *with literal quotes*
  (SSO silently dead), Gitea's OIDC discovery failing because the container had no
  `auth.<tld>` host mapping, PostgreSQL healing dir-mounted/empty SSL cert paths,
  and Bone's launchd fd limit 256→8192.

## What this tag is not

The roadmap had pencilled v0.9 in as "epic acceptance" — PG 16→17 cut over
end-to-end, the first real migration authored *and* applied, blank reproducibility
re-proven. None of that is in this tag. Those criteria move to the RC, and the
honest reason is that they are operator-gated live converges, and holding a
175-commit arc hostage to them reproduces exactly the release-debt pattern that
left master six weeks stale earlier this month.
