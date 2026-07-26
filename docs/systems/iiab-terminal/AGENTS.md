# IIAB Terminal — Agent Definition

## IIAB Terminal (kiosk shell, not an addressable agent)

**System:** IIAB Terminal (host organ, non-Docker; Python Textual TUI)
**Node:** `nos.host.iiab-terminal`
**Role:** A forced-shell menu for a console-only kiosk account. It hands an SSH guest a navigable list of homelab services instead of a bare prompt. It is a human-facing UI, not an automation surface.

### Context

- Access: `ssh home@<host>` → `sshd_config` `ForceCommand /opt/homebrew/bin/iiab-terminal`.
- Kiosk user: `home` (created on first run; SSH password auth, no shell, no TCP/X11 forwarding).
- App + config: `/opt/homebrew/etc/iiab-terminal/` (`iiab_terminal.py`, `config.json` rendered from the service registry).
- No port, no domain, no SSO, no daemon.

### Capabilities

- Present an interactive menu of enabled homelab services to a console guest.

### Automation Note

IIAB Terminal exposes no callable actions — see [SKILLS.md](SKILLS.md). An
orchestrator cannot dispatch to it; provisioning and menu contents are managed
entirely by `roles/pazny.iiab_terminal` through the playbook.
