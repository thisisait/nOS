# Coexistence Playbook

> Operator guide for running two versions of the same service side-by-side during an
> upgrade window. Useful for zero-downtime major upgrades where rollback safety matters.
> Spec: [framework-plan.md §4.4](framework-plan.md#44-librarynos_coexistencepy--dual-version-controller-agent-5).

---

## Table of contents

- [Purpose](#purpose)
- [How it works](#how-it-works)
- [Supported services](#supported-services)
- [Prerequisites](#prerequisites)
- [Step-by-step workflow](#step-by-step-workflow)
  - [1. Decide whether to use coexistence](#1-decide-whether-to-use-coexistence)
  - [2. Provision the new track](#2-provision-the-new-track)
  - [3. Test the new track](#3-test-the-new-track)
  - [4. Cut over](#4-cut-over)
  - [5. Observe, then clean up](#5-observe-then-clean-up)
- [Data cloning strategies](#data-cloning-strategies)
- [Interactions with migrations](#interactions-with-migrations)
- [When NOT to use coexistence](#when-not-to-use-coexistence)
- [Troubleshooting](#troubleshooting)
- [See also](#see-also)

---

## Purpose

A standard upgrade stops the service, bumps the image tag, starts the service with the new
binary on the old data. If the new binary migrates the data forward, a rollback requires
restoring the data from backup — minutes to hours depending on size. Downtime for users.

Coexistence provisions the new version on a **second port** with **cloned data**, runs the
two side-by-side, lets the operator validate the new track against real-ish data, then
flips the Nginx upstream atomically. Rollback is a second `cutover` call to swap back.

Net effect: zero user-visible downtime and a reversible cutover window measured in seconds,
at the cost of double disk usage and double compute for the window's duration.

---

## How it works

```
Before provision:
  nginx ──► grafana (port 3000, data=/SSD/grafana) ──► real users

After provision:
  nginx ──► grafana (port 3000, data=/SSD/grafana, tag=legacy)      ──► real users
       └──► grafana-new (port 3010, data=/SSD/grafana-new, tag=new) ──► operator via direct port

After cutover:
  nginx ──► grafana-new (port 3010, data=/SSD/grafana-new, tag=new) ──► real users
       └──► grafana (port 3000, data=/SSD/grafana, tag=legacy, read-only) ──► available for rollback

After cleanup (after TTL):
  nginx ──► grafana-new (now just "grafana", port 3000 after swap) ──► real users
  # legacy track removed from disk, compose override deleted, vhost cleaned up
```

Everything is driven by three sub-tasks under `tasks/`:

- `coexistence-provision.yml` — `nos_coexistence.provision_track`
- `coexistence-cutover.yml` — `nos_coexistence.cutover`
- `coexistence-cleanup.yml` — `nos_coexistence.cleanup_track`

Runtime state lives under `coexistence.<service>.tracks[]` in `~/.nos/state.yml`, mirrored
to Glasswing's `coexistence_tracks` table. See
[framework-plan.md §3.2](framework-plan.md#32-nosstateyml--private-runtime-generated).

---

## Supported services

Coexistence v1 supports:

- **Grafana** — bind-mount data, HTTP frontend, Nginx proxied
- **PostgreSQL** — named volume, TCP backend, data clone via `pg_dump | pg_restore`
- **MariaDB** — named volume, TCP backend, data clone via `mariadb-dump | mariadb`
- **Authentik** — named volume + DB, special handling (see §Interactions with migrations)
- **Gitea** — bind-mount data, HTTP + SSH, data clone via `cp -R`
- **Nextcloud** — bind-mount data + DB, HTTP, data clone via `cp -R` + DB clone
- **WordPress** — bind-mount data + DB, HTTP, data clone via `cp -R` + DB clone

Any service whose compose role exports the required knobs (`port_var`, `data_path_var`)
can opt in — see the role's `meta/main.yml`. Services outside this list should either
get a PR to add support or accept in-place upgrades with a downtime window.

---

## Prerequisites

Before starting a coexistence workflow:

1. **Free disk space** — at least 1.5× the service's current data size on the same
   filesystem. The cleanup phase reclaims half.
2. **No other active coexistence for the same service** — the engine refuses to
   provision a third track.
3. **Authentik reachable** (for services with OIDC — the new track needs its own OIDC
   client registration, handled by `nos_coexistence` automatically).
4. **A plan for downstream services** — if you're coexisting Postgres, every service
   that connects to it either points to the legacy track (default) or needs its own
   connection string override.

Glasswing shows all four in the `/coexistence` precheck panel.

---

## Step-by-step workflow

### 1. Decide whether to use coexistence

Use coexistence when any of:

- The service owns irreplaceable state you cannot quickly regenerate
- Users are actively hitting the service during the upgrade window
- The upgrade's `severity: breaking` AND the recipe's `coexistence_supported: true`
- You want a tested rollback path that doesn't depend on restore-from-backup

Skip coexistence and do an in-place upgrade when:

- The service is stateless or trivially regenerates data
- You have a confirmed maintenance window the team is aware of
- Data volume makes cloning impractical (> 500 GB)
- The upstream recipe explicitly lists `coexistence_supported: false`

See [§When NOT to use coexistence](#when-not-to-use-coexistence) below for the full
list of contra-indications.

### 2. Provision the new track

```bash
ansible-playbook main.yml -K --tags coexist-provision \
  -e 'coexist_service=grafana coexist_tag=new coexist_version=12.0.0'
```

Optional args:

- `coexist_port=3010` — override the auto-calculated port (default: current port + recipe's `coexistence_port_offset`)
- `coexist_data_source=clone_from:legacy` — how to populate the new track's data
  (default). Alternatives: `empty` (fresh install), `clone_from:<tag>` (clone from a
  specific named track).
- `coexist_ttl_days=7` — auto-cleanup the *legacy* track N days after cutover (default 7).

What happens:

1. The existing running track (call it `legacy`) is tagged — its record in
   `~/.nos/state.yml` gets `tag: legacy` if it didn't already.
2. Data is cloned from `legacy` to `new` using the strategy matching the service type.
   See [§Data cloning strategies](#data-cloning-strategies).
3. A compose override is rendered at `~/stacks/<stack>/overrides/<service>-new.yml`
   that points to the new image tag, port, data path, and (for OIDC-enabled services)
   a new OIDC client ID.
4. An Nginx vhost is rendered at `nginx/sites-enabled/<service>-new.conf` with a host
   of `<service>-new.<tld>` (e.g. `grafana-new.dev.local`). TLS cert auto-provisioned.
5. The new track container starts via `docker compose up <service>-new --wait`.
6. State file updated: `coexistence.<service>.tracks[]` now has two entries.
7. `coexistence_provision` event emitted.

Failure modes:
- Data clone fails — track not started, state not written, cleanup automatic.
- Container fails to start — track state retained with `healthy: false`, operator must
  cleanup manually or fix the recipe.

### 3. Test the new track

Browse to `https://<service>-new.<tld>` (e.g. `https://grafana-new.dev.local`).

- **Log in** — uses the new OIDC client, same Authentik backend, same credentials.
- **Verify data** — dashboards, users, settings should match the legacy track (minus
  whatever the upgrade intentionally changed).
- **Run your smoke tests** — if you have any.
- **Check logs** — `docker compose -f ~/stacks/<stack>/docker-compose.yml logs <service>-new`.
- **Check metrics** — the new track scrapes into the same Prometheus with label
  `track="new"`; Grafana dashboards can filter by it.

If anything looks wrong: `ansible-playbook main.yml -K --tags coexist-cleanup -e 'coexist_service=<svc> coexist_tag=new'`
to remove the new track. Legacy stays primary and untouched.

### 4. Cut over

```bash
ansible-playbook main.yml -K --tags coexist-cutover \
  -e 'coexist_service=grafana coexist_target_tag=new'
```

What happens:

1. State file updated: `coexistence.<service>.active_track = new`.
2. Nginx vhost for the public host (`<service>.<tld>`) is rewritten: `proxy_pass` now
   points at the new track's container.
3. Nginx reloads (zero-downtime — existing connections drain on the old upstream).
4. Legacy track is marked `read_only: true` in state. For databases this applies a
   runtime-level read-only flag; for stateless services it's advisory.
5. Legacy track gets a `ttl_until` timestamp = now + `coexist_ttl_days`.
6. `coexistence_cutover` event emitted.

Validation: hit `https://<service>.<tld>`. You're now talking to the new track through
the public hostname. Legacy is still running at `https://<service>-legacy.<tld>` for
rollback.

**Cutover is atomic at the Nginx level.** Users with active sessions may need to
refresh once if the new track doesn't accept the legacy track's session cookies.

### 5. Observe, then clean up

Watch the new track for a day or a week, depending on your confidence.

During the window you can **rollback** at any time with:

```bash
ansible-playbook main.yml -K --tags coexist-cutover \
  -e 'coexist_service=grafana coexist_target_tag=legacy'
```

Same command, different target. Nginx flips back. Data on the legacy track is where you
left it (since it was read-only after cutover, new data on the new track is lost or must
be manually replayed — see troubleshooting).

When satisfied, clean up the retired track:

```bash
ansible-playbook main.yml -K --tags coexist-cleanup \
  -e 'coexist_service=grafana coexist_tag=legacy'
```

What happens:

1. Confirms the tag is not the `active_track`. Refuses if so (override with `coexist_force=true`).
2. Stops the container, removes the compose override file, removes the vhost.
3. Creates a final backup at `~/.nos/backups/coexist-cleanup-<timestamp>/<service>-<tag>/`.
4. Deletes the data directory.
5. Removes the track from `~/.nos/state.yml`.
6. Renames the new track's compose override back to the canonical name (drops the `-new`
   suffix), shifts port back to the canonical port.
7. `coexistence_cleanup` event emitted.

After cleanup, the service looks like it did before coexistence started — just with a
new version.

---

## Data cloning strategies

| Service type | Strategy | Duration for 10 GB |
|---|---|---|
| Bind mount | `cp -R` between paths (via `rsync -a` if available) | ~30 s (local SSD) |
| Named Docker volume | `docker run --rm -v src:/src -v dst:/dst alpine cp -a /src/. /dst/` | ~45 s |
| Postgres DB | `pg_dump` from legacy + `pg_restore` to new | ~2 min (data size × wire format overhead) |
| MariaDB DB | `mariadb-dump` + `mariadb` restore | ~2 min |
| Mixed (app + DB) | All of the above in sequence | Sum of parts |

The engine picks the strategy based on the service's manifest entry (`data_path_var` +
auxiliary flags). Manual override via `coexist_clone_strategy=<strategy>` extra-var is
available for operator-driven variations.

### Clone integrity

After the clone:

- For bind mounts / volumes: a byte-level `find src -printf ...` comparison against
  `find dst -printf ...` validates no files were missed.
- For databases: row counts for every table are checked against the source.

A clone that fails integrity aborts the provision. Operator sees a clear error in
Glasswing and the terminal.

---

## Interactions with migrations

Coexistence and migrations interact carefully.

### Migrations refuse to run while coexistence is active

Migrations with the `no_active_coexistence` precondition block themselves when any
service has > 1 track. The rationale: global identifier renames (Authentik groups,
OIDC clients) could desync between tracks.

**Operator action:** either wait for cleanup, or run the migration on a quiet service
(one with no active coexistence) explicitly. See
[migration-authoring.md §Anatomy of a migration](migration-authoring.md#anatomy-of-a-migration)
for the `preconditions` section.

### Authentik coexistence is special

When coexisting Authentik itself, OIDC-consuming services can't follow the active_track
automatically — the discovery URL is cached in each consumer. The engine:

1. Provisions the new Authentik track on port 9444 (default offset 1).
2. Renders a parallel vhost at `auth-new.<tld>`.
3. Does NOT rewrite consumer OIDC URLs until cutover.
4. At cutover, the primary `auth.<tld>` vhost flips to the new track. Consumers still
   work because the OIDC well-known document is served at the same URL.

**Constraint:** you cannot simultaneously coexist Authentik AND another OIDC-enabled
service. Pick one at a time.

### Migrations between coexistence tracks

If you provisioned a new track two weeks ago and a migration landed in the meantime,
the new track is still at the pre-migration state. Cutover applies the migration to the
new track via the `post_cutover_migrations` hook in `nos_coexistence`. In practice this
is rare — keep coexistence windows short (< 7 days) to avoid.

---

## When NOT to use coexistence

Coexistence is powerful but not always appropriate. Skip it for:

### 1. Services in the middle of stateful writes

Services that are actively writing to storage while you're cloning — and where the clone
can miss data — are a footgun.

Examples:

- **FreePBX / Asterisk during a call** — CDR writes land on the legacy track, new track
  misses them, rollback is confusing.
- **Jellyfin mid-transcode** — transcoded segment files may be partially written.
- **n8n mid-workflow** — executions in flight on legacy won't appear on new.

Mitigation: schedule coexistence during low-activity windows, or accept a brief write
freeze (put the service in maintenance mode) during the clone phase.

### 2. Authentication providers during the cutover window

Authentik coexistence works (see above), but coexisting Authentik *while simultaneously*
doing anything else that relies on stable OIDC is unsafe. Do not combine with:

- A service upgrade that bumps OIDC client config
- A migration that renames OIDC clients
- Any other coexistence workflow

Pick one change at a time.

### 3. Services with singleton external bindings

A service that exclusively owns an external resource (e.g. SMTP port 25 on the host, a
specific Tailscale MagicDNS record, a hardware USB device) cannot coexist — the second
track can't claim the same binding.

Exception: the resource is TCP-only AND the service is listen-only AND the operator
manually accepts that inbound traffic will hit only the legacy track during the window.

### 4. Small data, tight schedule, trusted rollback

If the service has < 1 GB of data, a full in-place upgrade takes 60 seconds including
restart, and you have a tested rollback recipe, coexistence adds more complexity than
value. Do the in-place upgrade.

### 5. Data size > 500 GB

Cloning 500 GB over local SSD is ~30 minutes; over anything slower, hours. The
maintenance benefit of coexistence is eroded by the clone duration. Use in-place upgrade
with a read-replica-style staging environment instead (out of scope for `nOS` v1).

### 6. No recipe supports it

If the upgrade recipe sets `coexistence_supported: false`, the author has a reason — usually
a schema migration that can only run once per data set. Respect it. If you believe that's
wrong, open a PR to the recipe.

---

## Troubleshooting

### "Refused to provision: another track already exists"

Check `~/.nos/state.yml` under `coexistence.<service>.tracks`. Exactly one existing track
is expected (the legacy one). If there's already a `new` track from a previous attempt,
clean it up first: `--tags coexist-cleanup -e 'coexist_service=<svc> coexist_tag=new'`.

### Clone fails with "permission denied" on macOS bind mount

Docker Desktop's file-sharing permissions: the new data path must be in the File Sharing
allowlist. Add it via Docker Desktop → Settings → Resources → File Sharing, or relocate
the new track under `/Volumes/SSD1TB` (default allowlist).

### New track starts but doesn't appear in Glasswing

Two likely causes:

1. `pazny.state_manager` hasn't run post-provision. Trigger manually:
   `ansible-playbook main.yml -K --tags state-report`.
2. The new track's container is up but failing health. Check
   `docker logs nos-<service>-new` and the `/timeline` view for `task_failed` events.

### Cutover flipped Nginx but users still hit the old track

Nginx needs a reload (not a restart). The engine does this automatically via `nginx -s reload`.
If `nginx -t` fails, the vhost didn't update. Check `/opt/homebrew/etc/nginx/servers/`
for the new vhost file and `nginx -t` for the error.

### Rollback after cutover loses writes

This is by design. During the post-cutover observation window, the legacy track is
`read_only: true`. Writes on the new track do NOT propagate back. If a rollback might
lose important writes:

- Before rollback, export the delta from the new track manually
- Rollback (atomic Nginx flip)
- Replay the delta into the legacy track

There is no automatic two-way sync. This is a deliberate design tradeoff: simpler
mental model, smaller implementation surface.

### Data clone fills the disk

`fs_free_space_gb` precondition exists to catch this, but sizing estimates can be
optimistic for databases (index rebuilds inflate dumps). Restore from the auto-backup
under `~/.nos/backups/coexist-<timestamp>/` if it was taken, or re-clone after freeing
space elsewhere.

### "Coexistence active" blocks a migration you need to run

Two options:

1. Cleanup the coexistence first, run the migration, then re-provision if still needed.
2. Override the precondition for this one migration:
   `-e 'override_precondition=no_active_coexistence'`. Only do this if you're certain
   the migration is coexistence-safe (rare — document why in the migration record
   before shipping the override).

### Out-of-band changes on the legacy track

Something wrote to the legacy track after cutover despite `read_only: true`. The
read-only flag is advisory for some services (Grafana respects it, Gitea ignores it).
The cleanup phase preserves the legacy data in the backup bundle; you can restore
selectively.

---

## See also

- [framework-overview.md](framework-overview.md) — what the framework is
- [framework-plan.md](framework-plan.md) — authoritative spec
- [upgrade-recipes.md](upgrade-recipes.md) — recipes that support coexistence
- [migration-authoring.md](migration-authoring.md) — how coexistence interacts with migrations
- [glasswing-integration.md](glasswing-integration.md) — `/coexistence` view + widgets
