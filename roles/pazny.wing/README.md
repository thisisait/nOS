# pazny.glasswing

Ansible role for deploying **Glasswing** — a Nette PHP + SQLite security research dashboard — on a macOS host running Homebrew nginx + php-fpm.

Part of [nOS](../../README.md) Wave 2 role extraction pilot. First of three base roles (`pazny.glasswing`, `pazny.mariadb`, `pazny.grafana`).

## What it does

1. Creates the deployment directory tree (`~/glasswing/app/{data,temp,log}`, `~/glasswing/{repos,patches}`)
2. Rsyncs `files/project-glasswing/` from the playbook into the deployment dir
3. Runs `composer install` with production flags
4. Initializes the SQLite schema via `bin/init-db.php`
5. On first run, migrates security advisory JSON data into SQLite via `bin/migrate.php`
6. Reconverges the API token from `glasswing_api_token` credential every run (state-declarative)
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
| `glasswing_domain` | `glasswing.dev.local` | Public hostname behind nginx vhost |
| `glasswing_app_dir` | `~/glasswing/app` | Deployment directory for the Nette app |
| `glasswing_data_dir` | `{{ glasswing_app_dir }}/data` | SQLite database location |
| `glasswing_json_source` | `{{ playbook_dir }}/docs/llm/security` | Source JSON advisories for first-run migration |
| `glasswing_api_token` | *(from credentials)* | REST API bearer token, reconverged on every run |

Secrets (`glasswing_api_token`) stay in the top-level `default.credentials.yml` so that `global_password_prefix` rotation propagates consistently across all nOS services.

## Usage

In the consuming playbook:

```yaml
- import_role:
    name: pazny.glasswing
  when: install_glasswing | default(install_php | default(true))
  tags: ['glasswing', 'security']
```

## Rollback

Revert the commit that introduced this role and restore `tasks/glasswing.yml` + the `import_tasks` call site in `main.yml`. The `files/project-glasswing/` source tree is untouched by the role migration.
