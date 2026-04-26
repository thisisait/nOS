# Linux port — operator guide

**Status:** code-complete on master 2026-04-26 (Track C of `docs/roadmap-2026q2.md`). Not yet wet-tested on a clean Ubuntu 24.04 LTS host. This guide is the operator runbook for that test, plus a record of which roles already work cross-platform and which still need Darwin gates.

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
| `tasks/php.yml` | macOS-only (Homebrew) | Wing now runs in a container (Track A), so host PHP isn't needed by default. Set `install_php: false`. |
| `tasks/node.yml`, `tasks/python.yml`, `tasks/golang.yml`, `tasks/dotnet.yml`, `tasks/bun.yml` | macOS-only | Skip via `install_node: false` etc. on Linux for now. apt + asdf siblings come in Track C+. |
| `pazny.openclaw` (launchd plist) | macOS-only | Skip with `install_openclaw: false`. systemd-user equivalent is a follow-up. |
| `pazny.dotfiles` | macOS-only | Skip. Linux dotfile management is operator-side. |
| MLX backend for Ollama | macOS-only by design | Use Ollama's CUDA / CPU backend on Linux; nOS doesn't enforce MLX. |

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

## Tracking

This guide will be expanded as additional roles get Linux siblings. Failing tests / missing functionality should be reported as issues with `[linux]` prefix. The matching cross-platform plumbing lives in `tasks/_platform.yml`; new platform-conditional logic should consult that file's variables rather than re-detecting `ansible_os_family` inline.
