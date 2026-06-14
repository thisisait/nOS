# pazny.wing

Ansible role for deploying **Wing** — a Nette PHP + SQLite security research dashboard — on a macOS host running Homebrew nginx + php-fpm.

Part of [nOS](../../README.md) Wave 2 role extraction pilot. First of three base roles (`pazny.wing`, `pazny.mariadb`, `pazny.grafana`).

## What it does

1. Creates the deployment directory tree (`~/wing/app/{data,temp,log}`, `~/wing/{repos,patches}`)
2. Rsyncs `files/anatomy/wing/` from the playbook into the deployment dir (moved from `files/project-wing/` in 2026-05-03 anatomy A2)
3. Runs `composer install` with production flags
4. Initializes the SQLite schema via `bin/init-db.php`
5. On first run, migrates security advisory JSON data into SQLite via `bin/migrate.php`
6. Reconverges the API token from `wing_api_token` credential every run (state-declarative)
7. Fixes permissions so php-fpm can write to `temp/` and `log/`
8. Clears Nette cache

Changes to the app source or composer deps trigger a `Restart php-fpm` handler.

## Requirements

- macOS with Homebrew
- `php@{{ php_version }}`, `composer`, `rsync` installed (handled by the main nOS playbook)
- `ansible.posix` collection for the `synchronize` module
- Play-level handler `Restart php-fpm` defined in the consuming playbook

## FrankenPHP runtime (Apple Silicon)

Wing runs on the **FrankenPHP single binary** (Caddy + PHP + Mercure + Vulcain)
via host launchd — no PHP-FPM container. The version is pinned by
`frankenphp_version` in `default.config.yml` (tested: **1.12.4**).

- **One ARM64 binary across M1..M5.** FrankenPHP's Homebrew formula compiles a
  native ARM64 binary; there are no per-chip sub-variants — the same binary runs
  on every Apple Silicon generation (and macOS 26/27). The chip generation is
  *not* a compatibility axis.
- **Bottle vs source build.** Homebrew ships a pre-built `arm64_sequoia` bottle
  for macOS 15+. On older macOS with no matching bottle, brew source-builds
  FrankenPHP (needs a Go toolchain), which can fail silently — leaving Wing's
  launchd daemon to segfault on a missing/partial binary.
- **Version preflight gate.** `tasks/main.yml` runs `frankenphp --version` after
  install and **fails with a clear diagnostic** if the landed binary does not
  report `frankenphp_version`. A stale tap, a half-finished source build, or a
  missing bottle surfaces at provision time, not as a silent daemon crash.
- **Bumping the pin.** Re-validate on the live host (`frankenphp --version`),
  then update `frankenphp_version` in `default.config.yml`. The
  `tests/anatomy/test_wing_frankenphp_version_pin.py` gate keeps the pin and the
  preflight wired together.

## Variables

| Variable | Default | Description |
|---|---|---|
| `wing_domain` | `wing.dev.local` | Public hostname behind nginx vhost |
| `wing_app_dir` | `~/wing/app` | Deployment directory for the Nette app |
| `wing_data_dir` | `{{ wing_app_dir }}/data` | SQLite database location |
| `wing_json_source` | `{{ playbook_dir }}/docs/llm/security` | Source JSON advisories for first-run migration |
| `wing_api_token` | *(from credentials)* | REST API bearer token, reconverged on every run |

Secrets (`wing_api_token`) stay in the top-level `default.credentials.yml` so that `global_password_prefix` rotation propagates consistently across all nOS services.

## Usage

In the consuming playbook:

```yaml
- import_role:
    name: pazny.wing
  when: install_wing | default(install_php | default(true))
  tags: ['wing', 'security']
```

## Rollback

Revert the commit that introduced this role and restore `tasks/glasswing.yml` + the `import_tasks` call site in `main.yml`. The `files/project-wing/` source tree is untouched by the role migration.
