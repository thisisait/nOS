# Pulse — Agent Definition

## PulseAgent

**System:** Pulse (host organ, `nos.host.pulse`)
**Bind:** none — Pulse is an HTTP client, not a server. There is no base URL to call *on* Pulse.
**Role:** The estate's single timer. It asks Wing which registered jobs are due, forks each as a subprocess under the operator's account, and reports the exit code and scrubbed output tails back into `wing.db`.

### Context

- Control plane is **Wing**, on loopback: `http://127.0.0.1:9000/api/v1/`. Job registry, schedules and run history all live there — Pulse holds none of it.
- Daemon liveness is a service-manager fact, not an HTTP fact: `launchctl print gui/$(id -u)/eu.thisisait.nos.pulse` on macOS, `systemctl --user status eu.thisisait.nos.pulse` on Linux.
- Tick every 30 s, at most 4 concurrent runs, 30 s drain on SIGTERM.
- Source: `files/anatomy/pulse/`; runtime: `~/pulse/{venv,state,log}`; log: `~/pulse/log/pulse.log`.
- Auth for the Wing calls is `Authorization: Bearer <wing_api_token>` — the shared inner-ring token, not a Pulse-specific credential.

### Capabilities

- Register or update a job in the catalog (`POST /api/v1/pulse_jobs`, idempotent on `plugin_name` + `job_name`).
- Read what is due right now (`GET /api/v1/pulse_jobs/due`) and the full catalog (`GET /api/v1/pulse_jobs[/<id>]`).
- Read one run's outcome — exit code, duration, scrubbed tails (`GET /api/v1/pulse_runs/<run_id>`).
- Preview the repo-declared catalog before it is POSTed, by running the discovery script.
- Check, restart and read the daemon on the host.

### Cautions

- Registering a job is a **real scheduling mutation**: the next tick may fire it. There is no dry-run on the registration endpoint.
- `command` and `args` are allowlisted at registration *and* at spawn. A rejected command does not error at fire time — it returns `exit_code 126` with the rejection in `stderr_tail`, which reads like a normal failing run unless you look.
- Pulse has no pause endpoint. Pausing is declarative — `paused: true` + `paused_reason` in the plugin or agent profile — and a re-converge never un-pauses a job the operator paused.
- Restarting the daemon aborts in-flight runs after the 30 s drain. Their `pulse_runs` rows stay unfinished (`exit_code IS NULL`), which Wing's `/pulse` view counts as its own state, not as a failure.
- Do not invent a health URL for Pulse. It binds no socket; anything of the form `http://localhost:<port>/health` is a fabrication.

### Skills Reference

See [SKILLS.md](SKILLS.md) for callable actions.
