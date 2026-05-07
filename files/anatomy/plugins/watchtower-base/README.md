# watchtower-base

Tier-1 service plugin for Watchtower, the nOS Docker image-drift watcher.
Activates whenever `install_watchtower` is on (default `true`) and
`roles/pazny.watchtower` is installed. Polls Docker Hub on a cron schedule
(default 04:30 daily, `watchtower_schedule`) for newer image tags than
what's running across the fleet. Notify-only by default
(`watchtower_mode: notify`) — surfaces stale images via Mailpit so the
operator can promote them through upgrade recipes
(`upgrades/<service>.yml`). Setting `watchtower_auto_apply: true` per host
flips it to apply mode for containers labelled
`com.centurylinklabs.watchtower.enable=true` (intended for stateless
services only — anything stateful stays manual).

No `authentik:` block (no UI to gate) and no `hub_card` (operator-facing
surface is the Mailpit inbox at `mail.<tld>` and Grafana via the
Loki labels declared in `observability:`).
