# alloy-base

**Track Q1b** | **Phase 1, Worker U1** | **Status: live (PoC, post-A6.5 doctrine)**

Wiring layer for **Grafana Alloy** — the unified telemetry collector that ships
host-level metrics to Prometheus, log lines to Loki, and OTLP traces to Tempo.

`alloy-base` is the **first non-Docker service plugin** in the nOS anatomy. It
validates the **host-binary shape** (#6 in `docs/bones-and-wings-refactor.md`
§1.1) for any Homebrew-installed, `brew services`-managed daemon.

## What this plugin owns

- `~/.config/alloy/config.alloy` — the master Alloy config (River syntax).
  The base config is intentionally minimal: logging, alloy self-scrape,
  `prometheus.remote_write.default`, `loki.write.default`, OTLP receiver.
- The `grafana-alloy` Homebrew formula install + `brew services` lifecycle
  (via `tasks/install.yml`, imported by the Phase-2 thin `pazny.alloy` role).

## What this plugin does NOT own (Phase 3, U11-U13)

- Host metric scrapes (`prometheus.exporter.unix`, cAdvisor, Postgres /
  MariaDB / Redis exporters, Blackbox, nginx, php-fpm, Qdrant) →
  `alloy-host-metrics` composition plugin.
- Docker container log discovery (`discovery.docker` + `loki.source.docker`)
  → `alloy-docker-metrics` composition plugin.
- File-tail log sources (nginx access/error, php-fpm, agent markdown logs,
  brew services logs) → `alloy-syslog` composition plugin.

Composition plugins concatenate their River fragments INTO this base config
at render time. The loader's `compose_river` action (Phase 3) is spec'd in
`files/anatomy/docs/plugin-loader-spec.md` (forward-spec section).

## Files

```
files/anatomy/plugins/alloy-base/
├── plugin.yml                # manifest (loader-consumed)
├── README.md                 # this file
├── manifest.fragment.yml     # state/manifest.yml row (operator merges in Phase 2)
├── tasks/
│   └── install.yml           # brew install + brew services restart (Ansible)
└── templates/
    └── config.alloy.j2       # minimal core River config
```

## Why `type: [service]` and not `[service, host-binary]`

The `type` enum in `state/schema/plugin.schema.json` is closed
(`skill | service | composition | scheduled-job | ui-extension | notifier`).
Widening it for one orthogonal axis (Docker vs. brew) is a bigger schema
churn than the host-binary nature warrants, so we keep `type: [service]`
and capture the brew-managed shape under a top-level `host:` block (which
sits under `additionalProperties: true`). The loader doesn't parse `host:`
today; the install task wires it manually. When we have a second host
service (e.g. a future host-php-fpm exporter) we'll either widen the enum
or formalize `host:` as a first-class loader concern.

## Smoke test (E2E)

```bash
cd <repo>
PYTHONPATH=files/anatomy python3 -m module_utils.load_plugins smoke \
    --root files/anatomy/plugins
# Expect alloy-base in the discovery list with status=ok (or skipped — see
# below — if running on a machine without `brew`).
```

The smoke driver runs `pre_compose` against a tmp `stacks_dir`. For
`alloy-base` this means:

1. `ensure_dir ~/.config/alloy` — creates the directory under the smoke's
   mocked HOME.
2. `render provisioning.config` — renders `config.alloy.j2` to
   `<mock-home>/.config/alloy/config.alloy`. No `brew` interaction
   happens in the smoke run; all loader actions are filesystem-only.

If the worktree has no Homebrew (e.g. CI containers), the smoke is still
expected to PASS because `host_command: brew` under `requires:` is
documentary today — the loader does not enforce it (see
`files/anatomy/module_utils/load_plugins.py::topological_order`, which
only honours `requires.plugin`). The brew check fires later, in
`tasks/install.yml`, at real-blank time.

## Operator integration roadmap

| Phase | Step | Owner |
|-------|------|-------|
| **1** | Manifest + template + install task land. Smoke green. | U1 (this PR) |
| 2 | `pazny.alloy` thin role created; `tasks/observability.yml` brew block + monolithic `files/observability/alloy/config.alloy.j2` retired. `state/manifest.yml` row merged from `manifest.fragment.yml`. | operator |
| 3 | `alloy-host-metrics` / `alloy-docker-metrics` / `alloy-syslog` composition plugins land + `compose_river` loader action. | U11–U13 |

Until Phase 2 ships, the existing `files/observability/alloy/config.alloy.j2`
remains the source of truth for live deploys; `alloy-base` is **load-bearing
forward spec** but does not yet drive a real run.
