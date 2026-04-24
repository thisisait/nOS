# pazny.wing

Ansible role for deploying **Wing** — a Nette PHP + SQLite security research dashboard — on a macOS host running Homebrew nginx + php-fpm.

Part of [nOS](../../README.md) Wave 2 role extraction pilot. First of three base roles (`pazny.wing`, `pazny.mariadb`, `pazny.grafana`).

## What it does

1. Creates the deployment directory tree (`~/wing/app/{data,temp,log}`, `~/wing/{repos,patches}`)
2. Rsyncs `files/project-wing/` from the playbook into the deployment dir
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
