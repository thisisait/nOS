---
id: 2026-05-30-upgrade-engine-first-real-apply
title: "The upgrade engine had never actually run — and the day it did"
date: 2026-05-30
namespace: nos-core
summary: "The --tags upgrade apply path passed every dry-run for weeks while being completely broken: dry-run returned success before ever touching a handler. The first real apply failed 8/8 recipes in 0.2 seconds each, kicked off a day of structural fixes — a module-side Jinja2 render layer, an exec.shell bridge, topology corrections — and surfaced a near-miss where lookup('vars') without wantlist=true had rendered the PostgreSQL wipe as rm -rf //*."
tags: [upgrades, ansible, incident]
actors: [pazny, claude]
related: [docs/roadmap-2026q2.md, upgrades/]
---
## A verify that verifies nothing

nOS ships per-service upgrade recipes — `upgrades/<service>.yml`, with
`pre` / `apply` / `post` / `rollback` phases — and an engine
(`tasks/upgrade-engine.yml` + `nos_migrate.py`) to run them. The engine had
a dry-run mode, and the dry-runs were green, so the recipes were "verified".

On 2026-05-30 the apply path ran for real for the first time. All 8 recipes
failed, each in about 0.2 seconds. The reason the dry-runs had lied:
`_run_phase` returned success *before* calling the handler when `dry_run`
was set. Dry-run validated that a handler name existed — never token
rendering, never key contracts, never a single shell line. Weeks of green
checkmarks had tested the dictionary lookup.

## Four defects, one render layer

The failures decomposed into four structural problems. The big one: recipes
mix two token namespaces in one string — play-vars
(`{{ rustfs_data_dir }}`, with filters) and engine runtime tokens
(`{{ upgrade_id }}`, `{{ recipe.to }}`). Neither a pure-Ansible render (dies
on engine tokens) nor the engine's old literal-replace (can't do filters)
could handle both. The fix loads recipes raw and has the module render
everything via Jinja2 with StrictUndefined, against controller-harvested
play-vars plus engine tokens. Then: an `exec.shell` bridge (recipes say
`command:`, the handler wanted `cmd:` + `shell:true`), a backup dir nobody
created, and the worst-shaped one — a self-referential `failed_when` that
was always False, so even the 8/8 failure had reported `failed=0`. That
became `failed_when: false` plus an explicit result gate that fails the play
on any recipe failure.

Then real runs exposed that the recipes had been authored against an
invented topology: live containers are `<stack>-<service>-1`, not
`nos-<svc>`; the base file is `docker-compose.yml`; and a bare `up -d`
after `set_image_tag` can leave a healthy container un-recreated — silent
drift, now closed with `--force-recreate` + a post-up live-tag verify.

## The near-miss: rm -rf //*

The post-batch review caught the one that matters. The play-var harvest used
`lookup('vars', *names, default=...)` — which, **without `wantlist=true`,
returns a comma-joined string**. The downstream `names | zip(lookup(...))`
then zipped names against the string's *characters*: every play-var
collapsed to its first character. `/Users/pazny/...` became `/`. The
rendered PostgreSQL wipe step read `rm -rf //*`.

It never executed. The applied services happened to use `set_image_tag`
(engine tokens, not play-vars), and PostgreSQL was carved out via
`upgrade_exclude` — luck wearing the costume of design. The fix is one
argument (`wantlist=true`), now wearing a LOAD-BEARING comment, and the
lesson is permanent: any code path that renders shell from harvested vars
gets verified on the rendered output, not the green recap.

## Authentik: when the rollback is the incident

The 2026.5.2 Authentik jump added its own chapter. The post-upgrade health
check probed the **public** domain — which Cloudflare answered with a 403 —
while expecting 204 (Authentik returns 200 anyway). False timeout →
automatic rollback → `restore_db` restored the old dump **under the new
code**, which half-migrated the schema into a `cert_expiry already exists`
boot loop. SSO down. Recovery was out-of-band: clean dump restore, forward
migrate to 2026.5.2 — 10 users and 49 providers intact. The structural fix:
health checks probe `127.0.0.1:{{ authentik_port }}` with `[200, 204]`, and
Authentik major upgrades are now **forward-only** — rollback is `noop`,
because restoring a dump under newer code corrupts by construction.

## Where it stands

The engine has real applied upgrades behind it, a result gate that can't
lie, and a doctrine line that outlived the day: applied upgrades must bump
the role-default version var, or the next plain run quietly reverts them.
PG major upgrades stay on the coexistence track — the one recipe allowed to
delete data runs nowhere near bulk mode.
