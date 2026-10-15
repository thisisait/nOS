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

## Roaming host (`nos_lan_roaming: true`)

A Mac that leaves its office LAN cannot bake one LAN address into its answers.

| Who asks | Instance | Listens on | Answers `*.<tenant_domain>` with |
|---|---|---|---|
| the Mac itself (`/etc/resolver`) | system, `homebrew.mxcl.dnsmasq` | `127.0.0.1` only | `127.0.0.1` |
| the tailnet (split DNS) | tailnet, `eu.thisisait.nos.dnsmasq-tailnet` | the Tailscale IP only | the Tailscale IP |

The tailnet instance is a second root LaunchDaemon with its own config
(`dnsmasq_tailnet_conf`, `/Library/LaunchDaemons/eu.thisisait.nos.dnsmasq-tailnet.plist`):
`bind-interfaces` on the Tailscale address, so it never meets the system instance on
`127.0.0.1:53`; `no-resolv`, so it answers the tenant domain and nothing else. launchd
retries it every 10 s until the Tailscale address exists after boot. Traefik publishes
443 on every interface, so `https://<svc>.<tenant_domain>` over the tailnet lands on it.

- Roaming with no Tailscale IPv4 (Tailscale down, logged out): the converge says so and
  skips; nothing fails. Not roaming: the instance is removed if present.
- Every removal level (`nos --remove=data` and up) boots it out and deletes both files.

**One manual step, in the person's own Tailscale admin console** (the converge has no
API key, by design): login.tailscale.com/admin/dns → Nameservers → Add nameserver →
Custom… → Nameserver: the Mac's Tailscale IP (`tailscale ip -4`) → turn on "Restrict
to domain" → Domain: `<tenant_domain>` → Save. MagicDNS alone is not enough: it names
the machine (`<host>.<tailnet>.ts.net`), never the `*.<tenant_domain>` vhosts Traefik
routes on.

**The phone must trust the mkcert root CA** (a local TLD gets mkcert certificates):
send `$(mkcert -CAROOT)/rootCA.pem` to the phone; iOS: install the profile, then
Settings → General → About → Certificate Trust Settings → enable it. Without it every
page is a certificate warning.

Check: `ansible-playbook main.yml --tags verify` digs `@<tailscale ip>` for one service
name — RED if it does not answer the Tailscale IP, UNKNOWN when Tailscale is down.
Gate: `tests/anatomy/test_a_roaming_host_answers_the_tailnet.py`.

## Off

`install_dnsmasq: false` must be AUTHORED in `config.yml`: the authored stop boots the
root daemon out (`become`, system domain) and removes the resolver files with it, so a
name never points at a dead `127.0.0.1:53`. A one-off `-e install_dnsmasq=false` stops
nothing (`tests/anatomy/test_host_daemon_stop_is_authored.py`).

## Is it working

- Health probe (manifest): TCP `127.0.0.1:53`.
- `dig @127.0.0.1 grafana.<tenant_domain>` answers the host address.
- `tools/undeclared-status.py` lists the daemon as declared (it rides the manifest row).
