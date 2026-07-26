# Pulse — Skills

> Callable actions for the Pulse scheduling organ. Pulse itself exposes no API — it binds no socket. Its catalog and run history are reached through **Wing** on loopback (`http://127.0.0.1:9000`, `Authorization: Bearer <wing_api_token>`); the daemon itself is reached through the host service manager.

## Authentication

- **Method:** N/A — Pulse issues no credential of its own. The API actions below reuse `wing_api_token`, the shared inner-ring bearer that Wing owns; the host actions run as the operator.

---

## check-pulse-daemon

**Trigger:** "is Pulse running", "pulse daemon status", "check the scheduler"
**Method:** host service manager
**Command:**
```bash
launchctl print "gui/$(id -u)/eu.thisisait.nos.pulse"          # macOS
systemctl --user status eu.thisisait.nos.pulse                  # Linux
```
**Output:** the unit's load state, pid and last exit status. This is Pulse's liveness surface — there is no HTTP health endpoint, and `nos_state` reports `healthy` from exactly this signal (`version_source: launchd`).

---

## restart-pulse

**Trigger:** "restart Pulse", "reload the scheduler", "kick the pulse daemon"
**Method:** host service manager
**Command:**
```bash
launchctl kickstart -k "gui/$(id -u)/eu.thisisait.nos.pulse"    # macOS
systemctl --user restart eu.thisisait.nos.pulse                  # Linux
```
**Effect:** stops and respawns the daemon. In-flight runs get the 30 s drain, then die; their `pulse_runs` rows stay unfinished. Also the way to pick up an edit under `files/anatomy/pulse/`.

---

## read-pulse-log

**Trigger:** "pulse log", "why did the tick fail", "what is the scheduler doing"
**Method:** host file read
**Command:**
```bash
tail -n 100 ~/pulse/log/pulse.log
```
**Output:** the tick loop's own record — jobs due per tick, dispatch decisions, `rc`/duration/timeout per run, and the once-a-minute warning when `WING_API_TOKEN` is unset. Rotates at 10 MB, 5 backups. Launchd's own capture is beside it in `launchd.out.log` / `launchd.err.log`.

---

## list-pulse-jobs

**Trigger:** "list scheduled jobs", "what jobs are registered", "pulse catalog"
**Method:** API (Wing)
**Endpoint:** `GET /api/v1/pulse_jobs` — one job by id with `GET /api/v1/pulse_jobs/<plugin_name>:<job_name>`
**Auth:** Bearer `wing_api_token`
**Output:** `{"generated_at":"…","jobs":[…]}` — every registered job with its schedule, `paused` state and `next_fire_at`.

---

## register-pulse-job

**Trigger:** "register a pulse job", "schedule a job", "add a job to the catalog"
**Method:** API (Wing)
**Endpoint:** `POST /api/v1/pulse_jobs`
**Auth:** Bearer `wing_api_token`
**Input:** `{plugin_name, job_name, command, schedule}` required; `runner`, `args`, `env`, `jitter_min`, `max_runtime_s`, `max_concurrent`, `paused`, `paused_reason` optional. `command` must be an absolute path under `/opt/homebrew/bin/`, `/usr/local/bin/`, `/Users/` or `/home/`, must not be a shell interpreter, and every arg must match `^[a-zA-Z0-9._@/:=,+~-]{0,512}$`.
**Output:** `201` with the upserted job. Idempotent on `plugin_name` + `job_name`.
**Effect:** a real scheduling mutation — the next tick may fire it. The durable place to declare a job is a `pulse:` block in a plugin manifest or agent profile; this endpoint is what the playbook calls on your behalf.

---

## inspect-pulse-run

**Trigger:** "what happened in that run", "pulse run result", "check the job output"
**Method:** API (Wing)
**Endpoint:** `GET /api/v1/pulse_runs/<run_id>`
**Auth:** Bearer `wing_api_token`
**Output:** the run row — `exit_code`, `fired_at`/`finished_at`, and the scrubbed `stdout_tail` / `stderr_tail` (last 2000 chars each). `exit_code` `126` means the command was rejected by the allowlist, `127` not found, `-9` killed at `max_runtime_s`, `255` a daemon-side exception; `NULL` means the run never reported back.

---

## preview-pulse-catalog

**Trigger:** "what jobs would be registered", "preview the pulse catalog", "show declared pulse jobs"
**Method:** host script (read-only)
**Command:**
```bash
NOS_PLAYBOOK_DIR="$PWD" python3 files/anatomy/scripts/discover-pulse-catalog.py
```
**Output:** JSON on stdout — one `{source, plugin_name, job}` entry per job declared in `files/anatomy/plugins/*/plugin.yml` and `files/anatomy/agents/*.yml`. Writes nothing and calls no API. Placeholders like `{{ playbook_dir }}` are substituted **literally** from `NOS_*` env vars, not rendered by Jinja; unset vars leave the token in place. Exits `2` without `NOS_PLAYBOOK_DIR`.

---

## review-pulse-jobs

**Trigger:** "show the pulse dashboard", "which jobs are failing", "pulse view"
**Method:** UI (Wing)
**Endpoint:** `https://wing.<tenant_domain>/pulse`
**Auth:** Authentik forward-auth on Wing (no extra in-Wing tier gate on this page)
**Output:** per-job run counts split into ok / failing / unfinished, the last exit code and the last `stderr_tail` — the screen whose absence let a job fail silently for twelve days.

---

## reconverge-pulse

**Trigger:** "re-render the pulse daemon", "apply pulse config", "change the tick interval"
**Method:** playbook
**Command:**
```bash
ansible-playbook main.yml --tags pulse
```
**Effect:** ensures `~/pulse/{venv,state,log}` exist, reinstalls the package into the venv, re-renders the launchd plist (or systemd `--user` unit) and reloads it. This is how `pulse_tick_interval_s`, `pulse_max_concurrent`, `pulse_dry_run` and `pulse_wing_api_base` overrides in `config.yml` take effect. The role's tasks need no sudo, so pressing Enter at the password prompt is enough.
