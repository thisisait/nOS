# Upgrade/migration reset-scope + session-safety — design plan

Status: PHASES 0–4 BUILT (Phase 4: 2026-07-07). The macOS-update continuity flow
is live-validated; the reset-scope blank wet-test is still owed. A
discrete extension of the
[agentic upgrade → migration → coexistence epic](agentic-upgrade-migration-coexistence.md);
read that first for the layered RECIPE → MIGRATION → COEXISTENCE model and the
"agents drive, operator supervises" principle this inherits.

> **Build state (2026-06-20):** Phase 0 (run-hardening), Phase 1 (reset-scope
> schema + engine derive-floor + ingest/repository + 25 `reset` blocks across 14 recipe files),
> Phase 2 (plan-choice disruption preview + `run_mode` persistence), Phase 3
> (engine dry-run preview + pre-apply pause gate + `tools/nos-upgrade-detached.sh`
> + `reboot_required` marker/clear/banner + A9 notification) are all in the working
> tree, gated by the full anatomy suite + ansible-lint (production profile). Two
> multi-agent build workflows + adversarial review; all review findings fixed.
> **Phase 4 shipped 2026-07-07:** the migration-author agent carries the recipe's
> `reset` into authored migrations (pinned by a deterministic migration reset-floor
> gate in `tests/migrations/` that `migration-pr.sh` runs); Bone `apply()` refuses a
> session_risk recipe (409 → detached) so it can never run attached under Bone's
> TTY-less playbook; and the plan→detached chain (Wing `applyDetached` → Bone
> `apply-detached` → `nos-upgrade-detached.sh`) is wired. Remaining: the reset-scope
> **blank wet-test**, and a thin UI touch to auto-route a `run_mode=detached` apply
> button to the new endpoint (the session_risk refuse already forces detached for
> the dangerous recipes).

## Why this exists (the trigger)

During a `blank=true` run the operator's IDE (Windsurf) restarted and killed the
controlling agent/terminal session mid-run — leaving a run that could have been
half-applied. Two gaps surfaced:

1. **No blast-radius declaration.** Neither upgrade recipes nor the Wing `/upgrades`
   plan know whether applying a change needs *nothing*, a *container restart*, a
   *stack bounce*, a *host-app restart*, or a *full host reboot*. The operator can't
   plan timing around a disruption they can't see.
2. **The run itself disrupts the host session.** Even a non-upgrade run does
   `killall Dock` / `killall Finder` (`tasks/macos-defaults.yml`, every run) and a
   `launchctl kickstart` of `sshd` (`main.yml`, every run); a blank brings up ~50
   containers whose RAM pressure alone can make macOS terminate a heavy GUI app.
   None of this is `reboot`/`shutdown` (the playbook has none) — but it is enough
   to drop the session running the playbook.

Goal: the **plan** knows the blast radius and shows it; when applying could
disconnect the controlling session, the upgrade runs **detached** so the run
survives the IDE dying; and an *upgrade* run is provably free of the incidental
host-disruptive operations.

## Current state (grounded; from a 4-agent code sweep 2026-06-20)

| Surface | What exists | The gap |
| --- | --- | --- |
| Recipe schema `state/schema/upgrade.schema.json` | `severity`, `coexistence_supported`, `requires{}` | no reset/downtime/reboot field at all |
| Migration schema `state/schema/migration.schema.json` | `downtime{estimated_sec, services_affected}` (informational) | service-level only; no host_app/host_reboot notion |
| Engine `files/anatomy/library/nos_migrate.py` | runs pre→apply→post; `compose.set_image_tag` hardcodes `--force-recreate` | reads no disruption metadata; restart scope is implicit per-step |
| Wing `/upgrades` plan-choice `@plan-choice-modal.latte` | migration-in-place vs coexist (gated on `coexistence_supported`) | no disruption preview; planned row carries no reset/downtime field |
| Recipe → DB `bin/ingest-upgrade-recipes.php` → `upgrade_recipes` | extracts `coexistence_supported` → 0/1 column | nothing to extract for reset |
| Queue → exec `tasks/upgrade-engine.yml` (`--tags upgrade`) | reads `upgrades_planned`, runs `nos_migrate apply_upgrade` | no pre-apply disruption gate; always runs attached to the invoking TTY |
| Host disruption | `killall Dock`/`Finder` (`tasks/macos-defaults.yml`, every run), `launchctl kickstart … sshd` (`main.yml`, every run), `pkill` block (`tasks/blank-reset.yml`, blank only). No `reboot`/`shutdown`, no Docker-daemon restart. | upgrade runs are not proven free of these; GUI killalls fire mid-run unconditionally |

## The `reset` block (shared vocabulary, recipes + migrations)

Optional block on each recipe (`upgrades/<svc>.yml`) and each migration record.
On migrations the block is **forward-ready (Phase 4)**: `resolve_reset` already
folds the legacy `downtime.estimated_sec`/`downtime.services_affected` into
`reset` when `reset` is absent, but no migration code path consumes it yet — the
only live consumer today is the upgrade engine.

```yaml
reset:
  scope: none | container | stack | host_app | host_reboot   # required when reset present
  estimated_sec: 120                                          # optional
  affected_services: [postgresql, authentik]                 # optional
  affected_host_apps: ["Docker Desktop"]                     # optional; meaningful for host_app/host_reboot
  reason: "pg_upgrade rewrites the cluster; cold restart of all consumers"
```

### Scope semantics

| scope | meaning | session_risk |
| --- | --- | --- |
| `none` | config/data only, no process restart (e.g. Grafana dashboard-preserving reload) | no |
| `container` | only this service's container force-recreates (the `compose.set_image_tag` default). Brief blip. | no |
| `stack` | multiple containers in the compose project bounce / dependency cascade (DB upgrade → all consumers reconnect) | no |
| `host_app` | a host-level app/daemon restarts (Docker Desktop, a launchd daemon, host nginx/php-fpm) **or** the run touches Dock/`sshd`. Can ripple into the operator's GUI/terminal. | **yes** |
| `host_reboot` | completing the change needs a full machine reboot (kernel ext, FileVault toggle, macOS update, Docker Desktop major) | **yes** |

**`session_risk` is derived, not authored:** `scope ∈ {host_app, host_reboot}`. It
is the single boolean the plan uses to decide "running attached could disconnect
you → offer detached run."

### Auto-derived floor (engine computes; author may only escalate)

A recipe that omits `reset`, or under-declares it, must never read as `none`. The
engine derives a *floor* from the step/action types and raises (never lowers) the
authored value to it:

| step / action type | derived floor |
| --- | --- |
| `noop`, `http.*`, `backup.*`, `fs.*` | `none` |
| `compose.set_image_tag`, `compose.recreate`, `compose.restart_service` | `container` |
| step that declares its own `affected_services` naming a service other than self; migration `docker.compose_override_rename` on infra | `stack` |

> **`requires.other_services_healthy` is NOT a stack signal.** It is a precondition
> (services that must be healthy *before* the upgrade), which for a *consumer*
> (infisical → postgres/redis) is its own dependencies, not its dependents. Using
> it as blast radius wrongly escalated every consumer to `stack`. `stack` for a
> shared-DB *provider* (postgres/redis/mariadb) is **authored** above the
> mechanical container floor — the consistency gate pins authored ≥ derived.
| migration `launchd.bootout_and_delete`/`launchd.kickstart` of a host daemon; `exec.shell` matching the host-disruptive denylist (`killall`, `launchctl kickstart … sshd`/Dock, Docker Desktop restart, `osascript … quit`) | `host_app` |
| `exec.shell` matching `reboot`/`shutdown -r`/`softwareupdate -i` | `host_reboot` |

The migration-author agent (this branch) copies the recipe's resolved `reset` into
the authored migration verbatim, so the declaration survives promotion.

## Data path (mirrors the existing `coexistence_supported` flow)

1. **Schema** — add `reset` to the recipe `definitions.recipe` and to the migration
   root; keep `downtime` as a folded-in alias.
2. **Ingest** — `bin/ingest-upgrade-recipes.php` stores the **authored** `reset`
   block verbatim → new `upgrade_recipes.reset_json` TEXT column (same pattern as
   `coexistence_supported`). It does **not** derive the floor — the engine's
   `resolve_reset` does that at apply time. The authored value is safe to display
   because the consistency gate pins every shipped recipe to author `scope ≥`
   derived floor (`tests/anatomy/test_upgrade_reset_floor.py`).
3. **Repository** — `UpgradeRepository::matrix()` + `forService()` spread `reset`
   and the computed `session_risk` into each row.
4. **Planned row** — persist `reset_scope`, `session_risk`, `run_mode` onto
   `upgrades_planned` so the badge survives queue → apply and the engine knows how
   to launch.

## Wing `/upgrades` surface

### Disruption preview (in `@plan-choice-modal.latte`, above the migration/coexist radios)

- Scope badge + duration: "Container restart (~30 s)", "Stack bounce — postgresql
  + 4 consumers (~90 s)", "Requires host reboot (~2 min) — Docker Desktop".
- When `session_risk`: a callout — "Applying this can disconnect your IDE/terminal
  session" — and the **Run mode** sub-choice below.

### Run mode (the detached-run remedy; only shown when `session_risk`)

- **Detached (default, recommended)** — the apply runs under
  `caffeinate -ims nohup …` (or a launchd one-shot `eu.thisisait.nos.upgrade-apply`)
  so it survives the controlling session dying. Progress streams to
  `~/.nos/upgrade-<svc>-<ts>.log` + Wing events; the operator may close the IDE.
- **Attached** — operator explicitly accepts foreground (e.g. driving from a second
  machine over SSH).
- For `host_reboot`: a "Stage, then reboot" state — apply runs detached; on success
  it writes a `reboot_required` marker + fires an A9 HIGH notification. **Never
  auto-reboots** (destructive-op safety: manual over auto).

> **Pre-Phase-4 the chosen `run_mode` is persisted + advisory only.** It is snapshotted
> onto `upgrades_planned.run_mode` and surfaced in the plan-choice flash, but the
> engine has no planned-row `run_mode` consumer yet — a detached run is launched by
> the operator via `tools/nos-upgrade-detached.sh` (the engine pause's prompt also
> recommends it). Wiring the Wing "plan → detached" button through Bone is Phase 4.

## Execution side (`tasks/upgrade-engine.yml` + launcher)

- **Pre-apply gate** — before a recipe with `scope ∈ {host_app, host_reboot}`, pause
  for explicit confirmation (mirrors the breaking-migration pause in
  `tasks/pre-migrate.yml`), unless `-e auto_migrate=true` / a force flag.
- **Detached launcher** `tools/nos-upgrade-detached.sh` — `caffeinate -ims` + `nohup`
  (or a launchd one-shot label) that runs
  `ansible-playbook main.yml --tags upgrade -e upgrade_service=<svc>` detached from
  the invoking TTY, writes a pidfile, streams to the log + Wing events. Wing's
  "plan → detached" button shells to this through Bone (scoped, audited) instead of
  the operator running it inline.
- **`reboot_required` surfacing** — for `host_reboot`, on a successful apply write
  `~/.nos/reboot-required.json` + fire A9 HIGH; Wing `/upgrades` shows a persistent
  "Reboot pending to finish <svc> upgrade" banner until cleared.

## Run-hardening (what actually killed the session)

1. **`--tags upgrade` is provably host-quiet.** The Dock/Finder killalls carry
   `macos-defaults`/`osx` tags and the `sshd` kickstart is a handler, so tag
   isolation *should* already exclude them from an upgrade run — but pin it with a
   gate `tests/anatomy/test_upgrade_tag_host_quiet.py` asserting the upgrade task
   graph contains no `killall` / `kickstart … sshd` / Docker-Desktop op. An *upgrade*
   then cannot disconnect you regardless of its own `reset.scope`.
2. **GUI killalls become session-aware.** Gate `killall Dock`/`killall Finder`
   (`tasks/macos-defaults.yml`) behind `defer_gui_restarts` (default true on an
   interactive TTY): collect "GUI restarts needed" and either defer to a final
   post-run prompt or skip with a logged note ("Dock/Finder settings applied;
   restart them or log out to apply"). Document: **run `blank=true` from a terminal
   outside the IDE** (Terminal.app / tmux) — a blank's ~50-container RAM pressure
   alone can make macOS terminate a heavy GUI app.

## Phasing (Phase 0 ships independently, lowest risk, biggest immediate win)

- **Phase 0 — run-hardening.** Host-quiet upgrade gate (#1) + session-aware GUI
  killalls (#2) + the doctrine note. Stops the Windsurf-restart recurrence on its
  own; no schema/UI churn.
- **Phase 1 — schema + derive + ingest.** `reset` block in both schemas, auto-derive
  floor in the engine, `reset_json` column + repository spread. Author `reset` into
  the postgresql 16→17 recipe (the motivating upgrade — `scope: stack`).
- **Phase 2 — plan surface.** Disruption preview + `run_mode` sub-choice in the
  plan-choice modal; persist onto `upgrades_planned`.
- **Phase 3 — detached execution.** `tools/nos-upgrade-detached.sh` + the pre-apply
  gate + `reboot_required` surfacing.
- **Phase 4 — agent propagation.** migration-author copies `reset` into authored
  migrations; Wing "plan → detached" button wired through Bone (scoped, audited).

Agent-driven per the parent epic (the intended Phase-4 model, not yet wired): the
upgrade-architect will author `reset` into recipes and migration-author will
propagate it into authored migrations, the operator supervising, Claude reviewing.

## Tests / gates (the pins that close it)

- `tests/anatomy/test_upgrade_reset_scope_schema.py` — `reset.scope` is a valid enum;
  the authored value is never below the step-implied floor.
- `tests/anatomy/test_upgrade_tag_host_quiet.py` — the `--tags upgrade` graph has no
  host-disruptive op.
- Round-trip gate — `reset` flows recipe YAML → ingest → matrix → modal (mirror the
  F1 `coexistence_supported` round-trip test).

## Acceptance

- Clicking "plan" on postgresql 16→17 in Wing `/upgrades` shows "Stack bounce —
  postgresql + N consumers (~Ns)"; a host_reboot-class recipe shows the reboot
  callout + detached run mode by default.
- An upgrade chosen as "detached" finishes even if the operator closes the IDE
  mid-run (the run is not bound to the invoking TTY).
- `--tags upgrade` never touches Dock/Finder/`sshd`; a blank run no longer
  restarts the GUI mid-run.
