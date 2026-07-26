# Tailscale

> Tailscale — WireGuard mesh VPN. Gives the host a stable private address
> reachable from the operator's other devices without opening a router port.
> Exposes the estate's services remotely without port forwarding.

## Quick Reference

| | |
|---|---|
| **Type** | Host-native (NOT a Docker service) — installed on the Mac host |
| **Stack** | none (`stack: null` → taxonomy anchor `nos.host.tailscale`) |
| **Toggle** | `install_tailscale: true` (default **`true`** — on by default) |
| **Install** | Homebrew Cask `tailscale` (`tasks/tailscale.yml`) — the Tailscale.app system-extension variant |
| **CLI** | `/usr/local/bin/tailscale` (shim installed by the app) |
| **Version source** | `homebrew` (`brew_formula: tailscale`) |
| **Domain / Port** | none — a mesh VPN has no web vhost and no published port |
| **Data** | none managed by nOS |
| **SSO** | none — device auth is at `https://login.tailscale.com` |

Because it is a system-extension app (not a `brew` formula), the manifest health
check probes the **CLI**, not formula presence — a scout side-find (2026-06-11)
saw the mirror report `healthy:false` for a working VPN when it keyed off the
missing brew formula.

## Configuration

- `tailscale_hostname` (default `""`) — the node's tailnet FQDN, e.g.
  `mac-studio.tailnet-abc.ts.net`. Set in `config.yml`; the homepage
  (`https://<tailscale_hostname>/`) points at Grafana.
- `services_lan_access: true` binds Docker services on `0.0.0.0` so they are
  reachable over the tailnet by port (e.g. `http://<host>.<tailnet>.ts.net:3000`
  for Grafana). Default `false` keeps services on loopback.

## First-run setup (manual)

Tailscale requires an interactive login the playbook cannot perform:

1. Open **Tailscale** in Applications.
2. Click **Log in** and sign in at `https://login.tailscale.com`.
3. The host then appears as a node in your tailnet.

## Health Check

- **Type:** `exec` (host CLI, not HTTP)
- **Command:** `tailscale status --peers=false`
- **Expected:** exit code `0` (the daemon is up and the node is authenticated).

## Dependencies

- `tailscaled` (the Tailscale system extension daemon) running on the host.
- None inside the nOS compose estate — Tailscale wraps the host network, it does
  not depend on any nOS service.
