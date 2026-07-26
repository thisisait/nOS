# Pulse

> The scheduling organ — a **host launchd/systemd daemon** (not a container). Pulse listens on nothing: every tick it *calls* Wing on loopback for due jobs, forks each one as a subprocess, and posts the exit code and output tails back.

## Quick Reference

| | |
|---|---|
| **Toggle** | `install_pulse: true` (`default.config.yml`; the role default is `false`) |
| **Kind** | Host daemon — NOT a Docker service, no compose template |
| **Bind** | none — Pulse is an HTTP *client*, never a server |
| **Port / Domain** | none — the manifest row carries no `port_var` and no `domain_var`, so Traefik derives no route |
| **Stack** | `host` (manifest `stack: null`) |
| **Manifest node** | `nos.host.pulse` |
| **launchd label** | `eu.thisisait.nos.pulse` (`pulse_launchd_label`) |
| **systemd unit (Linux)** | `eu.thisisait.nos.pulse.service`, `--user` scope, same env as the plist |
| **Package** | `nos-pulse` `0.1.0`, `requires-python >= 3.12`, one dependency: `httpx>=0.28` |
| **Source tree** | `files/anatomy/pulse/` — the plist's `WorkingDirectory` |
| **Runtime tree** | `~/pulse/{venv,state,log}` (`pulse_home`) |
| **State dir** | `~/pulse/state` (`pulse_state_dir` → `PULSE_STATE_DIR`) |
| **Logs** | `~/pulse/log/pulse.log` (rotating, 10 MB × 5) + `launchd.out.log` / `launchd.err.log` |
| **Tick** | every `30` s (`pulse_tick_interval_s`) |
| **Concurrency** | `4` parallel runs (`pulse_max_concurrent`) |
| **Wing API** | `http://127.0.0.1:9000` (`pulse_wing_api_base`) |
| **Interpreter** | pyenv `~/.pyenv/shims/python3` (macOS) / `/usr/bin/python3` (Linux) — `pulse_python` |
| **Playbook tag** | `--tags pulse` (also carries `anatomy`) |

## No listening surface

Pulse is the fourth host organ, and the only one with nothing to connect to. Wing serves a dashboard, Bone serves an API, Cortex serves a typechecker — Pulse serves nobody. It opens outbound HTTP to Wing and that is its entire network footprint.

That is why its manifest row has no `port_var`, no `domain_var` and no `health_check`. There is no URL to probe. Liveness comes from the service manager instead: `version_source: launchd` makes `nos_state` run `launchctl list`, match `eu.thisisait.nos.pulse`, and report `healthy` / `installed: "loaded"` from whether the unit is loaded.

## Runtime and process model

The daemon is single-threaded in its tick loop and spawns a bounded pool of worker threads for runs (`PulseDaemon`, `files/anatomy/pulse/pulse/daemon.py`):

1. Each tick computes free slots as `max_concurrent - in-flight`. At the cap it logs and skips the tick entirely.
2. It polls `GET /api/v1/pulse_jobs/due` and takes the first `free_slots` jobs.
3. Each job runs in its own non-daemon thread so a five-minute backup never blocks the loop.
4. `SIGTERM` / `SIGINT` set the stop flag and drain in-flight runs for up to 30 s before exiting; launchd `KeepAlive` respawns on a hard death, with `ThrottleInterval 30` against tight respawn loops.

Wing owns the schedule. It computes `next_fire_at` from the job's cron expression plus jitter; Pulse only reads the materialised "due" view. There is no cron parser, no queue and no retry state inside the daemon.

The A4 scope is deliberately non-agentic: a job whose `runner` is anything other than `subprocess` is logged as unsupported and skipped. That is not an error and it does not crash the tick.

## Wing API, and why it is loopback

`pulse_wing_api_base` is `http://127.0.0.1:{{ wing_port | default(9000) }}` — direct loopback to the host-side Wing (FrankenPHP, anatomy A3.5). It deliberately does **not** go through Traefik at `wing.<tenant_domain>`.

Routing Pulse through the edge would put it behind Authentik forward-auth, and Pulse holds no OIDC session, so every poll would 302 to the login page. That is not theoretical: it happened live on 2026-05-07 as a polling 302 storm, and the loopback base is the fix recorded in `roles/pazny.pulse/defaults/main.yml`.

Three calls make up the whole client (`pulse/wing_client.py`): `GET /api/v1/pulse_jobs/due`, `POST /api/v1/pulse_runs` (start row), `POST /api/v1/pulse_runs/<run_id>/finish` (exit code + tails). A `404`/`405` on any of them degrades to an empty result rather than a crash, so Pulse idle-ticks safely against a Wing that has not finished booting.

## Authentication

Pulse issues no credential of its own. `pulse_api_token` is `{{ wing_api_token }}` — the single shared bearer for the inner ring (Wing / Bone / Pulse), persisted in `~/.nos/secrets.yml` and regenerated only when it is still a placeholder. Per-actor identity for Pulse is deferred to the A10 audit-trail phase.

Because the plist embeds that token, the rendered `~/Library/LaunchAgents/eu.thisisait.nos.pulse.plist` is mode `0600` — the same lock-down Wing and Bone use.

## How jobs are declared

Jobs are **declarative and repo-owned**. Nothing is registered by hand.

- A plugin declares its jobs in a `pulse:` block in `files/anatomy/plugins/<name>/plugin.yml` — today `gitleaks`, `keap-base`, `wing-base`, `gdpr-breach-base`, `authentik-tofu-drift-base`.
- An agent declares its jobs in a `pulse:` block in a flat profile `files/anatomy/agents/<agent>.yml` — today `conductor`, `curator`, `librarian`, `scout`, `remediator`, `migration-author`, `upgrade-advisor`, `upgrade-architect`.
- `files/anatomy/scripts/discover-pulse-catalog.py` harvests both globs into one JSON catalog.
- `roles/pazny.wing/tasks/post.yml` POSTs each entry to `/api/v1/pulse_jobs`, idempotent on `plugin_name` + `job_name`.
- `files/anatomy/plugins/pulse-base/plugin.yml` pins the long-term contract: it is a `composition` plugin that aggregates those blocks into `inputs.jobs`, and it declares no compose extension because Pulse is host-side.

A job block carries `name`, `runner`, `command`, `schedule`, and optionally `jitter_min`, `max_runtime_s`, `max_concurrent`, `env`, `paused`, `paused_reason`.

Pausing is declarative too, and one-way: `upsertJob` will set `paused` when a manifest says `paused: true`, but a re-converge never silently un-pauses a job an operator paused. Agent jobs that follow the on-demand doctrine ship `paused: true` with a `paused_reason` naming the script that fires them.

## Execution boundary

The command allowlist exists in two places on purpose: `PulsePresenter::validatePulseCommand` rejects a bad job at registration (SEC-8), and `pulse/runners/subprocess.py::validate_command` rejects it again at spawn time (SEC H-PULSE1), so the boundary holds no matter how a `pulse_jobs` row got written.

- `command` must be an absolute path under `/opt/homebrew/bin/`, `/usr/local/bin/`, `/Users/` or `/home/`.
- The basename must not be a shell interpreter (`sh`, `bash`, `zsh`, `dash`, `csh`, `ksh`, `fish`, `sudo`, `su`, `env`) and must match `^[a-z][a-zA-Z0-9._-]{0,63}$`.
- Each arg must match `^[a-zA-Z0-9._@/:=,+~-]{0,512}$` — whitespace and every shell metacharacter are banned.
- `max_runtime_s` is clamped to 3600 s (default 300) so one job cannot pin a slot past the 30 s stop-drain (SEC L-PULSE1).
- The child env is scoped (SEC M-PULSE2): inherited variables matching `SECRET|TOKEN|PASSWORD|CREDENTIAL|ANTHROPIC|HMAC|_KEY$|API_KEY` are stripped, and a job may not set `DYLD_*`, `LD_*`, `PYTHONPATH`, `PATH`, `IFS`, `BASH_ENV` or `ENV`.
- Output tails are scrubbed by `pulse/redact.py` before they leave the host (SEC-9) and truncated to the last 2000 characters by the client.

## Edge routing breaks the poll loop

**If** you repoint `pulse_wing_api_base` at the Traefik route (`https://wing.<tenant_domain>`) instead of loopback: Pulse holds no OIDC session, so Authentik forward-auth answers every poll with a 302 to the login flow. The client does not follow redirects, so `list_due_jobs` sees a non-200, logs it, and returns an empty list — no job ever fires, and nothing looks broken except the log filling with redirects. Keep the base on `127.0.0.1:{{ wing_port }}`; override it only for a topology that puts Wing on another host, and then give Pulse a path that is not behind the forward-auth gate.

## Job scripts need their executable bit

**When** you add a job whose `command` points at a script in this repo: commit it mode `0755`. Wing's API requires an absolute command path with no leading interpreter word, so the file is exec'd directly and its shebang does the rest — which makes git's file mode load-bearing. `keap-features-sync.py` was committed `100644` and failed on every fire for twelve days with `PermissionError`, faithfully recorded as `exit_code 255` in `pulse_runs` and never looked at. `tests/anatomy/test_pulse_job_commands_executable.py` is the gate that now catches it on a diff.

## Source edits need a daemon restart

**When** you change something under `files/anatomy/pulse/` and the running daemon behaves as before: restart it. The venv install is not editable (`pip install <path>`, no `-e`), but the unit's `WorkingDirectory` is the checkout and the entry point is `python -m pulse`, so the source tree lands first on `sys.path` and wins over the installed copy — at process start. Nothing is reloaded in place.

## Exit codes

The daemon reports the child's own exit code, plus four conventions of its own:

- `126` — rejected by the execution-boundary allowlist.
- `127` — command not found.
- `-9` — SIGKILL after `max_runtime_s`.
- `255` — the daemon itself threw while running the job.

## Dependencies

- **Wing** — the job catalog, the schedule, and the run store all live in `wing.db` behind Wing's API. With Wing down, Pulse polls, gets transport errors, logs them and keeps ticking.
- **`wing_api_token`** — without it the daemon idle-ticks and warns once a minute instead of every tick. It never polls anonymously.
- **The repo checkout** — the plist's `WorkingDirectory` is `{{ playbook_dir }}/files/anatomy/pulse`, and most job commands are absolute paths into the same checkout.
- **A Python ≥ 3.12 interpreter** to build the venv: the operator's pyenv shim on macOS, the system `python3` (with `python3-venv` from `tasks/python.yml`) on Linux.
