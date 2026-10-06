# Tailscale

> WireGuard mesh VPN, host-native (Homebrew cask, or the operator's own Tailscale.app —
> `tasks/tailscale.yml` finds an existing CLI and installs nothing then). Toggle
> `install_tailscale` (default `true`). Health: `tailscale status --peers=false`, rc 0.

## nos_edge: lan_tailscale — one name per service, inside and outside

No public IP, no Cloudflare. Every service keeps ONE name (`files.<tenant_domain>`):
the office router hands out this host as DNS, dnsmasq answers `nos_lan_ip`, and the
tailnet's split DNS sends the same names to the same address from anywhere. Users
never see the tailnet name. Certificates are public (ACME DNS-01 at the registrar,
`acme_dns_provider`), so no device has to trust a private CA. Funnel: never — the
preflight refuses any `tailscale_funnel*` variable and `--tags verify` fails if it is on.

**Set:** `nos_edge: lan_tailscale`, `nos_lan_ip` (the address the router reserves) in
`config.yml`; `tailscale_auth_key` (admin console → Settings → Keys) in
`credentials.yml`. The converge runs `tailscale up --advertise-routes=<nos_lan_ip>/32`
once, only on a node that is not up; a node already up gets the route via `tailscale set`.

**Router (once):** reserve the host's IP in DHCP; set DHCP's DNS server to that IP.

**Admin console (once, the converge cannot do it — no API key by design):**

1. login.tailscale.com/admin/machines → this host → ⋯ → Edit route settings →
   approve `<nos_lan_ip>/32` → Save.
2. login.tailscale.com/admin/dns → Nameservers → Add nameserver → Custom… →
   Nameserver: `<nos_lan_ip>` → turn on "Restrict to domain" → Domain:
   `<tenant_domain>` → Save.

macOS, iOS and Windows clients use approved routes by default; a Linux client needs
`tailscale up --accept-routes`.

## Is it working

- `ansible-playbook main.yml --tags verify` — RED (fails the play) unless the node is
  up, the /32 is advertised AND approved, and `dig @<nos_lan_ip>` answers `nos_lan_ip`;
  UNKNOWN without the CLI.
- `tools/tailscale-status.py` — the same, read-only, any time.

Neither can see the tailnet's DNS settings (that needs an API key). The end-to-end
check is a phone on mobile data with Tailscale on: `https://grafana.<tenant_domain>`
must open with a valid certificate.

## Other knobs

- `tailscale_hostname` — the node's tailnet FQDN; its first label becomes `--hostname`.
- `services_lan_access: true` binds services on `0.0.0.0` (reachable by port).
