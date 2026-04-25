# Domain Flip Operator Guide — `dev.local` → `pazny.eu`

End-to-end runbook for moving an nOS instance from the local-only
`dev.local` TLD to a real public domain. Targeted at this specific
setup: home box behind a residential router with a public IPv4, domain
registered at **Wedos**, DNS managed by **Cloudflare**.

The repo side of the flip is already done (commits `0896b65` +
`a77367b`). What remains is **infrastructure** outside the playbook —
DNS, certificates, port forwards, ISP rDNS — plus the actual config
edit + blank reset.

> **Prerequisites:** verify you have a real public IPv4 (not CGNAT)
> before starting. Run `curl ifconfig.me` from inside your LAN and
> `ssh public-vps curl https://ifconfig.me` separately if possible —
> if the two values match a genuine public IP you control, you're
> good. If your ISP gives you a 100.64.0.0/10 address, you're behind
> CGNAT and this guide will not work without changing ISP plan.

---

## Phase 0 — Decisions before you touch anything

| Question | Recommended answer | Why |
|---|---|---|
| Hide home IP behind Cloudflare proxy? | **Yes** for HTTPS, **no** for SMTP/IMAP | CF Free proxy hides origin IP for HTTPS apps; doesn't proxy SMTP at all (port 25 is dropped at edge). |
| Cloudflare or Wedos as authoritative DNS? | **Cloudflare** (delegate from Wedos) | CF gives free DDNS API, edge proxy, instant TTL, free ACME challenge support; Wedos UI for DNS is clunkier. |
| Wildcard cert vs per-host certs? | **Wildcard** (`*.pazny.eu`) | One cert covers all 50+ subdomains; nOS already configured for it. |
| ACME challenge type? | **DNS-01** (Cloudflare API) | Avoids opening port 80 to internet for HTTP-01 validation; works behind any proxy/firewall. |
| Inbound mail (`@pazny.eu` mailboxes)? | **Phase 2 only**, not now | Stalwart MTA + SPF/DKIM/DMARC + ISP rDNS + maybe smarthost — separate effort. |
| Outbound mail from local services? | **Phase 1 OK** via Mailpit (dev sink) | Apps relay into Mailpit at `mailpit:1025`; no real outbound until Stalwart lands. |
| Bluesky PDS federation? | **Phase 2** (needs valid LE cert + DNS) | Repo is ready (`bsky.pazny.eu` template); blocked on Phase 1 DNS + cert. |

---

## Phase 1 — Public DNS + HTTPS for web apps

### 1.1  Cloudflare account + zone

1. Register a Cloudflare account (free) — https://dash.cloudflare.com/sign-up.
2. **Add site** → enter `pazny.eu` → select **Free plan**.
3. Cloudflare scans existing DNS at Wedos. Review what gets imported and
   delete anything you don't recognise (Wedos default MX, parking
   placeholders, etc.).
4. CF gives you two nameservers — write them down, e.g.
   `tom.ns.cloudflare.com` + `lana.ns.cloudflare.com`.

### 1.2  Wedos — delegate nameservers to Cloudflare

1. Log into https://client.wedos.com/.
2. **Domény** → click `pazny.eu` → **Změna name serverů**.
3. Replace existing NS with the two Cloudflare nameservers from step 1.1.4.
4. Save. Propagation: 1–24 hours, usually under an hour. Check with
   `dig NS pazny.eu @1.1.1.1`.

> Once Cloudflare detects the delegation it sends a "site is active"
> email and the dashboard goes green. Don't proceed until that happens —
> ACME DNS-01 needs Cloudflare authoritative for the zone.

### 1.3  Cloudflare DNS records

In the Cloudflare dashboard for `pazny.eu`, **DNS** tab. Create:

| Type | Name | Content | Proxy | TTL | Why |
|---|---|---|---|---|---|
| A | `@` (apex) | `<your_public_ip>` | 🟠 Proxied | Auto | Web apps that hit `pazny.eu` directly |
| A | `*` (wildcard) | `<your_public_ip>` | 🟠 Proxied | Auto | Catches every `<svc>.pazny.eu` subdomain via one record |
| A | `mail` | `<your_public_ip>` | ⚪ DNS only | Auto | **MUST be DNS-only** — CF doesn't proxy SMTP, so MX records have to point at the unproxied origin |
| A | `pds` | `<your_public_ip>` | 🟠 Proxied | Auto | Bluesky PDS — proxy is fine, AT Protocol works over HTTPS |
| TXT | `@` | `v=spf1 ip4:<your_public_ip> ~all` | n/a | Auto | SPF — any SMTP relay you set up later must be in this record |
| MX | `@` (priority 10) | `mail.pazny.eu` | n/a | Auto | Optional now (no inbound mail yet); set to `mail.pazny.eu` for Phase 2 |

**Wildcard caveat:** Cloudflare does NOT proxy wildcard A records on
the Free plan unless you're on the new "always-proxied wildcard"
feature (2024+). If your dashboard shows a grey cloud you can't change,
either upgrade to Pro **or** add explicit per-app A records (`grafana`,
`wing`, `auth`, `api`, `mail`, `vault`, `pass`, …) instead of
relying on the wildcard. Check both before proceeding — if the
wildcard isn't proxied, your IP leaks via DNS.

### 1.4  Cloudflare API token (for ACME DNS-01)

1. https://dash.cloudflare.com/profile/api-tokens → **Create Token**.
2. Use **Custom token** (not the "Edit zone DNS" preset — too permissive).
3. Permissions:
   - `Zone` → `Zone` → `Read`
   - `Zone` → `DNS` → `Edit`
4. Zone Resources: **Include → Specific zone → pazny.eu** (don't grant
   access to all zones).
5. TTL: leave open or set 1 year — acme.sh re-uses it for every renewal.
6. Copy the token. You only see it once.

Put the token in your local `credentials.yml` (gitignored):

```yaml
acme_cloudflare_api_token: "vYxx…token-from-step-6"
```

### 1.5  Router — minimum port forwards

Your home router must forward two ports to your Mac's LAN IP. Find
your Mac's LAN IP (`ifconfig en0 | grep inet` on macOS, look for
192.168.x.x or 10.x.x.x).

| External port | Internal target | Protocol | Why |
|---|---|---|---|
| 443 | `<mac_lan_ip>:443` | TCP | HTTPS for every web app + ACME DNS-01 doesn't need this but Cloudflare proxy origin pulls do |
| 80 | `<mac_lan_ip>:80` | TCP | nginx redirects 80→443 + ACME HTTP-01 fallback if DNS-01 ever fails |

**Skip these for now** (Phase 2 only):

| External port | Why later |
|---|---|
| 25, 465, 587 | Inbound + outbound SMTP — only when Stalwart lands; many ISPs block 25 outbound on consumer plans (test with `nc -vz aspmx.l.google.com 25`) |
| 993 | IMAPS — only if you want to access mailboxes from outside the LAN |
| 22 | SSH — handled via Tailscale instead, leave closed |

Most consumer routers (Asus, MikroTik, AVM Fritz!Box, TP-Link) call
this **Port Forwarding**, **Virtual Server** or **NAT**. Make sure the
forward survives router reboots.

> **Test from outside your LAN:** `curl -v https://pazny.eu/cdn-cgi/trace`
> from a phone on cellular data after step 1.6. Should return a
> Cloudflare trace blob, not a connection refused.

### 1.6  Dynamic IP? Set up DDNS via Cloudflare API

If your ISP changes your public IP, you need a small daemon that
updates the A records when it changes. Cleanest option: `cloudflare-ddns`
running as a launchd agent on the Mac itself.

```bash
# Install via Homebrew (community formula)
brew install cloudflare-ddns

# Create config at ~/.config/cloudflare-ddns/config.toml
mkdir -p ~/.config/cloudflare-ddns
cat > ~/.config/cloudflare-ddns/config.toml <<EOF
[cloudflare]
api_token = "<same token as in credentials.yml>"

[[record]]
zone = "pazny.eu"
name = "@"
type = "A"

[[record]]
zone = "pazny.eu"
name = "*"
type = "A"

[[record]]
zone = "pazny.eu"
name = "mail"
type = "A"

[[record]]
zone = "pazny.eu"
name = "pds"
type = "A"
EOF

# launchd plist (every 5 min)
cat > ~/Library/LaunchAgents/eu.thisisait.nos.ddns.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>eu.thisisait.nos.ddns</string>
  <key>ProgramArguments</key>
  <array><string>/opt/homebrew/bin/cloudflare-ddns</string></array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF

launchctl load -w ~/Library/LaunchAgents/eu.thisisait.nos.ddns.plist
```

If your ISP confirms a static IP, skip this — A records stay valid forever.

> **Followup for the playbook:** if DDNS proves useful, fold it into a
> `pazny.cloudflare_ddns` role so it's reproducible on a fresh box.

### 1.7  Edit `config.yml` and run a blank reset

Once DNS propagation is done (CF dashboard green, `dig pazny.eu` shows
your IP) **and** the API token works (`curl -H "Authorization: Bearer
$TOKEN" https://api.cloudflare.com/client/v4/zones?name=pazny.eu`
returns success):

```yaml
# config.yml (gitignored)
instance_tld: "pazny.eu"
default_admin_email: "you@pazny.eu"   # gets cascaded to Authentik etc.
```

```yaml
# credentials.yml (gitignored)
acme_cloudflare_api_token: "vYxx…"
```

Then:

```bash
ansible-playbook main.yml -K -e blank=true
```

What happens automatically:
- `instance_tld_is_local` resolves `false` → mkcert + dnsmasq skip
- `pazny.acme` issues `*.pazny.eu` wildcard via Cloudflare DNS-01
- All 50+ nginx vhosts pick up `ssl_cert_path` → the new Let's Encrypt cert
- Authentik cookie domain becomes `.pazny.eu` (no manual config)
- Bluesky PDS hostname becomes `bsky.pazny.eu`

### 1.8  Smoke test after the blank

```bash
curl -I https://wing.pazny.eu/        # should return 302 → auth.pazny.eu
curl -I https://auth.pazny.eu/        # should return 200 with valid LE cert (no -k)
curl https://api.pazny.eu/api/health  # should return 200 from Bone

# Check the cert chain
echo | openssl s_client -connect grafana.pazny.eu:443 -servername grafana.pazny.eu \
  2>/dev/null | openssl x509 -noout -issuer -dates -subject
# Issuer should be Let's Encrypt R3; Subject should match *.pazny.eu
```

---

## Phase 2 — Real outbound mail (`admin@pazny.eu` not in spam)

> **Skip until Phase 1 is verified working.** Phase 2 only adds
> outbound mail via a real MTA (Stalwart), reverse DNS at the ISP, and
> SPF/DKIM/DMARC — none of that helps until the box itself is reachable
> on a real domain.

### 2.1  ISP — request reverse DNS (PTR) for your IP

This is the one thing you can't self-serve. Call/email your ISP and
ask for **reverse DNS** to be set on your IP to `mail.pazny.eu`. In
Czech ISPs:

- **T-Mobile / O2 / UPC / Vodafone:** business-tier accounts get this on
  request, no fee. Consumer accounts: hit-or-miss; some won't.
- **Smaller ISPs (CZNet, Nej.cz, etc.):** usually yes, ticket via
  customer portal.

Verification: `dig +short -x <your_public_ip>` should return
`mail.pazny.eu.` Without this, Gmail / Outlook will mark your mail as
spam regardless of SPF/DKIM/DMARC.

### 2.2  Cloudflare — finalise mail DNS

Replace the placeholder records from Phase 1 with the full mail set.
Replace `<DKIM_PUBLIC_KEY>` with the public key Stalwart will print on
first start (it's also visible in the admin UI).

| Type | Name | Content | TTL |
|---|---|---|---|
| MX | `@` (prio 10) | `mail.pazny.eu` | Auto |
| TXT | `@` | `v=spf1 mx ip4:<public_ip> ~all` | Auto |
| TXT | `default._domainkey` | `v=DKIM1; k=rsa; p=<DKIM_PUBLIC_KEY>` | Auto |
| TXT | `_dmarc` | `v=DMARC1; p=quarantine; rua=mailto:postmaster@pazny.eu; ruf=mailto:postmaster@pazny.eu; fo=1` | Auto |

> All three TXT records (SPF, DKIM, DMARC) are needed for modern mail
> providers to accept your mail. Test with https://www.mail-tester.com/
> after Stalwart is up — aim for 9/10 or higher.

### 2.3  Router — open SMTP ports

Add these forwards if you confirmed PTR is in place AND `nc -vz
aspmx.l.google.com 25` from your Mac shows the connection succeeds
(many ISPs block port 25 outbound):

| External port | Internal | Protocol | Why |
|---|---|---|---|
| 25 | `<mac>:25` | TCP | Inbound delivery (SMTP from other servers) |
| 587 | `<mac>:587` | TCP | Authenticated submission for clients |
| 465 | `<mac>:465` | TCP | SMTPS (legacy but widely required) |
| 993 | `<mac>:993` | TCP | IMAPS (only if you want remote mailbox access; otherwise stay LAN-only via Tailscale) |

If port 25 outbound is blocked, you have two options:
- **Smarthost relay** through Wedos's SMTP (login + AUTH) — Stalwart
  supports this natively; emails go out via `smtp.wedos.cz:587`
  authenticated, SPF includes Wedos.
- **VPS smarthost** — €5/mo Hetzner with Postfix relay; PTR + SPF on
  the VPS IP.

### 2.4  Add `pazny.stalwart` role + enable

Not yet committed. Will land in a separate PR with:
- `install_stalwart: false` opt-in
- `stalwart_admin_password` in credentials
- DKIM keypair generated on first run, public key shown for DNS step
- Wired to existing Authentik for admin UI OIDC

### 2.5  Switch service SMTP relays from Mailpit → Stalwart

Currently every service relays to `mailpit:1025` (dev sink, no
delivery). With Stalwart up:
- Stalwart becomes the authoritative outbound MTA for `@pazny.eu`
- Mailpit stays as a bcc sink for dev visibility (`stalwart →
  mailpit` chained relay) — switch is one variable in default.config.yml

---

## Phase 3 — Bluesky federation

Repo is ready (`bsky.pazny.eu` template, `install_bluesky_pds: true`),
but federation needs:
- Phase 1 DNS + Phase 1 wildcard cert (✓ after Phase 1)
- Public reachability on 443 to `pds.pazny.eu` (✓ if Cloudflare proxies
  it — AT Protocol does work behind CF proxy)
- The legacy `-invite-code` flag bug fixed (CLI → API migration in
  `tasks/stacks/bluesky_pds_bridge.yml`)

The bridge bug is tracked separately. Once it's fixed, federation
works automatically because the playbook already templates the
hostname.

---

## Recovery / rollback

If anything breaks during the flip and you want to go back to dev:

1. Comment out `instance_tld: pazny.eu` in `config.yml` (falls back to
   default `dev.local`).
2. `ansible-playbook main.yml -K -e blank=true` — full reset.
3. Cloudflare DNS records can stay; Wedos delegation can stay (they're
   inert without a running server).

For a softer rollback (no blank), `instance_tld_is_local: true` as an
extra var forces the local path even on a public TLD — useful for
debugging.

---

## Operator checklist (TL;DR — print this)

- [ ] Confirm public IPv4 (not CGNAT)
- [ ] Cloudflare account + add `pazny.eu`
- [ ] Wedos: delegate NS to Cloudflare (wait for CF green)
- [ ] CF: A wildcard + apex + `mail` (DNS only) + `pds`
- [ ] CF: API token (Zone:DNS:Edit, scoped to `pazny.eu`)
- [ ] Router: forward 80 + 443 to Mac LAN IP
- [ ] (If dynamic IP) `cloudflare-ddns` launchd agent
- [ ] `config.yml`: `instance_tld: pazny.eu`
- [ ] `credentials.yml`: `acme_cloudflare_api_token: "..."`
- [ ] `ansible-playbook main.yml -K -e blank=true`
- [ ] Smoke: `curl -I https://wing.pazny.eu/`
- [ ] (Phase 2) ISP rDNS request
- [ ] (Phase 2) MX + SPF + DKIM + DMARC at CF
- [ ] (Phase 2) Router: 25/465/587/993 (if needed)
- [ ] (Phase 2) Stalwart role + flip mail relay
