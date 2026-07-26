# Watchtower — Agent Definition

## WatchtowerAgent

**System:** Watchtower (Docker image-drift watcher, `iiab` stack)
**Node:** `nos.iiab.watchtower`
**Domain:** none (headless daemon; no UI, no HTTP surface)
**Role:** Scans the container estate for newer image tags on a cron schedule and
reports drift. **Notify-only by default — no agent-invocable surface.**

### Context

- No login surface and **no `authentik:` block** — SSO bucket `none`.
- Control surface is playbook-rendered environment config, not a runtime API.
- Default mode `notify` (`WATCHTOWER_MONITOR_ONLY: true`); `apply` is per-host
  opt-in for labelled stateless services only.
- Reports route to Mailpit (email) and Loki (logs, `app: watchtower`).

### Capabilities

- **None for agents.** Do not synthesize skills for this system — there is no
  endpoint to call. To read what it found, query Mailpit (`nos.iiab.mailpit`) or
  Loki. To act on a stale image, drive the upgrade-recipe engine
  (`upgrades/<service>.yml`), which runs backups + verify hooks — never let
  Watchtower auto-apply stateful services.

### Skills Reference

See [SKILLS.md](SKILLS.md) — it documents, honestly, that there is no skill surface.
