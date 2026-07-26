# Watchtower — Skills

> **Watchtower has no external skill surface.** It is a headless cron daemon on
> the Docker socket — no HTTP API, no UI, no endpoint an agent can call. This
> file is intentionally skill-free so recall never routes an agent to a
> fabricated endpoint (a confident-wrong route is worse than no route).

## Why there is no skill surface

- Watchtower is a **cron daemon**, not a service-mesh component. It wakes on a
  schedule (`0 30 4 * * *`), reads the Docker socket, compares running image tags
  to the registry, and (in `notify` mode) emails a report. There is nothing to
  invoke over the network.
- It exposes **no health/HTTP endpoint** — `/healthz`, `/ping` do not exist.
- Its entire control surface is **environment configuration** rendered by the
  playbook (`watchtower_mode`, `watchtower_schedule`, `watchtower_label_enable_only`,
  notification vars) — declarative, not callable at runtime.

## How the estate actually interacts with it

- **Read what it found** → the update report is delivered to **Mailpit**
  (`nos.iiab.mailpit`); read it there via Mailpit's REST API, and the run logs
  via Grafana/Loki (`app: watchtower`).
- **Act on a stale image** → do **not** let Watchtower auto-apply stateful
  services. Promote a version through the **upgrade-recipe engine**
  (`upgrades/<service>.yml`, `--tags upgrade -e upgrade_service=<svc>`), which
  runs backups + verify hooks. Watchtower `apply` mode is opt-in per host and
  only for labelled stateless services.

Watchtower reports; the operator (or an upgrade agent through the recipe engine)
acts. It has no callable capability of its own.
