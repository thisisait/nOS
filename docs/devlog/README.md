# nOS devlog — narrative history as data

The devlog is where nOS **history and narrative** live (live doctrine stays as
`.md` under `docs/`; completed plans go to `docs/archive/`). Entries are
namespaced, machine-readable, and presented three ways: WordPress on the live
box (all namespaces), GitHub Pages (nos-core only, published on release tags),
and the repo itself (nos-core source files).

## Namespaces

| Namespace | Source of truth | Who writes |
|---|---|---|
| `nos-core` | **This repo** — `docs/devlog/nos-core/<YYYY>/*.md`, compiled to `state/devlog-bundle.jsonl`; the playbook syncs repo → WordPress (last run wins, the WP side is disposable) | Operator + agent via `/devlog new` (files, committed) |
| `site` | WordPress DB on the live box | `/devlog post` → `tools/devlog-post.py` |
| `tenant/<name>` | WordPress DB | same |
| `machine/<name>` | WordPress DB | same |
| `user/<name>` | WordPress DB | same |

On-site namespaces are **never committed**; `tools/devlog-post.py` refuses
`nos-core` (a REST-only nos-core post would be deleted as an orphan by the next
sync). In WordPress, namespaces map to stock categories under parent `devlog`
(`/` flattened to `-`, e.g. `tenant/acme` → `tenant-acme`).

## Entry format (nos-core)

One file per entry: `docs/devlog/nos-core/<YYYY>/<YYYY-MM-DD>-<slug>.md`.

```yaml
---
id: 2026-06-12-opentofu-authentik-cutover   # REQUIRED = filename stem; never changes, never rename
title: "OpenTofu becomes the Authentik authority"  # REQUIRED
date: 2026-06-12                             # REQUIRED — ISO publication date
namespace: nos-core                          # REQUIRED — must be nos-core for committed files
summary: "One-paragraph abstract; used as WP excerpt + index blurb"  # REQUIRED
tags: [authentik, opentofu]                  # optional, lowercase-dash
release: v0.6-beta                           # optional — ties entry to a tag
updated: 2026-06-13                          # optional — set on edit
status: published                            # optional; draft = excluded from bundle
actors: [pazny, claude]                      # optional
related: [docs/opentofu-authentik-cutover.md]  # optional repo paths / URLs
---
Markdown body…
```

The WordPress post slug = `id`. Edits change content, never the id; a rename
is a delete+create (the sync's orphan logic handles it, but don't).

## Pipeline

1. **Author** — `/devlog new` scaffolds the file; write the body.
2. **Compile** — `tools/devlog-compile.py` validates every entry and rewrites
   `state/devlog-bundle.jsonl` (byte-deterministic; `--check` verifies
   freshness — pinned by `tests/anatomy/test_devlog_bundle.py`). Commit both.
3. **Sync** — every playbook run (`--tags devlog` for just this) runs
   `files/anatomy/scripts/devlog-sync.py`: upserts bundle entries into
   WordPress via REST as the `nos-devlog-bot` user and deletes orphans
   (triple-guarded: nos-core category ∧ bot author ∧ absent from bundle).
   Emits a `devlog_sync_run` Bone event (`actor_id: agent:devlog`).
4. **Publish** — pushing a `v*` tag fires `.github/workflows/pages.yml`:
   `tools/devlog-render.py` renders nos-core entries to a static site on
   GitHub Pages (index + per-entry pages + RSS).

## Release ceremony

`/devlog release` = the 2nd-level review before a release: read
`git log <last-tag>..dev` + session devlogs, consolidate docs (archive newly
completed plans), draft/refresh the `release-vX.Y` entry (this IS the release
blog post), update `RELEASE.md`, recompile the bundle. Then
`tools/devlog-release.sh vX.Y-beta` runs the mechanical pre-flight and prints
the remaining release checklist (ci-local → PR → admin merge → tag →
gh release).

## Audit doctrine

Every WordPress write goes through `tools/devlog-post.py` or the sync engine —
never raw curl, never the admin account — so each write lands in `wing.db`
`events` with `actor_id: agent:devlog` and an `actor_action_id` per run.
The `nos-devlog` machine identity is registered in `authentik_agent_clients`
(scope `nos:devlog:write`); the WP credential is a WordPress Application
Password persisted in `~/.nos/secrets.yml` (`wordpress_devlog_app_password`).
