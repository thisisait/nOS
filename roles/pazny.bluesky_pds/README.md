# pazny.bluesky_pds

Ansible role for deploying a **Bluesky PDS** (Personal Data Server, AT Protocol) as a compose override fragment in the devBoxNOS `infra` stack. Provides federated identity for devBoxNOS users in the atproto / Bluesky network.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction (infra-edge unit).

## What it does

Two invocation modes from `tasks/stacks/core-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose up infra`:
   - Creates `{{ bluesky_pds_data_dir }}` on the host (SQLite + blobs)
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/infra/overrides/bluesky-pds.yml`
   - The override is picked up by core-up's `find + -f` loop and merged into the infra compose project
   - Notifies `Restart bluesky-pds` if the override template changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose up infra --wait`:
   - Waits for `/xrpc/_health` (20 × 3s)
   - Checks if the admin account exists via `goat pds admin account list`
   - On fresh install: creates the admin account (`pds.{{ bluesky_pds_hostname }}`) via `goat pds admin account create`
   - On every run: reconverges the admin password via `goat pds admin account update-password` (idempotent)

The **Authentik → PDS identity bridge** (auto-provisions `@user.bsky.dev.lan` accounts for every Authentik user) stays in `tasks/stacks/bluesky_pds_bridge.yml` — it's cross-service and not role-owned.

## Requirements

- Docker Desktop for Mac (ARM64)
- `bluesky_pds_jwt_secret`, `bluesky_pds_admin_password`, `bluesky_pds_rotation_key` in `default.credentials.yml` (auto-generated in `main.yml` pre-tasks on blank run)
- `stacks_shared_network` defined at the play level
- `goat` CLI pre-installed inside the official Bluesky PDS image (replaces the old `pdsadmin` bash script)

## Variables

| Variable | Default | Description |
|---|---|---|
| `bluesky_pds_version` | `latest` | Tag of `ghcr.io/bluesky-social/pds` |
| `bluesky_pds_hostname` | `bsky.dev.lan` | PDS hostname (`.local` is forbidden by AT Protocol spec) |
| `bluesky_pds_port` | `2583` | Exposed on `127.0.0.1` by default |
| `bluesky_pds_data_dir` | `~/bluesky-pds` | Host bind mount for `/pds` (SQLite + blobstore) |
| `bluesky_pds_invite_required` | `true` | Invite-only registration (closed PDS) |
| `bluesky_pds_email_smtp_url` | `""` | Empty = email notifications disabled |
| `bluesky_pds_email_from` | `""` | Default: `noreply@<hostname>` |
| `bluesky_pds_mem_limit` | `{{ docker_mem_limit_light }}` | Defaults to `512m` |
| `bluesky_pds_cpus` | `{{ docker_cpus_light }}` | Defaults to `0.5` |
| `bluesky_pds_admin_password` | *(from credentials)* | Set via `global_password_prefix` rotation |
| `bluesky_pds_jwt_secret` | *(auto-generated)* | 32-byte random hex |
| `bluesky_pds_rotation_key` | *(auto-generated)* | K256 private key hex |

## Usage

From `tasks/stacks/core-up.yml`, gate the role invocations on `install_bluesky_pds`:

```yaml
# Before infra compose up
- name: "[Core] Bluesky PDS render (pazny.bluesky_pds role)"
  ansible.builtin.include_role:
    name: pazny.bluesky_pds
  when: install_bluesky_pds | default(false)

# ... core-up.yml renders base infra compose + runs docker compose up ...

# After infra compose up
- name: "[Core] Bluesky PDS post-start account + password"
  ansible.builtin.include_role:
    name: pazny.bluesky_pds
    tasks_from: post.yml
  when:
    - install_bluesky_pds | default(false)
    - _core_infra_enabled | bool
```

## Frontend / Web UI

**PDS nemá vlastní web UI.** Je to **backend** AT Protocol server — pouze HTTP API pro
Lexicon (repos, records, blobs). Access to data se dělá přes třetí-stranné klienty.

### Health / API check

```bash
# PDS health (mělo by vrátit {"version":"..."})
curl -sk https://{{ bluesky_pds_hostname | default('bsky.dev.lan') }}/xrpc/_health

# Popis serveru (vypíše did:web, available user domains, invite policy)
curl -sk https://{{ bluesky_pds_hostname | default('bsky.dev.lan') }}/xrpc/com.atproto.server.describeServer
```

### Jak se dostat k UI

Uživatel se loguje přes existujícího AT Protocol klienta a tam nastaví custom PDS URL:

1. **Oficiální web client — https://bsky.app** (hostovaný Bluesky Inc.)
   - Sign In → *"Hosting provider"* → vyplň `https://bsky.dev.lan` (nebo svůj hostname)
   - Login handle ve formátu `<user>.bsky.dev.lan`, heslo z PDS account create

2. **Self-hosted webapp** — klonuj [bluesky-social/social-app](https://github.com/bluesky-social/social-app),
   build s proměnnou `REACT_APP_PDS_URL=https://bsky.dev.lan` a nasadit jako separátní
   Docker service. Zatím není součástí devBoxNOS (bude přidáno jako `pazny.bsky_webapp` role).

3. **Alternativní klienti** (všichni umí custom PDS):
   - [Graysky](https://graysky.app/) — iOS/Android
   - [Deer.social](https://deer.social/) — web
   - [Ozone](https://github.com/bluesky-social/ozone) — moderation dashboard (pro admina)

### Account bootstrap

Admin účet (`pds.{{ bluesky_pds_hostname | default('bsky.dev.lan') }}`) vytváří `tasks/post.yml` automaticky.
Další účty přes Authentik → PDS bridge (`tasks/stacks/bluesky_pds_bridge.yml`) —
každý Authentik user dostane `<username>.bsky.dev.lan` handle.

Manuální account create:
```bash
docker exec -it infra-bluesky-pds-1 goat pds admin account create \
  --email user@example.com --handle user.bsky.dev.lan
```

### Známé limitace

- **Federace není funkční** — AT Protocol federation vyžaduje veřejné DNS a TLS
  certifikát pro `did:web:<hostname>`. Self-hosted PDS na `.dev.lan` hostname zůstává
  ostrov (uživatelé na něm se navzájem vidí, ale s `bsky.app` uživateli ne).
- **Invite required** — výchozí `bluesky_pds_invite_required: true`. Pro self-serve
  registraci nastav `false` v config.yml.

## Rollback

Revert the commit that introduced this role and:

1. Restore the `bluesky-pds` service block in `templates/stacks/infra/docker-compose.yml.j2`
2. The legacy `tasks/stacks/bluesky_pds_post.yml` is untouched (coordinator deletes it in Phase B)
3. `tasks/stacks/bluesky_pds_bridge.yml` stays in place — cross-service, never was role-owned

The override file at `~/stacks/infra/overrides/bluesky-pds.yml` becomes dead — delete it manually if the rollback is permanent.
