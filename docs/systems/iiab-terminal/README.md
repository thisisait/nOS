# IIAB Terminal

> A text user interface (Python Textual) set as the forced shell for a kiosk
> account over SSH. A console-only guest `ssh home@<host>` and lands directly in
> a menu of homelab services — no shell access. Non-Docker: a host user +
> `sshd_config` `ForceCommand`, no daemon and no listening HTTP port of its own.

## Quick Reference

| | |
|---|---|
| **Type** | Host organ (non-Docker), SSH `ForceCommand` TUI — no daemon, no HTTP port, no domain |
| **Stack** | `host` (synthetic bucket for `stack: null` manifest services) |
| **Toggle** | `install_iiab_terminal: false` (default off; requires SSH) |
| **Manifest id** | `iiab_terminal` → node `nos.host.iiab-terminal` (underscore folds to a hyphen) |
| **Version source** | `none` |
| **Access** | `ssh home@<host>` (the `ForceCommand` launches the TUI) |
| **Kiosk user** | `home` (`iiab_terminal_user`; macOS user, created on first run) |
| **Config + app** | `/opt/homebrew/etc/iiab-terminal/` (`config.json`, `iiab_terminal.py`) |
| **Launcher** | `/opt/homebrew/bin/iiab-terminal` |

Values read from `roles/pazny.iiab_terminal/defaults/main.yml`,
`roles/pazny.iiab_terminal/tasks/main.yml`, `files/iiab-terminal/iiab_terminal.py`,
and `state/manifest.yml`. Paths shown resolve `homebrew_prefix` to `/opt/homebrew`
on Apple Silicon.

## How Access Works

- A `Match User home` block in `/etc/ssh/sshd_config` sets `ForceCommand /opt/homebrew/bin/iiab-terminal`, disables `X11Forwarding`, `AllowTcpForwarding`, and `PermitTunnel`.
- The launcher exports `IIAB_CONFIG` and `exec`s the Textual app on the host `python3`. The guest gets the menu, never a prompt.
- On first run the role creates the `home` user and, if `iiab_terminal_password` is empty, auto-generates a password (`openssl rand -base64 12`).

## Authentication

- **SSO bucket:** none. Access is SSH password auth for the `home` user (`iiab_terminal_password_auth: true`, default). There is no Authentik provider, no web domain, and no OIDC — the manifest row declares no `domain_var`/`port_var`.

## Configuration

`config.json` is rendered from the nOS service registry, so the menu lists the
services this estate actually enabled. Re-running the role regenerates it.

## Dependencies

- SSH (`sshd`) with `ForceCommand` support — the delivery mechanism
- Python (host `pyenv`/Homebrew interpreter) with `textual` + `rich`
- `sudo` for user creation and `sshd_config` edits
- The nOS service registry (feeds `config.json`)
