# pazny.iiab_terminal

Ansible role for deploying **IIAB Terminal** — a public SSH TUI hub for the devBoxNOS homelab — on macOS. Part of [devBoxNOS](../../README.md).

IIAB Terminal is a Python [Textual](https://textual.textualize.io/) app that is launched through an SSH `ForceCommand` on a dedicated local user. Guests `ssh home@devbox` and land directly in the TUI with no shell access.

## What it does

1. Installs the `textual` and `rich` Python packages on the host pyenv interpreter
2. Creates the config directory (`{{ homebrew_prefix }}/etc/iiab-terminal/`)
3. Deploys the TUI application (`files/iiab-terminal/iiab_terminal.py`) and renders `config.json` from the service registry template
4. Creates a launcher script at `{{ homebrew_prefix }}/bin/iiab-terminal`
5. Creates the macOS user (default `home`) on first run, auto-generates a random password if not provided
6. Ensures the user home and `.ssh/` directory exist with correct permissions
7. Adds an SSH `Match User ... ForceCommand` block to `/etc/ssh/sshd_config` and notifies the shared `Restart ssh` handler

## Requirements

- macOS with Homebrew, pyenv with Python 3.13+
- `sudo` privileges for user creation and `sshd_config` edits
- The `files/iiab-terminal/` and `templates/iiab-terminal/config.json.j2` trees staying inside the playbook repo
- Play-level handler `Restart ssh` defined in the consuming playbook (the role does NOT redefine it, handlers resolve globally)

## Variables

| Variable | Default | Description |
|---|---|---|
| `iiab_terminal_user` | `home` | macOS user dedicated to the TUI (created if missing) |
| `iiab_terminal_password` | `""` | If empty, auto-generated on first run with `openssl rand -base64 12` |
| `iiab_terminal_password_auth` | `true` | Allow SSH password login for the dedicated user |
| `iiab_terminal_config_dir` | `{{ homebrew_prefix }}/etc/iiab-terminal` | Config + app directory |
| `iiab_terminal_bin_path` | `{{ homebrew_prefix }}/bin/iiab-terminal` | Launcher wrapper path used by `ForceCommand` |

## Usage

In the consuming playbook:

```yaml
- import_role:
    name: pazny.iiab_terminal
  tags: ['iiab-terminal', 'ssh']
```

## Rollback

Revert the commit that introduced this role and restore `tasks/iiab-terminal.yml` + the `import_tasks` call site in `main.yml`. The dedicated macOS user created on the host is not removed — delete it manually with `sysadminctl -deleteUser home` if desired. The SSH `ForceCommand` block inside `/etc/ssh/sshd_config` is removed automatically by `blockinfile` when the role is re-applied with `iiab_terminal` removed (or can be cleared manually).
