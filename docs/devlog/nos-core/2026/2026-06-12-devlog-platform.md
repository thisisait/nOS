---
id: 2026-06-12-devlog-platform
title: "The devlog platform: turning 31,000 lines of archaeology into data"
date: 2026-06-12
namespace: nos-core
summary: "nOS docs had grown to 408 markdown files and ~31k lines where live doctrine sat interleaved with closed-epic archaeology. The fix is the thing you're reading: a namespaced devlog with the repo as source of truth for nos-core, a deterministic bundle compiler, a WordPress sync bot with full Bone audit lineage (actor_id agent:devlog), a /devlog authoring skill, and GitHub Pages publishing on release tags."
tags: [devlog, docs, meta, wordpress]
actors: [pazny, claude]
related: [docs/devlog/README.md, tools/devlog-compile.py, files/anatomy/scripts/devlog-sync.py]
---
## The problem: docs that couldn't forget

A repo that documents its own doctrine aggressively eventually drowns in
it. By June, `docs/` plus the anatomy docs held 408 markdown files and
roughly 31,000 lines — and the dangerous part wasn't the volume, it was the
*mixture*. A file describing how the upgrade engine works today sat next to
the narrative of the day it first broke; CLAUDE.md carried "recently shipped
doctrine" paragraphs that were really blog posts wearing a config file's
clothes. Live contract and historical narrative have opposite lifecycles —
one must stay current, the other must never change — and keeping them in
the same files meant every doc read required carbon-dating.

## The split: doctrine stays, narrative becomes data

The fix draws one line: live doctrine remains plain `.md` under `docs/`,
completed plans go to `docs/archive/`, and **history and narrative move to
the devlog** — namespaced, machine-readable entries with YAML frontmatter,
one file per entry under `docs/devlog/nos-core/<YYYY>/`.

Namespaces decide the source of truth. `nos-core` lives in **this repo**:
files are committed, compiled by `tools/devlog-compile.py` into a
byte-deterministic `state/devlog-bundle.jsonl` (a `--check` mode pinned by
CI catches stale bundles), and synced repo → WordPress on every playbook
run — last run wins, the WP side is disposable. On-site namespaces
(`site`, `tenant/<name>`, `machine/<name>`, `user/<name>`) live in the
WordPress DB and are never committed; `tools/devlog-post.py` flat-refuses
to post into `nos-core`, because a REST-only nos-core post would just be
deleted as an orphan by the next sync. One taxonomy, two custody models,
no ambiguity about which side owns what.

## A bot with a paper trail

The platform eats the platform's own dog food. Every WordPress write goes
through the sync engine or `devlog-post.py` — never raw curl, never the
admin account. The `nos-devlog` machine identity is registered in
`authentik_agent_clients` with scope `nos:devlog:write`; the actual WP
credential is a WordPress Application Password living in
`~/.nos/secrets.yml`; and every sync run emits a `devlog_sync_run` Bone
event with `actor_id: agent:devlog` and a per-run `actor_action_id` — the
same lineage discipline AgentKit established for LLM agents, applied to a
humble blog bot. Orphan deletion is triple-guarded (nos-core category ∧
bot author ∧ absent from bundle) so the sync can never reap a human's post.

Publishing fans out three ways: WordPress on the live box carries all
namespaces; pushing a `v*` release tag fires `.github/workflows/pages.yml`,
which renders nos-core to a static GitHub Pages site (index, entry pages,
RSS) via `tools/devlog-render.py`; and the repo itself stays the canonical,
greppable source.

## Authoring as ceremony

A `/devlog` skill scaffolds entries and enforces the frontmatter contract
(`id` equals the filename stem, forever — a rename is a delete+create, so
don't). The release flow grew a second-level review around it:
`/devlog release` reads the git log since the last tag, consolidates docs,
archives newly completed plans, and drafts the `release-vX.Y` entry — which
*is* the release blog post — before `tools/devlog-release.sh` runs the
mechanical pre-flight.

## Where it stands

The platform ships with its own history seeded: seven backfilled entries
covering the between-release epics — Track Q, AgentKit, the SSO doctrine
lock, the upgrade-engine reckoning, the gov/GDPR batch, the CI filter saga,
and this one. Which makes this the rare meta-entry that is also its own
integration test: if you're reading it on the blog, the compiler, the sync
bot, and the audit chain all did their jobs.
