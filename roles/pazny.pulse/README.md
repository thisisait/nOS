# pazny.pulse

Local launchd Python daemon for scheduled jobs. **A4 phase** of the
bones-and-wings refactor (2026-05-03).

## What it does

1. Creates `~/pulse/{venv,state,log}` runtime tree.
2. Builds a Python venv at `~/pulse/venv` (uses pyenv-managed Python).
3. Installs the `nos-pulse` package from `files/anatomy/pulse/` into the
   venv (non-editable; pip `--upgrade` keeps it idempotent).
4. Renders `~/Library/LaunchAgents/eu.thisisait.nos.pulse.plist`.
5. Bootstraps (or reloads) the launchd job.

The plist sets `KeepAlive: true` so launchd respawns Pulse on crash,
with `ThrottleInterval: 30` to prevent tight loops.

## Toggle

Disabled by default until first wet activation lands clean:

```yaml
# config.yml
install_pulse: true
```

## What gets running

| Surface | Where | What |
|---|---|---|
| Daemon | launchd `eu.thisisait.nos.pulse` | `~/pulse/venv/bin/python -m pulse` |
| Logs | `~/pulse/log/pulse.log` | Rotating (10 MB × 5 backups) |
| State | `~/pulse/state/` | sqlite scratch (retry counters, etc.) |
| Wing API | `https://wing.<tenant_domain>` | Polled every 30s |

## Status / control commands

```bash
# Status
launchctl print "gui/$(id -u)/eu.thisisait.nos.pulse" | head -20

# Tail
tail -f ~/pulse/log/pulse.log

# Hot-reload after editing files/anatomy/pulse/
launchctl kickstart -k "gui/$(id -u)/eu.thisisait.nos.pulse"

# Stop (until next playbook run re-bootstraps)
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/eu.thisisait.nos.pulse.plist
```

## Notes

- **No agentic runs yet** (A4 PoC). `runner: subprocess` only. Agent runner
  (claude SDK) lands in A8.
- Pulse polls `/api/v1/pulse_jobs/due` — those Wing endpoints are NOT yet
  implemented (PHP presenters in next commit). Until then, Pulse
  idle-ticks gracefully (logs warning every 60s, never crashes).
- The schema (`pulse_jobs` + `pulse_runs` tables in wing.db) is created
  by Wing's `bin/init-db.php` at first run via the appended block in
  `files/anatomy/wing/db/schema-extensions.sql`.
- This role does NOT containerize anything — Pulse runs on the host. This
  is the first host-launchd organ in the new bones-and-wings shape; A3
  (track-A-reversal) follows by reverting Wing+Bone from container to
  host launchd.
