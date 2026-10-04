# nOS

[![License: MIT](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![built with ponytail](https://img.shields.io/badge/built%20with-ponytail-ff69b4?style=flat-square)](docs/doctrine/ponytail.md)

> **Your own cloud, on the machine on your desk.**
>
> nOS is an Ansible playbook that orchestrates 82 roles to turn one Apple Silicon Mac,
> or an Ubuntu 24.04 host, into a complete self-hosted stack: about 55 open-source services behind one sign-in,
> one secrets vault, one observability stack and one backup, plus local AI agents that
> run on your own hardware. Everything is FOSS and every byte of data stays on the box.

nOS is the open-source reference implementation behind
[**This is AIT — Agentic IT**](https://thisisait.eu).

<p align="center">
  <a href="https://thisisait.eu">thisisait.eu</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#what-you-get">What you get</a> ·
  <a href="#how-it-is-built">How it is built</a> ·
  <a href="#how-it-is-tested">How it is tested</a> ·
  <a href="#status-and-limits">Status</a>
</p>

---

## Why it exists

A small team today rents a document wiki, a git forge, a password manager, an identity
provider, monitoring, file sync, automation and a chat assistant from eight different
vendors, each with its own login and its own copy of the team's data. nOS puts the FOSS
equivalents on one machine the team owns and wires them together so they behave like
one system:

- **One sign-in.** Authentik fronts every service, with per-user identity wherever the
  service supports it.
- **One place for secrets.** Every credential is derived from a single master key kept
  on the host. Infisical holds infrastructure secrets, Vaultwarden holds personal ones.
- **One view of the system.** Metrics, logs and traces from every service land in
  Grafana, Prometheus, Loki and Tempo.
- **One backup.** Every database and data directory is dumped nightly into an encrypted
  S3 store (RustFS). Optionally, a restic repository with the Backrest UI lets you browse
  and restore single files.
- **One command to rebuild.** `nos --remove=data --confirm` wipes the estate and
  reinstalls it from zero. That rebuild is how the project tests itself.

---

## Status and limits

nOS is **beta** (latest tag `v0.13-beta`) and has one primary maintainer who works with
coding agents. It runs daily on the maintainer's Mac Studio. Read this before you rely
on it:

- **Reference platform:** macOS on Apple Silicon (M1 or newer). Intel Macs are not supported.
- **Also supported:** Ubuntu 24.04 LTS. A standing CI job runs the full playbook on a
  Linux runner and checks that the services come up. The local AI agents (OpenClaw,
  Hermes) are macOS-only for now. See [docs/linux-port.md](docs/linux-port.md).
- **Recommended hardware:** 36 GB RAM and a 1 TB external SSD for service data.
- **Known rough edges:** ERPNext's first migration is unreliable and it is left out of the
  full test profile. Bluesky PDS federation needs public DNS. Jellyfin and Open WebUI can
  restart a few times on their first database init.

---

## Quick start

### 1. Bootstrap

```bash
git clone https://github.com/thisisait/nOS.git ~/nOS
cd ~/nOS
./bootstrap.sh      # Xcode CLT → Homebrew → Ansible → Galaxy roles → config scaffolding
```

### 2. Choose what to install

Bootstrap creates two gitignored files, `config.yml` and `credentials.yml`. `config.yml`
holds your choices: which services to install (`install_<service>: true|false`), your
domain (`tenant_domain`), and where data lives.

The profile builder writes a `config.yml` for you from a few questions and a choice of
profiles. It is published with each release; until then, build it locally with
`tools/profile-builder-build.py --out /tmp/pb` and open `/tmp/pb/index.html`. Committed
profiles live in [`profiles/`](profiles/):

| Profile | What it is for |
|---|---|
| `dev-minimal.yml` | Only what developing nOS itself needs |
| `all-on.yml` | Every known-good service, sequential bring-up, generous health budget |
| `gov-local.yml` | Enforced MFA, at-rest encryption gate, encrypted backups, tamper-evident audit log |
| `praxis.yml` | A small consulting firm's Mac (beta) |

### 3. Run

```bash
ansible-playbook main.yml       # first run; asks for sudo once, installs the `nos` CLI
nos                             # every run after that
```

The first run downloads many gigabytes of images. Plan for well over twenty minutes, and
more if GitLab is enabled.

### 4. Log in

Credentials are 43-character random strings derived from one master key in
`~/.nos/secrets.yml`. Read one on the host itself:

```bash
tools/nos-secret.py authentik_admin     # the Authentik admin (akadmin) password
tools/nos-secret.py --status            # which scheme is active, names only
```

A value you set in `credentials.yml` always wins over the derived one. Hosts installed
before the v2 scheme keep `<prefix>_pw_<service>` passwords until their next rebuild.

Every service lives at `<service>.<tenant_domain>`. Start at `auth.<tenant_domain>`.

---

## What you get

Services are grouped into Docker Compose stacks. `infra` and `observability` always come
up first; the rest only if you enable them.

| Stack | Services |
|---|---|
| **infra** | MariaDB, PostgreSQL, Redis, Traefik, Authentik, Infisical, Portainer, Stalwart mail, Bluesky PDS |
| **observability** | Grafana, Prometheus, Loki, Tempo, InfluxDB (Alloy runs on the host as the collector) |
| **iiab** | Nextcloud, WordPress, n8n, Node-RED, Open WebUI, MCP gateway, Vaultwarden, Uptime Kuma, ntfy, Miniflux, Calibre-Web, Kiwix, offline maps, Jellyfin, Home Assistant, RustFS, KEAP, nOS face |
| **devops** | Gitea, Woodpecker CI, GitLab CE, Paperclip, code-server |
| **b2b** | Outline, HedgeDoc, BookStack, OnlyOffice, Dolibarr, Firefly III, FreeScout, ERPNext |
| **data** | Metabase, Apache Superset |
| **engineering** | QGIS Server |
| **apps** | Manifest apps from [`apps/`](apps/): Documenso, 2FAuth, Roundcube |

On the host, outside Docker, nOS runs its own small organs:

- **Bone:** a local FastAPI bridge between playbook runs and the event store.
- **Wing:** the operator dashboard, covering security findings, migrations, upgrades,
  the audit timeline and agent sessions.
- **Pulse:** the scheduler for recurring jobs.
- **Cortex:** a loopback reasoning daemon that validates agent pipelines against KEAP,
  the knowledge store.
- **OpenClaw and Hermes:** AI agents backed by Ollama with the MLX backend, so models run
  on the Mac's GPU with no API key.
- **Backrest** (optional): the UI over the restic backup repository.

---

## How it is built

### One role per service, one plugin per integration

Every Docker service is owned by an Ansible role under `roles/pazny.<service>/`. The role
renders one Compose fragment into `~/stacks/<stack>/overrides/`, and the stack is brought
up with every fragment merged. A service is added by adding a role, never by editing a
shared file.

How a service is wired to the rest (its SSO client, notification routing, dashboards,
scheduled jobs, backup coverage) is declared in its plugin manifest,
`files/anatomy/plugins/<service>-base/plugin.yml`. Aggregators read those manifests and
render the Authentik configuration, the notification routes and the Grafana
provisioning. [files/anatomy/docs/plugin-wiring-capabilities.md](files/anatomy/docs/plugin-wiring-capabilities.md)
lists which manifest blocks have a live consumer.

Long-tail apps that do not need a role are a single YAML manifest in `apps/`. The runner
refuses a manifest without a complete GDPR Article 30 block. See
[docs/tier2-app-onboarding.md](docs/tier2-app-onboarding.md).

### Sign-in

Authentik serves `auth.<tenant_domain>`. Each service is in one of three modes:

| Mode | What the user sees | Examples |
|---|---|---|
| **Native OIDC** | "Sign in with Authentik" inside the app, with a per-user account | Grafana, Gitea, GitLab, Nextcloud, Outline, Open WebUI, n8n, Vaultwarden, WordPress |
| **Header SSO** | No login screen; the app trusts identity headers from the proxy | Firefly III, KEAP |
| **Forward auth** | Authentik gates the route; the app has no per-user state | Uptime Kuma, Kiwix, Paperclip, Wing, code-server, Metabase |

Four RBAC tiers (admin, manager, user, guest) map to Authentik groups; each plugin
declares its tier. The full account is in [docs/sso-and-attribution.md](docs/sso-and-attribution.md).

### Edge and TLS

Traefik binds 80 and 443 and routes every service from one generated file. Local domains
get mkcert certificates; public domains get Let's Encrypt certificates through a DNS
challenge. See [docs/traefik-primary-proxy.md](docs/traefik-primary-proxy.md).

### State, upgrades and removal

- `state/manifest.yml` declares what should exist, and `~/.nos/state.yml` records what
  does.
- Per-service upgrade recipes live in `upgrades/`.
- Global migrations live in `files/anatomy/migrations/`.
- Major version changes can run side by side before cutover.

The operator tour is [files/anatomy/docs/framework-overview.md](files/anatomy/docs/framework-overview.md).

Removal is a ladder: `nos --remove=data|deep|all`. Without `--confirm` it is a dry run
that prints exactly what it would delete. See [docs/nos-cli.md](docs/nos-cli.md).

### Agents

AgentKit, inside Wing, is the agent runtime. Every model call is recorded with its session,
tokens and an OpenTelemetry span, and an agent's success is decided by a gate run, never by
the model's own claim. See [docs/ait-runtime-architecture.md](docs/ait-runtime-architecture.md).

---

## How it is tested

The rule the project runs on: **a check that can be satisfied by editing the check is not a
check.** Three layers, each with its own job:

1. **Shape: pytest gates** (`tests/anatomy/`, several thousand tests). They render the
   templates and run the scripts, often against a deliberately broken state, rather than
   grepping for text.
2. **Effect: `--tags verify`.** Readers on the live host ask each service whether the
   wiring landed.
3. **End to end: `tools/nos-smoke.py --strict`.** It hits every route through the real
   edge.

On top of those sits the **from-blank rebuild**. The most recent one, on 2026-09-29, found
ten defects that every gate had passed on the running estate. Each was fixed with a gate
that fails on the broken version.

```bash
tools/ci-local.sh                         # the CI toolchain, frozen, on your machine
python3 -m pytest tests/anatomy -q        # the gate suite
tools/red-status.py                       # what is red on this host right now
```

---

## Everyday commands

```bash
nos                                   # converge everything that is enabled
nos --tags authentik,anatomy,gitea    # one area (tags inherit into roles)
tools/nos-stacks.sh woodpecker        # render and recreate one service, no sudo
nos --remove=data                     # dry run of a rebuild: prints the inventory
nos --remove=data --confirm           # wipe and reinstall from zero
tools/nos-cc.sh                       # terminal control centre: live state, one tmux session
```

The source you cloned is not the running system. nOS runs from `~/stacks`, launchd
agents and data directories, and only a converge moves changes across. Ask the host
what it is running rather than reading the repo:

```bash
tools/estate-status.py                # host vs local checkout vs origin
tools/estate-status.py --config tenant_domain    # a resolved value, not the default
```

---

## Manual steps macOS cannot automate

| What | Why |
|---|---|
| `tailscale up` | Interactive browser login |
| Full Disk Access for your terminal | Protected by SIP |
| Docker Desktop disk image location on the external SSD | GUI-only setting |

---

## Contributing

- Issues with real traces are the most useful thing you can send: the failing task,
  `docker compose logs`, `ansible-playbook -vv`.
- Commits follow Conventional Commits with a subject of 50 characters or fewer.
- Branches: `feat/<name>` or `fix/<name>` merge into `dev`, and `dev` reaches `master`
  only through a pull request. Release tags are cut from `master`.
- A change that fixes a defect ships with the gate that would have caught it.

[CLAUDE.md](CLAUDE.md) is the working contract for agents and humans alike. History and
design narratives live in the [devlog](docs/devlog/README.md).

---

## Origin and license

Forked from [geerlingguy/mac-dev-playbook](https://github.com/geerlingguy/mac-dev-playbook)
by [Jeff Geerling](https://www.jeffgeerling.com/). Inspired by
[Internet-in-a-Box](https://github.com/iiab/iiab).

MIT licensed, see [LICENSE](LICENSE). Built by humans, maintained by agents.
