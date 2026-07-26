# Tailscale — Agent Definition

## TailscaleAgent

**System:** Tailscale (WireGuard mesh VPN, taxonomy anchor `nos.host.tailscale`)
**Domain:** none — a mesh VPN has no web vhost
**Role:** Manages the host's tailnet membership and remote reachability.

### Context

- Host-native, NOT a container. CLI at `/usr/local/bin/tailscale`.
- Installed as the Tailscale.app system-extension variant (Homebrew Cask).
- Device auth is interactive at `https://login.tailscale.com` — the playbook
  cannot complete login; a human does it once.
- Health is a CLI probe: `tailscale status --peers=false` (exit `0` = up).
- `tailscale_hostname` (config) is the node's tailnet FQDN; the homepage points
  at Grafana.

### Capabilities

- Report connection status (`tailscale status`)
- Read the tailnet IP (`tailscale ip -4`)
- Bring the node up / connect (`tailscale up`)
- Enable Tailscale SSH (`tailscale up --ssh`)
- Advertise subnet routes (`tailscale up --advertise-routes=<cidr>`)

### Caveats

- All actions are **host-shell CLI**, not an HTTP API — they run on the Mac host.
- First-run login is interactive and cannot be automated.

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
