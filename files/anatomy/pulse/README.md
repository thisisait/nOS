# nos-pulse

Local launchd daemon scheduling agentic + non-agentic jobs for the
bones-and-wings platform. **A4 PoC scope:** non-agentic only (subprocess
runner). Agentic mode (claude SDK invocations) lands in A8.

## Architecture

- **Tick loop** every 30s (configurable via `PULSE_TICK_INTERVAL_S`)
- Polls Wing API: `GET /api/v1/pulse_jobs/due` → list of jobs whose
  `next_fire_at <= now()` and not paused
- For each job, fires a worker thread that calls
  `pulse.runners.subprocess.execute()` and POSTs results back via
  `/api/v1/pulse_runs/start` + `/finish`
- Concurrency cap: `PULSE_MAX_CONCURRENT` (default 4)
- Graceful drain on SIGTERM (30s grace before forced exit)

## Environment

Required:

| Var | Default | Description |
|---|---|---|
| `WING_API_BASE` | `http://127.0.0.1:9000` | Wing PHP-FPM listening loopback |
| `WING_API_TOKEN` | (empty → idle) | Pulse-side OIDC client_credentials JWT or static API token |

Optional:

| Var | Default | Description |
|---|---|---|
| `PULSE_TICK_INTERVAL_S` | `30` | Tick period in seconds |
| `PULSE_MAX_CONCURRENT` | `4` | Max parallel job executions |
| `PULSE_STATE_DIR` | `~/pulse/state` | Local sqlite scratch for retry counters etc. |
| `PULSE_LOG_PATH` | `~/pulse/log/pulse.log` | Rotating log file |
| `PULSE_DRY_RUN` | `0` | Set to `1` to log instead of exec |

## Running locally

```bash
cd files/anatomy/pulse
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
WING_API_TOKEN="dev-token" python -m pulse
```

The daemon idle-ticks if `WING_API_TOKEN` is unset (warning every 60s
instead of every tick) — useful in dev when Wing is down.

## Job schema

```yaml
# Conceptual shape — registered via Wing API at plugin-loader time
# (anatomy/module_utils/load_plugins.py POSTs to /api/v1/pulse_jobs).
id: "rotate-wing-db-backup"
plugin_name: "wing-base"        # owner; supports cleanup on plugin removal
runner: "subprocess"            # "subprocess" | "agent" (A8)
command: "/Users/pazny/wing/bin/rotate-backup.sh"
args: []
schedule: "0 3 * * *"           # cron expression (parsed Wing-side; Pulse just polls due_at)
jitter_min: 15                  # randomize start within ±15min
max_runtime_s: 600              # SIGKILL after 10 min
max_concurrent: 1               # don't overlap with self
paused: false
```

Wing computes `next_fire_at` based on `schedule`+`jitter`; Pulse just polls
the materialized `due` view. This keeps Pulse's logic dumb and Wing's
catalog UI rich.

## Status

- [x] Skeleton (config, daemon, runners, wing client)
- [x] Subprocess runner with timeout + tail capture
- [x] launchd plist via `pazny.pulse` role
- [ ] Wing PHP endpoints `/api/v1/pulse_jobs/due` + `/pulse_runs/{start,finish}` (next commit)
- [ ] First non-agentic job — `rotate-wing-db-backup` (plugin-loader-registered post-A6)
- [ ] Agent runner (A8 — claude SDK)

## Files

```
files/anatomy/pulse/
├── pyproject.toml
├── README.md            # this file
├── pulse/
│   ├── __init__.py      # version, doc
│   ├── __main__.py      # `python -m pulse` entry
│   ├── config.py        # PulseConfig.from_env()
│   ├── daemon.py        # PulseDaemon — tick loop + dispatch
│   ├── wing_client.py   # HTTP client (idle-tolerant for unimplemented endpoints)
│   └── runners/
│       ├── __init__.py
│       └── subprocess.py  # non-agentic shell runner
└── tests/
    └── test_daemon.py   # unit tests for tick + dispatch
```
