# pazny.qgis_server

Ansible role for deploying **QGIS Server** as a compose override fragment in the devBoxNOS `engineering` stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction (voip-engineering-data worker).

> **Apple Silicon note:** The upstream `kartoza/qgis-server` image is published only for `linux/amd64`. On ARM64 Macs it runs under Rosetta emulation via `platform: linux/amd64` — expect slower performance than native.

## What it does

Single invocation from `tasks/stacks/stack-up.yml` (runs before `docker compose up engineering`):

- Ensures `{{ qgis_data_dir }}/projects` exists on the host
- Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/engineering/overrides/qgis_server.yml`
- Notifies `Restart qgis_server` if the override template changed

No post-start task — QGIS Server is stateless; projects are loaded from the bind-mounted `projects/` directory.

## Requirements

- Docker Desktop for Mac with Rosetta enabled for amd64 emulation

## Variables

| Variable | Default | Description |
|---|---|---|
| `qgis_version` | `latest` | `kartoza/qgis-server` image tag |
| `qgis_port` | `8071` | HTTP port bound on `127.0.0.1` |
| `qgis_data_dir` | `~/qgis` | Host bind mount root (projects/ subdir mounted into `/io/data`) |
| `qgis_mem_limit` | `{{ docker_mem_limit_light }}` | Defaults to `512m` |

## Usage

From `tasks/stacks/stack-up.yml`:

```yaml
- name: "[Stacks] QGIS Server render (pazny.qgis_server role)"
  ansible.builtin.include_role:
    name: pazny.qgis_server
  when: install_qgis_server | default(false)
```

## Rollback

Revert the commit and restore the `qgis-server` service block in `templates/stacks/engineering/docker-compose.yml.j2`.
