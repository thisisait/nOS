# Linux port — operator guide

**Status:** infra layer (apt / docker / nginx / hardening) code-complete on master 2026-04-26; **host-daemon layer in progress (2026-05-25)**. Not yet wet-tested on a clean Ubuntu 24.04 LTS host. This guide is the operator runbook for that test, plus a record of which roles already work cross-platform and which still need Darwin gates.

> **⚠️ Regression note (2026-05-25):** the original Track C predates the anatomy
> host-revert. **A3.5 / A3a / A4 moved Bone, Wing, Pulse and OpenClaw from Docker
> containers back to host `launchd` plists** — re-coupling the core daemons to
> macOS. The cross-platform fix is a service-manager abstraction
> (`pazny.linux.systemd_user::ensure_unit`, branched on `nos_service_manager`).
> **Bone is the first daemon ported (pilot, 2026-05-25);** Wing / Pulse / OpenClaw
> and the preflight launchctl loop (`main.yml` "[Preflight] Ensure anatomy daemons
> loaded") still need the same branch. See "Host daemons" below.

---

## TL;DR

```bash
# Provision a fresh Ubuntu 24.04 LTS box (bare metal, Lima, Multipass, EC2 ARM64, …)
sudo apt update && sudo apt install -y python3-pip git ansible
git clone https://github.com/thisisait/nOS.git ~/nOS
cd ~/nOS
cp default.config.yml config.yml          # tweak install_* flags as needed
cp default.credentials.yml credentials.yml # set global_password_prefix
ansible-playbook main.yml -K               # asks for sudo password
```

The first run installs Docker CE, nginx, the host packages from `pazny.linux.apt`, then proceeds through the normal infra → observability → iiab → ... stack pipeline.

## What's wired up

| Layer | macOS | Linux | Implemented in |
|---|---|---|---|
| Package manager | Homebrew | apt / dnf | `pazny.mac.homebrew` / `pazny.linux.apt` |
| Service manager | launchd | systemd-user | `pazny.linux.systemd_user` |
| Docker runtime | Docker Desktop | Docker CE (apt) | `pazny.linux.docker` (Track C) |
| nginx | Homebrew nginx | apt nginx | `pazny.linux.nginx` (Track C) |
| TLS local-dev cert | mkcert | mkcert (manual install) | `tasks/nginx.yml` |
| TLS public cert | acme.sh + Cloudflare | acme.sh + Cloudflare | `pazny.acme` (cross-platform) |
| Observability stack | Docker | Docker | `tasks/stacks/core-up.yml` |

Cross-platform variables live in `tasks/_platform.yml` (imported in `pre_tasks`). Roles read `nos_nginx_etc_dir`, `nos_systemd_user_dir`, `nos_docker_bin` instead of `/opt/homebrew/...` / `~/Library/LaunchAgents/...`.

## What's NOT wired up yet

| Concern | Status | Workaround |
|---|---|---|
| `tasks/php.yml` | macOS-only (Homebrew) | **STALE WORKAROUND** — Wing reverted to a HOST FrankenPHP launchd daemon in A3.5, so host PHP *is* needed again when `install_wing: true`. Linux needs an apt `php8.3-*` + FrankenPHP path. Until then, set `install_wing: false` on Linux. |
| `tasks/node.yml`, `tasks/python.yml`, `tasks/golang.yml`, `tasks/dotnet.yml`, `tasks/bun.yml` | macOS-only | Skip via `install_node: false` etc. on Linux for now. apt + asdf siblings come in Track C+. |
| `pazny.openclaw` (launchd plist) | macOS-only | Skip with `install_openclaw: false`. systemd-user equivalent is a follow-up. |
| `pazny.dotfiles` | macOS-only | Skip. Linux dotfile management is operator-side. |
| MLX backend for Ollama | macOS-only by design | Use Ollama's CUDA / CPU backend on Linux; nOS doesn't enforce MLX. |

## Host daemons (launchd → systemd --user)

The anatomy daemons run as **host services**, not containers (A3.5/A3a/A4).
On macOS that's a `launchd` plist + `launchctl bootstrap`; on Linux it's a
systemd `--user` unit. The abstraction lives in **`pazny.linux.systemd_user`**:

```yaml
- include_role:
    name: pazny.linux.systemd_user
    tasks_from: ensure_unit
  vars:
    su_name: eu.thisisait.nos.bone
    su_description: "nOS Bone — local FastAPI bridge"
    su_exec_start: "{{ bone_venv }}/bin/uvicorn main:app --host 127.0.0.1 --port {{ bone_port }}"
    su_working_dir: "{{ bone_runtime_dir }}"
    su_environment: { WING_EVENTS_HMAC_SECRET: "...", ... }   # → Environment= lines
```

It renders `~/.config/systemd/user/<name>.service`, runs `loginctl enable-linger`
(units survive logout), and `systemctl --user enable --now`. Each daemon role
branches on `nos_service_manager` (`tasks/_platform.yml`): `launchd` keeps the
plist path untouched, `systemd-user` calls `ensure_unit`.

| Daemon | macOS (launchd) | Linux (systemd --user) |
|---|---|---|
| **Bone** | ✅ | ✅ **ported (2026-05-25)** |
| **Pulse** | ✅ | ✅ **ported (2026-05-25)** |
| **Wing** | ✅ | ✅ **ported (2026-05-25)** — FrankenPHP static binary + composer via `frankenphp php-cli`; **pending VM validation** (static binary arch, php-cli, Caddyfile) |
| OpenClaw | ✅ | 🚫 **Darwin-gated** — Ollama MLX is Apple-Silicon only; Linux = separate Ollama-CUDA role (post-v1) |
| Hermes | ✅ | 🚫 **Darwin-gated** — brew-coupled (uv/python@3.13); apt/uv-installer branch = backlog |
| **backup** (timer) | launchd | ✅ **ported (2026-05-25)** — oneshot `.service` + `.timer` via `ensure_unit` |
| acme (renewal) | acme.sh self-cron | ⏳ acme.sh manages its own renewal cron cross-platform; remaining gap is the **Homebrew install** of acme.sh on Linux (apt/curl) |

The **preflight launchctl loop** in `main.yml` (`[Preflight] Ensure anatomy
daemons loaded`) is already `when: ansible_os_family == 'Darwin'` — Linux-safe
(each role's systemd-user branch does its own `enable --now`).

## Linux gotchas

### IP forwarding for Docker bridge networks
Docker installs `iptables` rules but doesn't enable `net.ipv4.ip_forward` by default on every distro. The `pazny.linux.hardening` role (Track D) sets it via sysctl, but if you're not running hardening:

```bash
echo 'net.ipv4.ip_forward=1' | sudo tee /etc/sysctl.d/99-docker.conf
sudo sysctl --system
```

### User namespace remapping
`docker run --user 10001:10001` (which pazny.bone uses) works out of the box on standard Docker. Rootless Docker requires extra `subuid`/`subgid` configuration; we don't enable rootless by default — the `docker` group membership in `pazny.linux.docker` is the canonical path.

### nginx user
Debian's nginx runs as `www-data`; macOS Homebrew runs as `_www`. The `nos_nginx_run_user` variable in `_platform.yml` resolves both. Vhost templates that hard-code `_www` (legacy: `tasks/observability.yml` blackbox config) will be updated to use the variable as part of cross-cutting cleanup.

### dnsmasq + /etc/resolver
The `dnsmasq_force_local_domains` flag (default `false` on Linux) is wired up for both platforms, but on Linux the `/etc/resolver/<tld>` mechanism doesn't exist — instead we'd write to `/etc/systemd/resolved.conf.d/<tld>.conf` and `resolvectl flush-caches`. Out of scope for Track C; if you need split-horizon DNS on Linux, use the Pi-hole / Adguard pattern instead.

### Apple Silicon vs Linux ARM64
nOS works fine on `aarch64` Linux (Raspberry Pi 5, AWS Graviton, Apple Silicon under Multipass / Lima). No code changes needed; the Docker images we build (`nos-bone`, `nos-wing`) are platform-agnostic.

## Verification checklist

After a fresh `ansible-playbook main.yml -K` on a clean Ubuntu 24.04 box:

```bash
# 1. Docker daemon up + user can run docker without sudo (after re-login)
docker info | grep "Server Version"

# 2. Compose plugin available
docker compose version

# 3. nginx serving HTTP
curl -fsS http://localhost/

# 4. infra stack up
docker ps --filter label=com.docker.compose.project=infra

# 5. observability stack up
docker ps --filter label=com.docker.compose.project=observability

# 6. Bone responding (after install_bone: true and a successful run)
curl -fsS http://localhost:8099/api/health

# 7. Authentik admin reachable
curl -fkSI https://auth.dev.local/ | head -1   # expect HTTP/2 302
```

## v0.4 milestone — minimal cross-platform-ready scope

Captured from the 2026-05-30 readiness audit (decision: v0.3-beta ships macOS;
this is the v0.4 lane). The codebase is ~65% Linux-ready: the **infra layer**
(apt / docker / nginx / hardening) and the **`pazny.linux.systemd_user`
abstraction** are done, and **Bone / Pulse / Wing / backup** already branch on
`nos_service_manager`. What's left for a clean Ubuntu 24.04 aarch64 run:

**Minimal (blocks a Linux run) — mostly mechanical, reuse the proven pattern:**
1. **Gate every `homebrew:` call** with `when: nos_pkg_manager == 'homebrew'`
   (or rely on the `install_*: false` defaults): `tasks/php.yml`, `tasks/node.yml`,
   `tasks/python.yml`, `tasks/dnsmasq.yml`, `tasks/nginx.yml`,
   `roles/pazny.hermes`, `roles/pazny.openclaw`. On a default all-on run the first
   ungated `homebrew:` module errors on Linux.
2. **Port `tasks/heartbeat.yml`** — launchd-only today; add the systemd-user
   branch (copy `roles/pazny.pulse/tasks/main.yml:58-100`).
3. **Gate `tasks/autostart.yml`** osascript Docker-login-items + the
   `~/Library/LaunchAgents/com.ollama.agent.plist` check `when: ansible_os_family == 'Darwin'`.
4. **Gate the OpenClaw LaunchAgent rendering** `when: nos_service_manager == 'launchd'`.
5. **Replace hardcoded `homebrew_prefix` paths** with `_platform.yml` vars
   (`nos_nginx_etc_dir`, etc.) in `tasks/nginx.yml`, `tasks/dnsmasq.yml`.
6. **Ubuntu 24.04 aarch64 wet-test** (Lima / Multipass / Graviton) — the gating
   above + `install_{openclaw,hermes,php,node,...}: false`; Bone/Pulse/Wing/backup
   + the full Docker stack should come up. This is the real acceptance gate.

**Defer (post-v0.4, keep `install_*: false` on Linux):** OpenClaw (Ollama MLX is
Apple-only → needs a CUDA/CPU backend), Hermes (Homebrew `uv`/`python@3.13` →
apt + uv-installer), the dev tool-chains (node/python/php via apt+asdf).

**Reuse, don't re-detect:** `tasks/_platform.yml` (`nos_service_manager`,
`nos_pkg_manager`, `nos_nginx_*`), `roles/pazny.linux.{apt,docker,nginx,hardening,systemd_user}`.

## Tracking

This guide will be expanded as additional roles get Linux siblings. Failing tests / missing functionality should be reported as issues with `[linux]` prefix. The matching cross-platform plumbing lives in `tasks/_platform.yml`; new platform-conditional logic should consult that file's variables rather than re-detecting `ansible_os_family` inline.
