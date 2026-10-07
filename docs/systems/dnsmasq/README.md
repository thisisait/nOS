# dnsmasq

> The host's own DNS answer for the local TLD, host-native (Homebrew formula, pinned
> `dnsmasq_version`; a root LaunchDaemon `homebrew.mxcl.dnsmasq`, domain `system`).
> Toggle `install_dnsmasq` (default `true`). Installed and configured by
> `tasks/dnsmasq.yml`; no role, plugin or Pulse job yet (the homes gate declares the gap).
> Manifest row since I-12 (2026-10-07): `stack: null`, `software_owner: symbiont`.

## What it does

1. dnsmasq listens on `127.0.0.1:53` (and the LAN address when `dnsmasq_lan_access`
   is true or `nos_edge: lan_tailscale`).
2. macOS `/etc/resolver/<tenant_domain>` sends every `*.<tenant_domain>` query to it
   (`dnsmasq_dev_domain` tracks `tenant_domain`; a second resolver covers `dev.lan`
   for the Bluesky PDS).
3. It answers the host's address (`dnsmasq_dev_address` from localhost, `nos_lan_ip`
   on the LAN) for every such name, so Traefik can route them. It carries no traffic;
   it only says where the names point. `dnsmasq_additional_addresses` adds records.

Public TLDs use real DNS; `dnsmasq_force_local_domains: true` keeps the local answer
beside them (hybrid mode).

## Off

`install_dnsmasq: false` must be AUTHORED in `config.yml`: the authored stop boots the
root daemon out (`become`, system domain) and removes the resolver files with it, so a
name never points at a dead `127.0.0.1:53`. A one-off `-e install_dnsmasq=false` stops
nothing (`tests/anatomy/test_host_daemon_stop_is_authored.py`).

## Is it working

- Health probe (manifest): TCP `127.0.0.1:53`.
- `dig @127.0.0.1 grafana.<tenant_domain>` answers the host address.
- `tools/undeclared-status.py` lists the daemon as declared (it rides the manifest row).
