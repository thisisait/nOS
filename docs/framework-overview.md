# nOS State & Migration Framework — Overview

> Declarative, replayable state management, migrations, dual-version coexistence, and
> upgrade orchestration for `nOS`. This document explains *what* the framework is and
> *why* it exists. Implementation spec: [framework-plan.md](framework-plan.md).

---

## Table of contents

- [Purpose](#purpose)
- [Why this exists](#why-this-exists)
- [Mental model](#mental-model)
- [The five pillars](#the-five-pillars)
- [Data surfaces](#data-surfaces)
- [Lifecycle of a change](#lifecycle-of-a-change)
- [What you see as an operator](#what-you-see-as-an-operator)
- [What you write as an author](#what-you-write-as-an-author)
- [Observability](#observability)
- [Safety properties](#safety-properties)
- [Limitations](#limitations)
- [See also](#see-also)

---

## Purpose

Give `nOS` a first-class answer to three questions that every long-lived self-hosted
stack eventually runs into:

1. **"What is installed right now, and does it match what the playbook says it should be?"**
2. **"How do I safely change a breaking thing (rename identifiers, bump Postgres major, restructure
   a data dir) across an entire fleet without writing throw-away shell scripts?"**
3. **"How do I upgrade a stateful service without a downtime window, and roll back if it breaks?"**

The framework answers with YAML records, a handful of Ansible modules, a set of guarantees,
and a read model in Glasswing. No new DSL, no daemon, no database — the playbook stays the
single source of truth.

---

## Why this exists

`nOS` used to handle breaking changes the way most Ansible projects do: inline `when:` guards,
ad-hoc `shell:` tasks, and a README line saying "run `blank=true` if you're on an old version".
That worked at 10 services. At 57 roles across 8 stacks, it rots fast:

- **Rebrands hurt.** Renaming `devboxnos-*` identifiers to `nos-*` (Authentik groups, launchd
  bundle IDs, state dirs) across a live fleet required manual runbook work per box.
- **Upgrades are risky.** Grafana 11 → 12 changes dashboard schema; Postgres 16 → 17 needs
  `pg_upgrade`. The playbook re-runs image pulls but nothing guides the data transformation.
- **Rollbacks are fictional.** "Just re-run with the old version" ignores that the data
  directory has already been migrated. You need a declared inverse.
- **State is implicit.** `docker ps`, `launchctl list`, `authentik list groups` — knowing
  what's on the box required running five commands and squinting.

The framework moves all four problems into data files and gives them a uniform runtime.

---

## Mental model

Every change to the system is one of three kinds:

| Kind | Example | Lives in |
|---|---|---|
| **Migration** | "Rebrand `devboxnos` → `nos`", "Move state dir", "Rename Authentik groups" | `migrations/<date>-<slug>.yml` |
| **Upgrade** | "Grafana 11 → 12", "Postgres 16 → 17", "Authentik 2026.1 → 2026.4" | `upgrades/<service>.yml` |
| **Coexistence** | "Run Grafana 11 and 12 side-by-side for a week, then cut over" | Runtime state in `~/.nos/state.yml` + orchestrator tasks |

Each is a **record**, not a script. The record describes `detect` (should this run?),
`action` (how to move forward), `verify` (did it work?), and `rollback` (how to undo).
An Ansible module reads the record and executes it idempotently.

---

## The five pillars

### 1. Declarative state

`state/manifest.yml` is the *expected* shape of the system — which services are in play,
where their data lives, what version each is at. Committed to the repo.

`~/.nos/state.yml` is the *actual* shape — generated at the end of every playbook run by the
`pazny.state_manager` role. Gitignored. Merged (never overwritten) so external changes are not
clobbered.

The delta between the two is what drives everything else.

### 2. Migrations

One-shot transitions that move the system from version N to version N+1. Examples:

- Rename `~/.devboxnos` → `~/.nos`
- Rename Authentik groups from `devboxnos-admins` to `nos-admins`
- Bootout `com.devboxnos.openclaw.plist` launchagents

A migration is a YAML file under `migrations/`. The engine runs migrations automatically
during `pre_tasks`. Idempotent: already-applied migrations are no-ops. See
[migration-authoring.md](migration-authoring.md).

### 3. Upgrade recipes

Per-service transitions from a version range to a target version. Examples:

- `grafana 11.x → 12.0.0` (dashboard schema change)
- `postgresql 16.x → 17.0` (requires `pg_upgrade`)
- `authentik 2026.1.x → 2026.4.x` (migrates with built-in `ak migrate`)

A recipe is a YAML file under `upgrades/`, with `pre`, `apply`, `post`, and `rollback`
phases. Invoked explicitly (`--tags upgrade -e upgrade_service=grafana`) or offered as
a suggestion in Glasswing when the manifest shows a newer stable version. See
[upgrade-recipes.md](upgrade-recipes.md).

### 4. Coexistence

Dual-version operation. For supported stateful services (Postgres, MariaDB, Grafana,
Gitea, Nextcloud, WordPress, Authentik), the `nos_coexistence` module can:

- **Provision** a second "track" — new version on a shifted port with cloned data
- **Cutover** — atomically flip Nginx upstream, mark the old track read-only
- **Cleanup** — remove the retired track after a TTL

See [coexistence-playbook.md](coexistence-playbook.md).

### 5. Observability

A Python Ansible callback plugin (`callback_plugins/glasswing_telemetry.py`) emits a
structured event for every task, migration step, upgrade step, and coexistence action.
Events POST to BoxAPI → Glasswing SQLite, with an append-only local JSONL fallback
when the network is down.

Glasswing exposes four new views (`/migrations`, `/upgrades`, `/timeline`, `/coexistence`)
that read the events + mirror state via BoxAPI. See [glasswing-integration.md](glasswing-integration.md).

---

## Data surfaces

```
Repo (committed)                     Host (runtime)
────────────────                     ────────────────
state/manifest.yml   ◄── drives ──►  ~/.nos/state.yml          (generated per run)
migrations/*.yml     ◄── read ────►  ~/.nos/state.yml#applied  (merged on apply)
upgrades/*.yml       ◄── read ────►  ~/.nos/state.yml#services (matched against installed)
                                     ~/.nos/backups/<id>/      (pre-upgrade backups)
                                     ~/.nos/events.jsonl       (callback fallback)

                     ┌── BoxAPI ──► Glasswing SQLite
Callback plugin ─────┤
                     └── fallback ► ~/.nos/events.jsonl
```

Every file above is human-readable. `~/.nos/` is the single runtime side-car; delete it
and the next playbook run regenerates everything (migrations re-detect, already-applied
ones no-op on their own, and state is reintrospected from the live system).

---

## Lifecycle of a change

A typical breaking upstream bump (Grafana 12 release) moves through the framework like this:

1. **Author writes a recipe** — `upgrades/grafana.yml` gets a new `grafana-11-to-12` entry
   with `pre` (backup dashboards), `apply` (bump compose tag), `post` (wait healthy),
   `rollback` (revert tag + restore dashboards).
2. **Operator sees it in Glasswing** — the `/upgrades` matrix highlights Grafana with a
   yellow "breaking upgrade available" badge.
3. **Operator chooses a mode** —
   - **Direct:** `ansible-playbook main.yml -K --tags upgrade -e upgrade_service=grafana`.
     Recipe runs start-to-finish, ~2 min of downtime.
   - **Coexistence:** provision a `new` track on port 3010, test it, then cut over.
     Zero-downtime. See [coexistence-playbook.md](coexistence-playbook.md).
4. **Events land in Glasswing** — every step shows up in `/timeline` and in the detail
   page for the upgrade. The final event marks the recipe `success` or `failed`.
5. **State is persisted** — `~/.nos/state.yml#services.grafana.installed` is updated.
   If anything failed, `rollback` runs and state stays at the old version.
6. **Next playbook run is a no-op** — the recipe's `detect` returns "already at target",
   the upgrade engine skips it.

---

## What you see as an operator

### In the terminal

During `ansible-playbook main.yml -K`, the framework adds three phases:

```
PLAY [Playbook] *************************************************
  TASK [Migrate] Read current state
  TASK [Migrate] Introspect services against manifest
  TASK [Migrate] List pending migrations
  TASK [Migrate] Summary
    msg: |
      Pending migrations: 1
        - [breaking] 2026-04-22-devboxnos-to-nos — Rebrand devBoxNOS → nOS
  TASK [Migrate] Confirm breaking migrations        # interactive, skipped with -e auto_migrate=true
  TASK [Migrate] Apply each pending migration
  ...
  # host roles, stacks, post-start ... (unchanged)
  ...
  TASK [State] Persist updated state                # post_tasks
  TASK [State] Push state to BoxAPI
```

Already-applied migrations are silently skipped. First-time install: 0 migrations pending.

### In Glasswing

Four new views under the main nav (see [glasswing-integration.md](glasswing-integration.md)):

- `/migrations` — pending + applied cards, with [Preview] / [Apply] / [Rollback] buttons
- `/upgrades` — service × version matrix with severity badges
- `/timeline` — merged event stream, filter chips, infinite scroll
- `/coexistence` — active dual-version tracks, TTL countdown, [Cutover] button

### On disk

- `~/.nos/state.yml` — pretty-printed YAML, safe to `cat`, safe to back up
- `~/.nos/backups/<upgrade_id>/` — pre-upgrade backup bundles (data dirs, dashboards, DB dumps)
- `~/.nos/events.jsonl` — append-only event log, used only as fallback when BoxAPI is down

---

## What you write as an author

Three kinds of authoring, three guides:

| If you want to... | Write a... | Guide |
|---|---|---|
| Rename a persistent identifier, fix a global data layout, retire a legacy convention | Migration | [migration-authoring.md](migration-authoring.md) |
| Upgrade a service across a breaking boundary (major version bump) | Upgrade recipe | [upgrade-recipes.md](upgrade-recipes.md) |
| Run old + new side-by-side for a specific service | Nothing — use existing orchestrator | [coexistence-playbook.md](coexistence-playbook.md) |

Authoring is pure YAML. No Python, no Jinja outside template strings, no shell unless
you explicitly set `allow_shell: true` on the migration and justify it in a comment.

---

## Observability

Every significant action emits a structured event. The event schema is defined in
`state/schema/event.schema.json` and enumerates roughly 15 event types:

- Playbook lifecycle: `playbook_start`, `playbook_end`, `play_start`, `play_end`
- Task lifecycle: `task_start`, `task_ok`, `task_changed`, `task_failed`, `task_skipped`,
  `task_unreachable`, `handler_start`, `handler_ok`
- Framework lifecycle: `migration_start`, `migration_step_ok`, `migration_step_failed`,
  `migration_end`, `upgrade_start`, `upgrade_step_ok`, `upgrade_end`, `coexistence_provision`,
  `coexistence_cutover`, `coexistence_cleanup`

Events POST to `BoxAPI /api/events` (HMAC-signed). BoxAPI writes them to Glasswing SQLite.
If the POST fails, events spool to `~/.nos/events.jsonl` and the callback plugin replays
them on the next successful POST.

---

## Safety properties

The framework is designed around six invariants. If any is violated, file a bug.

1. **Idempotent.** Running the playbook twice with nothing changed applies zero migrations,
   zero upgrades, zero coexistence actions. `detect` gates everything.
2. **Ordered.** Migrations apply in filename (chronological) order. Steps within a migration
   apply in declaration order. No reordering.
3. **Atomic at the step level.** A step either completes (detect + action + verify all pass)
   or rolls back. There is no "half-applied step".
4. **Recoverable.** If a step fails, the engine runs its `rollback` and stops. Subsequent
   steps do not run. The migration record stays in `pending`. Operator intervention required.
5. **Observable.** Every step emits an event. If an event is missing, the step didn't run.
6. **Reversible by design.** Every action declares an inverse. "Irreversible" actions are
   allowed only with `rollback: { type: noop, reason: "..." }` and an explanatory reason.

---

## Limitations

Explicitly out of scope for v1 (see [framework-plan.md §10](framework-plan.md)):

- **Cross-host state.** `nOS` is single-host; there is no cluster-wide lock or consensus.
- **Encryption at rest beyond filesystem permissions.** `~/.nos/state.yml` is `0600`; no
  key-wrap.
- **Cross-version downgrade.** A downgrade is modeled as a rollback of a forward upgrade.
  Arbitrary `v2 → v1` without a prior v1→v2 record is not supported.
- **Web UI for authoring.** Migrations and recipes are authored as YAML by hand.
- **CI for framework itself.** Ad-hoc tests (`tests/migrate/`, `tests/upgrades/`) exist but
  are not yet wired into `.github/workflows/ci.yml`.

---

## See also

- [framework-plan.md](framework-plan.md) — authoritative implementation spec
- [migration-authoring.md](migration-authoring.md) — how to write a migration
- [upgrade-recipes.md](upgrade-recipes.md) — how to write an upgrade recipe
- [coexistence-playbook.md](coexistence-playbook.md) — operator guide for dual-version
- [glasswing-integration.md](glasswing-integration.md) — Glasswing views, widgets, API
- [../README.md](../README.md) — project-level overview
