# pazny.jsos

Ansible role for deploying **jsOS** — a self-hosted web desktop platform based on OS.js v3, running on Node.js via PM2. Part of [devBoxNOS](../../README.md).

jsOS provides a browser-based desktop environment with Bluesky AT Protocol authentication, per-user virtual filesystem, per-user PostgreSQL databases, Redis session storage, and optional RustFS S3 buckets.

## What it does

1. Creates the deployment directory tree (`~/projects/jsOs/{vfs,src/server/adapters,src/packages}`) and the agent log dir
2. Clones the `os-js/OS.js` v3 boilerplate on first run
3. Runs `npm install` plus the custom dependency set (`@atproto/api`, `pg`, `typeorm`, `@aws-sdk/client-s3`, `connect-redis`, ...)
4. Copies devBoxNOS server adapters (Bluesky auth, S3 VFS, per-user provisioning) from `files/jsos/`
5. Copies the HomelabPortal application package
6. Templates the OS.js server config/index, client index/scss, PM2 ecosystem file and homelab services JSON
7. Runs `npm run package:discover` + `npm run build` when inputs change (webpack, async)
8. Starts/restarts jsOS under PM2 and saves the process list

Changes to adapters, templates or the ecosystem file trigger a `Restart jsos` handler.

## Requirements

- macOS with Homebrew
- Node.js via NVM, PM2 installed globally (handled by the main devBoxNOS playbook)
- PostgreSQL and Redis reachable on `127.0.0.1` (provided by the infra stack)
- The `files/jsos/` and `files/project-jsOs/` trees staying inside the playbook repo (referenced via `playbook_dir`)
- Play-level handler `Restart jsos` defined in the consuming playbook (a role-local copy is also provided)

## Variables

| Variable | Default | Description |
|---|---|---|
| `jsos_domain` | `jsos.dev.local` | Public hostname behind nginx vhost |
| `jsos_port` | `8070` | PM2 app listen port |
| `jsos_dir` | `~/projects/jsOs` | Deployment directory |
| `jsos_db_name` | `jsos` | Primary PostgreSQL database name |
| `jsos_db_user` | `jsos` | Primary PostgreSQL user |
| `jsos_bluesky_pds_url` | `https://bsky.social` | Default PDS for AT Protocol auth |
| `jsos_admin_handles` | `[]` | Bluesky handles with admin permissions |
| `jsos_provision_s3_buckets` | `true` | Create per-user RustFS S3 buckets |
| `jsos_provision_databases` | `true` | Create per-user PostgreSQL databases |
| `jsos_provision_redis_namespace` | `true` | Allocate per-user Redis key prefix |
| `jsos_session_secret` | *(from credentials)* | Session cookie secret, prefix-rotated |
| `jsos_db_password` | *(from credentials)* | PostgreSQL password for `jsos_db_user` |

Secrets (`jsos_session_secret`, `jsos_db_password`) stay in the top-level `default.credentials.yml` so that `global_password_prefix` rotation propagates consistently across all devBoxNOS services.

## Usage

In the consuming playbook:

```yaml
- import_role:
    name: pazny.jsos
  when: install_jsos | default(false)
  tags: ['jsos', 'desktop']
```

## Rollback

Revert the commit that introduced this role and restore `tasks/jsos.yml` + the `import_tasks` call site in `main.yml`. The `files/jsos/` and `files/project-jsOs/` source trees are untouched by the role migration.
