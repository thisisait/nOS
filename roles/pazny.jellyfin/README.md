# pazny.jellyfin

Ansible role for deploying **Jellyfin** (self-hosted media server) as a compose override fragment in the devBoxNOS `iiab` stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction (iiab-content unit).

## What it does

Two invocation modes from `tasks/stacks/stack-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose -p iiab up`:
   - Creates config, cache, movies, shows, and music directories on the host
   - Enables the nginx vhost at `{{ homebrew_prefix }}/etc/nginx/sites-enabled/jellyfin.conf`
   - Prints a post-install note
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/jellyfin.yml`
   - Notifies `Restart jellyfin` when the override changes

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose -p iiab up`:
   - Waits for `/health` to return 200
   - Drives the Startup API wizard (`/Startup/Configuration`, `/Startup/User`, `/Startup/Complete`) on first run
   - On subsequent runs, reconverges the admin password via `AuthenticateByName` + `POST /Users/{id}/Password` using `previous_password_prefix` for OLD auth
   - Degrades gracefully to `DRIFT — manual reset required` when neither current nor previous prefix authenticates

## Requirements

- Docker Desktop for Mac (ARM64)
- `iiab_net` Docker network (declared in the base iiab compose file)
- `global_password_prefix` + (optional) `previous_password_prefix` set at play level

## Variables

| Variable | Default | Description |
|---|---|---|
| `jellyfin_version` | `10.10.7` | Pinned for CVE-2025-31499 (FFmpeg argument injection → RCE) |
| `jellyfin_port` | `8096` | Host port |
| `jellyfin_domain` | `media.dev.local` | Used by the nginx vhost |
| `jellyfin_lan_access` | `true` | Expose port on all interfaces instead of `127.0.0.1` |
| `jellyfin_config_dir` | `~/jellyfin/config` | Host bind mount |
| `jellyfin_cache_dir` | `~/jellyfin/cache` | Host bind mount |
| `jellyfin_movies_dir` | `~/media/movies` | Read-only bind mount |
| `jellyfin_shows_dir` | `~/media/shows` | Read-only bind mount |
| `jellyfin_music_dir` | `~/media/music` | Read-only bind mount |
| `jellyfin_admin_user` | `admin` | Startup wizard user |
| `jellyfin_admin_password` | *(from prefix)* | Falls back to `{{ global_password_prefix }}_pw_jellyfin` |
| `jellyfin_language` | `en-US` | Startup `UICulture` |
| `jellyfin_country` | `CZ` | Startup `MetadataCountryCode` |
| `jellyfin_mem_limit` | `docker_mem_limit_critical` | Defaults to `2g` |
| `jellyfin_cpus` | `docker_cpus_standard` | Defaults to `1.0` |

## Usage

From `tasks/stacks/stack-up.yml`:

```yaml
- name: "[Stack] Jellyfin render + dirs (pazny.jellyfin role)"
  ansible.builtin.include_role:
    name: pazny.jellyfin
  when: install_jellyfin | default(false)

# ... stack-up.yml runs docker compose up iiab ...

- name: "[Stack] Jellyfin post-start wizard + password reconverge"
  ansible.builtin.include_role:
    name: pazny.jellyfin
    tasks_from: post.yml
  when: install_jellyfin | default(false)
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the `jellyfin` service block in `templates/stacks/iiab/docker-compose.yml.j2`
2. Restore `tasks/iiab/jellyfin.yml` and `tasks/iiab/jellyfin_post.yml`
3. Restore the `import_tasks` calls in `main.yml`

The override file at `~/stacks/iiab/overrides/jellyfin.yml` becomes dead — delete it manually.
