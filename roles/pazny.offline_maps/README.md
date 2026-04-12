# pazny.offline_maps

Ansible role for the complete **offline maps subsystem** (tileserver-gl + MBTiles) in the devBoxNOS `iiab` stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction (iiab-content unit).

> **Naming note:** the role is named `pazny.offline_maps` (not `pazny.tileserver`) because it owns the full offline-maps subsystem — MBTiles download, tileserver-gl config render, nginx vhost, and the Docker compose service. The compose service itself is still called `tileserver`.

## What it does

Single invocation from `tasks/stacks/stack-up.yml`, runs *before* `docker compose -p iiab up`:

- Creates `{{ maps_data_dir }}` and a `fonts/` subdirectory on the host
- Seeds `config.json` with a tileserver-gl configuration (references `/data/*.mbtiles` inside the container)
- Downloads any MBTiles listed in `maps_mbtiles_files`
- Renders and enables the nginx reverse-proxy vhost
- Drops a `download-maps.sh` helper script for operator use
- Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/tileserver.yml`
- Notifies `Restart offline_maps` when the override changes (handler targets compose service `tileserver`)

There is no post-start task — tileserver-gl serves MBTiles statically with no setup wizard.

**Historical note:** the legacy `tasks/iiab/maps.yml` also installed `tileserver-gl` globally via npm and wrote a launchd plist to run it on the host. That path is dead once the Docker compose service takes over — this role drops the npm/launchd logic and relies entirely on the Docker container.

## Requirements

- Docker Desktop for Mac (ARM64)
- `iiab_net` Docker network (declared in the base iiab compose file)
- At least one `.mbtiles` file on disk (role can download via `maps_mbtiles_files`)

## Variables

| Variable | Default | Description |
|---|---|---|
| `maps_tileserver_version` | `latest` | `maptiler/tileserver-gl` image tag |
| `maps_port` | `8070` | Host port (bound to `127.0.0.1`) |
| `maps_domain` | `maps.dev.local` | Used by the nginx vhost |
| `maps_data_dir` | `~/maps` | Host bind mount for MBTiles + config.json |
| `maps_mbtiles_files` | `[]` | Optional list of `{url, dest}` dicts for pre-download |
| `tileserver_mem_limit` | `docker_mem_limit_light` | Defaults to `512m` |
| `tileserver_cpus` | `docker_cpus_light` | Defaults to `0.5` |

## Usage

From `tasks/stacks/stack-up.yml`:

```yaml
- name: "[Stack] Offline maps render + dirs (pazny.offline_maps role)"
  ansible.builtin.include_role:
    name: pazny.offline_maps
  when: install_offline_maps | default(false)
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the `tileserver` service block in `templates/stacks/iiab/docker-compose.yml.j2`
2. Restore `tasks/iiab/maps.yml` (with legacy npm + launchd logic)
3. Restore the `import_tasks` call in `main.yml`

The override file at `~/stacks/iiab/overrides/tileserver.yml` becomes dead — delete it manually.
