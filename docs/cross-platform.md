# Cross-platform — macOS, Linux, Windows (WSL2)

**One playbook, one `default.config.yml`, no per-OS profile.** The goal is that an
operator on any of the three runs `ansible-playbook main.yml` with the committed
defaults and gets the same estate. Platform differences are resolved by FACTS,
never by asking the operator for a toggle.

## The rule

> A toggle expresses what the operator WANTS. What the host IS comes from a fact.

`install_hardening: true` on a container, `configure_osx: true` on Ubuntu,
`install_openclaw: true` on Linux — each is a sensible *want* on a host where it
cannot mean anything. The playbook gates on the fact and skips; the operator's
`config.yml` stays identical across machines.

## Facts (`tasks/_platform.yml`)

| Fact | Values | Gates |
|---|---|---|
| `nos_platform` | macos · ubuntu · debian · redhat | package paths, nginx layout |
| `nos_pkg_manager` | homebrew · apt · dnf | every brew / apt call |
| `nos_service_manager` | launchd · systemd-user | host daemon units |
| `nos_init` | launchd · systemd · none | `none` → units run under `nos-proc` |
| `nos_user_systemctl` | `systemctl --user` · `~/.local/bin/nos-proc` | every restart handler |
| `nos_kernel_ipv6` | true · false | IPv4 listeners (authentik, socket proxy) |
| `nos_is_container` | true · false | `pazny.linux.hardening` (the kernel is the host's) |
| `nos_is_wsl` | true · false | reported; WSL2 is the Linux path |
| `nos_container_user` | '' (macOS) · `<uid>:<gid>` | `user:` on non-root images with operator-owned bind mounts |
| `nos_docker_ready` | true · false | the whole compose layer |

## What each platform runs

| Layer | macOS (Apple Silicon) | Linux (Ubuntu 24.04) | Windows |
|---|---|---|---|
| Packages | Homebrew | apt (`pazny.linux.apt` base prereqs) | WSL2 → Linux column |
| Docker | Docker Desktop | Docker CE (apt) | Docker Desktop WSL2 backend, or Docker CE inside WSL |
| Host organs (Bone, Pulse, Wing, Cortex) | launchd | systemd `--user` · `nos-proc` without systemd | WSL2 → Linux column (enable `systemd=true` in `/etc/wsl.conf`, or `nos-proc` runs them) |
| Node (Cortex ≥ 22) | Homebrew nvm | nvm cloned at `nvm_git_version` | Linux |
| PHP (Wing) | FrankenPHP (brew php-zts) | FrankenPHP single binary | Linux |
| Edge proxy | Traefik | Traefik | Linux |
| Local AI (OpenClaw, Hermes, Ears) | Ollama MLX | **not yet** — Darwin-gated, skipped | not yet |
| macOS niceties (dock, defaults, pmset, casks, MAS) | yes | skipped (fact) | skipped |
| ANSSI hardening | — | yes · skipped in a container | runs (WSL2 is a VM, not a container) |

## Windows: WSL2, not native

Ansible's controller does not run on native Windows, and every nOS host daemon
is a POSIX process. Windows is therefore **Ubuntu 24.04 under WSL2**:

```powershell
wsl --install -d Ubuntu-24.04
```

```bash
# inside the Ubuntu shell
sudo apt update && sudo apt install -y git python3-venv
git clone https://github.com/thisisait/nOS.git ~/nOS && cd ~/nOS
tools/ci-local.sh true                 # frozen ansible toolchain in .ci-venv/
.ci-venv/bin/ansible-playbook main.yml
```

Docker: either Docker Desktop with *Use the WSL 2 based engine* + integration
for the Ubuntu distro, or let `pazny.linux.docker` install Docker CE inside WSL.
Browse from Windows at `https://<svc>.dev.local` — add the mkcert root CA to the
Windows trust store and point `*.dev.local` at `127.0.0.1` (WSL2 forwards
localhost).

**Honest status:** the WSL2 path is the Linux path proven by the cloud e2e
lane (`docs/cloud-e2e.md`) and the `Integration (ubuntu-24.04)` CI job. No
Windows host has run it yet; `nos_is_wsl` exists so the first one reports
itself in the platform summary.

## Proven where

| Evidence | Platform |
|---|---|
| operator's Mac, every release | macOS |
| `Integration (ubuntu-24.04)` CI job | Linux with systemd |
| `tools/cloud/e2e.sh all` (Claude cloud sandbox) | Linux container, no systemd, no IPv6 |
