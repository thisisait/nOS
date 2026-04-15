# pazny.onlyoffice

Ansible role for deploying **ONLYOFFICE Document Server** (collaborative document editor backend) as a compose override fragment in the devBoxNOS `b2b` stack.

ONLYOFFICE is a **backend service** — end users do not log in directly. It is embedded via iframe by host applications (Nextcloud, Outline, BookStack, ...) that sign API requests with a shared JWT secret.

## What it does

Single invocation from `tasks/stacks/stack-up.yml`:

- Creates 4 host data dirs (`data`, `logs`, `lib`, `db` — embedded postgres)
- Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/b2b/overrides/onlyoffice.yml`
- Notifies `Restart onlyoffice` if the override template changed

No post-start task. Embedded PostgreSQL bootstraps on first run. Redis from the infra stack is used when `install_redis=true` (optional, improves throughput).

## Requirements

- Docker Desktop for Mac (ARM64)
- `stacks_shared_network` defined at the play level
- A top-level `Restart onlyoffice` handler in the consuming playbook (role-local fallback also provided)
- (Optional) `install_redis=true` — reuses infra Redis for caching
- `onlyoffice_jwt_secret` (auto-generated via `openssl rand -hex 32` in `main.yml`)

## Variables

| Variable | Default | Description |
|---|---|---|
| `onlyoffice_version` | `9.3.1.2` | Pinned CE stable (Apr 2026) |
| `onlyoffice_port` | `3015` | Host port; container listens on `:80` |
| `onlyoffice_domain` | `office.{{ instance_tld }}` | Nginx vhost name |
| `onlyoffice_data_dir` | `~/onlyoffice/data` | `/var/www/onlyoffice/Data` bind mount |
| `onlyoffice_logs_dir` | `~/onlyoffice/logs` | `/var/log/onlyoffice` bind mount |
| `onlyoffice_lib_dir` | `~/onlyoffice/lib` | `/var/lib/onlyoffice` bind mount |
| `onlyoffice_db_dir` | `~/onlyoffice/db` | `/var/lib/postgresql` (embedded) bind mount |
| `onlyoffice_jwt_enabled` | `true` | Enforces signed API requests |
| `onlyoffice_jwt_secret` | *(from credentials)* | 32-byte hex; shared with host apps |
| `onlyoffice_mem_limit` | `{{ docker_mem_limit_critical }}` | Defaults to `2g` (conversion is RAM-heavy) |

## Usage

From `tasks/stacks/stack-up.yml`, gated on `install_onlyoffice`:

```yaml
- name: "[Stacks] pazny.onlyoffice render"
  ansible.builtin.include_role:
    name: pazny.onlyoffice
    apply:
      tags: ['onlyoffice']
  when: install_onlyoffice | default(false)
  tags: ['onlyoffice']
```

## Integrace s Nextcloud / Outline / BookStack

ONLYOFFICE je **backend**, pripojuje se pres shared JWT secret. Postup pro kazdou hostitelskou aplikaci:

1. Instaluj plugin / connector v hostitelske aplikaci:
   - **Nextcloud** → app "ONLYOFFICE" ze sklepu → Settings → ONLYOFFICE
   - **Outline** → neni oficialni plugin (Outline ma vlastni editor); ONLYOFFICE lze pouzit jen pres Nextcloud bridging
   - **BookStack** → chapter/page → attached office doc pres ONLYOFFICE module

2. Nastav v hostitelske aplikaci:
   - **Document Server URL**: `https://{{ onlyoffice_domain }}/` (napr. `https://office.dev.local/`)
   - **JWT secret**: hodnota `onlyoffice_jwt_secret` z `credentials.yml`
   - **JWT header**: `Authorization` (default)

3. Host aplikace musi mit sitovy pristup k `https://office.dev.local/` (v devBoxNOS OK — vsechno na localhost).

4. Pokud se zobrazi "Error: The document security token is not correctly formed" — skontroluj ze obe strany pouzivaji stejny JWT secret a JWT je zapnuty na obou (na ONLYOFFICE: `JWT_ENABLED=true`).

## Rollback

Revert the commit that introduced this role and:

1. Delete `~/stacks/b2b/overrides/onlyoffice.yml`
2. Stop the container: `docker compose -f ~/stacks/b2b/docker-compose.yml -p b2b stop onlyoffice && docker compose -f ~/stacks/b2b/docker-compose.yml -p b2b rm -f onlyoffice`
3. (Optional) Wipe host data: `rm -rf ~/onlyoffice`
