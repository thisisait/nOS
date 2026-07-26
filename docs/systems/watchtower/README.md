# Watchtower

> Docker image-drift watcher. Polls registries on a cron schedule for newer
> image tags than what's running. **Notify-only by default** — it surfaces stale
> images via Mailpit and the operator promotes them through upgrade recipes
> (`upgrades/<service>.yml`); it is the early-warning system, not the executor.
> Uses the active `nickfedor` fork (the upstream `containrrr` project was
> archived in 2023 and its API client is too old for current Docker daemons).

## Quick Reference

| | |
|---|---|
| **URL** | none — Watchtower has no web UI |
| **Port** | none — it is a cron daemon on the Docker socket, not an HTTP service |
| **Stack** | `iiab` |
| **Node** | `nos.iiab.watchtower` |
| **Toggle** | `install_watchtower: true` (default **on**) |
| **Image** | `nickfedor/watchtower:1.16.1` (`watchtower_image`) |
| **Compose override** | `~/stacks/iiab/overrides/watchtower.yml` |
| **Data** | `{{ nos_data_root }}/platform/services/watchtower/data` (default `~/nos/platform/services/watchtower/data`) → mounted at `/data` |
| **Docker socket** | `/var/run/docker.sock` (read-only bind is not used — it needs write to pull/recreate in apply mode) |

## Configuration

- **Mode:** `watchtower_mode: notify` (default) → sets `WATCHTOWER_MONITOR_ONLY:
  true` (scan + report, never pull/recreate). `apply` opts a host into
  pulling + recreating labelled stateless containers.
- **Schedule:** `watchtower_schedule: "0 30 4 * * *"` (Go 6-field cron; daily 04:30 local).
- **Scope:** `watchtower_label_enable_only: true` → only containers labelled
  `com.centurylinklabs.watchtower.enable=true` are scanned (avoids noise on a
  60-service box).
- **Cleanup:** `watchtower_cleanup: true` (prune old layers after a pull; apply mode only).

## Authentication

- **None.** Watchtower has no login surface and carries **no `authentik:` block**
  — it is a host-side daemon with no UI to gate.
- **SSO bucket:** `none` (manifest `oidc: none`).

## Notifications

- Routed through **Mailpit** by default (`watchtower_notifications: email`),
  relayed to `mailpit:1025` so update reports land in the `mail.<tld>` UI.
  From/To: `watchtower_notification_email_from` / `_to`.
- Also carries A9 severity routing (`on_critical`/`on_high` → `wing-inbox`, `ntfy`).

## Health Check

- **None.** Watchtower exposes no HTTP health endpoint (`/healthz`, `/ping` do
  not exist — it is a cron daemon). Liveness is the container's own restart-loop
  on a missing Docker socket; the plugin loader has nothing to wait on.

## Dependencies

- Docker daemon socket (`/var/run/docker.sock`) — mandatory.
- Mailpit (or any SMTP relay) for notifications.
- Grafana/Loki for the operator-facing log view (Loki labels `app: watchtower`).
