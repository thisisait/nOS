# pazny.kiwix

Ansible role for deploying **Kiwix** (offline Wikipedia, Gutenberg, and other ZIM content) as a compose override fragment in the devBoxNOS `iiab` stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction (iiab-content unit).

## What it does

Invoked from `tasks/stacks/stack-up.yml` before `docker compose -p iiab up`:

- Creates `{{ kiwix_data_dir }}` on the host
- Downloads the init ZIM (`kiwix_init_zim_url`) if no `.zim` files exist yet — without at least one ZIM the container crashloops
- Downloads any additional ZIMs listed in `kiwix_zim_files`
- Renders the nginx reverse-proxy vhost at `{{ homebrew_prefix }}/etc/nginx/sites-available/kiwix.conf` and enables it (when `install_nginx` is true)
- Drops a `download-zim.sh` helper script in `{{ kiwix_data_dir }}` for operator use
- Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/kiwix.yml`
- Notifies `Restart kiwix` when the override template changes

There is no post-start task — Kiwix serves ZIM files statically with no admin/user provisioning.

## Requirements

- Docker Desktop for Mac (ARM64)
- `iiab_net` Docker network (declared in the base iiab compose file)
- At least one `.zim` file on disk (role handles this via `kiwix_init_zim_url`)

## Variables

| Variable | Default | Description |
|---|---|---|
| `kiwix_version` | `latest` | `ghcr.io/kiwix/kiwix-serve` image tag |
| `kiwix_port` | `8888` | Host port (bound to `127.0.0.1` unless `services_lan_access`) |
| `kiwix_domain` | `kiwix.dev.local` | Used by the nginx vhost |
| `kiwix_data_dir` | `~/kiwix` | Host bind mount for ZIM files |
| `kiwix_init_zim_url` | based.cooking ZIM | ~1 MB init download so the container boots |
| `kiwix_init_zim_dest` | `based-cooking.zim` | Filename on disk |
| `kiwix_zim_files` | `[]` | Optional list of `{url, dest}` dicts for additional downloads |
| `kiwix_mem_limit` | `docker_mem_limit_light` | Defaults to `512m` |
| `kiwix_cpus` | `docker_cpus_light` | Defaults to `0.5` |

## Usage

From `tasks/stacks/stack-up.yml`, gate the include on `install_kiwix`:

```yaml
- name: "[Stack] Kiwix render + dirs (pazny.kiwix role)"
  ansible.builtin.include_role:
    name: pazny.kiwix
  when: install_kiwix | default(false)
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the `kiwix` service block in `templates/stacks/iiab/docker-compose.yml.j2`
2. Restore `tasks/iiab/kiwix.yml` and its `import_tasks` call in `main.yml`

The override file at `~/stacks/iiab/overrides/kiwix.yml` becomes dead — delete it manually if the rollback is permanent.
