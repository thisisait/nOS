# pazny.calibre_web

Ansible role for deploying **Calibre-Web** (ebook server UI) as a compose override fragment in the devBoxNOS `iiab` stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction (iiab-content unit).

> **Naming note:** the role directory uses the underscore form `pazny.calibre_web` per Ansible Galaxy naming rules, but the Docker compose service is declared as `calibre-web` (with hyphen). The handler name and all `docker compose ... calibre-web` commands use the hyphen form for consistency with the compose service. A legacy bug in `tasks/iiab/calibreweb_post.yml` referenced `calibreweb` without the hyphen (silent failure via `failed_when: false`) — this role fixes it.

## What it does

Two invocation modes from `tasks/stacks/stack-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose -p iiab up`:
   - Creates `~/calibre-web/config`, the books library directory, and the agents log directory
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/calibre-web.yml`
   - Notifies `Restart calibre-web` when the override changes

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose -p iiab up`:
   - Waits for the web UI to respond (12 × 10s retry)
   - Probes whether the default creds (`admin / admin123`) still work
   - Reconverges the admin password via `python3 + werkzeug + sqlite3 UPDATE` in-container
   - Works as a state-declarative idempotent password reset on every run

## Requirements

- Docker Desktop for Mac (ARM64)
- `iiab_net` Docker network (declared in the base iiab compose file)
- `global_password_prefix` set at play level (admin password falls back to `{{ global_password_prefix }}_pw_calibreweb`)
- The `linuxserver/calibre-web` image ships with `python3`, `werkzeug`, and `sqlite3` pre-installed (via `DOCKER_MODS: linuxserver/mods:universal-calibre`)

## Variables

| Variable | Default | Description |
|---|---|---|
| `calibreweb_version` | `latest` | `lscr.io/linuxserver/calibre-web` image tag |
| `calibreweb_port` | `8083` | Host port (bound to `127.0.0.1`) |
| `calibreweb_domain` | `books.dev.local` | Used by the nginx vhost |
| `calibreweb_config_dir` | `~/calibre-web/config` | Host bind mount for `/config` |
| `calibreweb_books_dir` | `~/calibre` | Host bind mount for `/books` (Calibre library) |
| `calibreweb_timezone` | `Europe/Prague` | `TZ` env var |
| `calibreweb_admin_password` | *(from prefix)* | Falls back to `{{ global_password_prefix }}_pw_calibreweb` |
| `calibreweb_mem_limit` | `docker_mem_limit_light` | Defaults to `512m` |
| `calibreweb_cpus` | `docker_cpus_light` | Defaults to `0.5` |

## Usage

From `tasks/stacks/stack-up.yml`:

```yaml
- name: "[Stack] Calibre-Web render + dirs (pazny.calibre_web role)"
  ansible.builtin.include_role:
    name: pazny.calibre_web
  when: install_calibreweb | default(false)

# ... stack-up.yml runs docker compose up iiab ...

- name: "[Stack] Calibre-Web post-start password reset"
  ansible.builtin.include_role:
    name: pazny.calibre_web
    tasks_from: post.yml
  when: install_calibreweb | default(false)
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the `calibre-web` service block in `templates/stacks/iiab/docker-compose.yml.j2`
2. Restore `tasks/iiab/calibreweb.yml` and `tasks/iiab/calibreweb_post.yml`
3. Restore the `import_tasks` calls in `main.yml`

The override file at `~/stacks/iiab/overrides/calibre-web.yml` becomes dead — delete it manually.
