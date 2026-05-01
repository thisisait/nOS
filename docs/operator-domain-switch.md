# Operator guide — domain switch (dev.local → your real TLD)

> **Goal:** flip `tenant_domain` from `dev.local` to a public TLD (e.g.
> `pazny.eu`) and bring up production-grade TLS, mail, and Bluesky
> federation. End state: every service on `*.<your-domain>` with a real
> Let's Encrypt wildcard cert, Stalwart sending mail under your domain,
> Bluesky PDS reachable for AT Protocol federation.
>
> Time budget: ~30 min of clicking + 1 blank run. **Do this once per host.**

---

## Pre-flight — what you need

- Registrar account where the domain lives (wedos / namecheap / google
  domains / …). You need access to the **nameserver** settings.
- Cloudflare account (free tier is fine).
- Public IP or Tailscale Funnel hostname for inbound 443 (and 25/465/587/993
  if you want Stalwart SMTP).
- Router admin access (for port forwarding).

---

## Step 1 — Cloudflare zone setup

### 1.1 Add the domain to Cloudflare

1. Login to <https://dash.cloudflare.com/>
2. **Add a Site** → enter `<your-domain>` → **Free plan** → Continue
3. Cloudflare scans existing DNS → review, accept defaults, Continue
4. **Cloudflare gives you 2 nameservers** — copy them:
   - `<NS1>.ns.cloudflare.com`
   - `<NS2>.ns.cloudflare.com`
5. Don't close this tab yet — Cloudflare needs the nameserver flip in step 2.

### 1.2 Get an API token (DNS-01 ACME challenge)

While Cloudflare's "Activate Site" page is open in another tab:

1. Top-right profile menu → **My Profile** → **API Tokens** → **Create
   Token**
2. Use the **"Edit zone DNS"** template
3. **Permissions:**
   - `Zone` → `DNS` → `Edit`
   - `Zone` → `Zone` → `Read`
4. **Zone Resources:**
   - Include → Specific zone → `<your-domain>`
5. **TTL:** leave default (1 year is fine; rotate annually)
6. **Continue → Create Token → COPY THE TOKEN** (shown once, can't recover)
7. Paste into your local `credentials.yml`:
   ```yaml
   acme_cloudflare_api_token: "cf-NjU2…paste-here…"
   ```

### 1.3 Verify the token works

```bash
curl -fsS \
  -H "Authorization: Bearer $(yq '.acme_cloudflare_api_token' credentials.yml)" \
  https://api.cloudflare.com/client/v4/user/tokens/verify \
  | jq .result.status
# Expected: "active"
```

---

## Step 2 — wedos (or your registrar) nameserver flip

This step **breaks anything currently using your domain** until step 3 lands
the new DNS records. If your domain is already on Cloudflare or you've
parked it, skip to step 3.

### wedos.cz (Czech registrar)

1. Login to <https://klient.wedos.com/>
2. **Domény** → click your domain
3. **DNS servery** tab → **Změnit** button
4. **Vlastní DNS servery** → paste:
   ```
   <NS1>.ns.cloudflare.com
   <NS2>.ns.cloudflare.com
   ```
5. **Uložit** → wedos sends a confirmation email → click the link
6. Propagation: usually 5–30 min, can stretch to 24 h on first change.
   Track with `dig +short NS <your-domain>`. Expect to see the Cloudflare
   nameservers when it's done.

### Other registrars (namecheap / google / godaddy)

Same idea, different UI:

- **namecheap:** Dashboard → Domain List → Manage → Nameservers → Custom DNS
- **google:** dns.google → My domains → DNS → Custom name servers
- **godaddy:** Domain Manager → DNS → Nameservers → I'll use my own

After flipping, return to the Cloudflare tab and click **"Check
nameservers"** at the bottom. Cloudflare will email you when the zone is
**Active** (state changes from Pending → Active).

---

## Step 3 — Cloudflare DNS records

Once the zone is Active in Cloudflare:

### 3.1 Wildcard A record (Tier-1 + Tier-2 services)

| Type | Name | Content | Proxy | TTL |
|---|---|---|---|---|
| `A` | `@` | `<your-public-IP>` | DNS only (grey cloud) | Auto |
| `A` | `*` | `<your-public-IP>` | DNS only (grey cloud) | Auto |
| `A` | `*.apps` | `<your-public-IP>` | DNS only (grey cloud) | Auto |

> **Why grey cloud:** Cloudflare's orange-cloud proxy terminates TLS at
> CF's edge and re-encrypts to your origin. For nOS we want the LE wildcard
> cert pazny.acme issues to be the actual TLS endpoint — keep it grey.
> You can flip individual records to orange later (e.g. `wing.<td>` for
> DDoS protection on the operator dashboard).

### 3.2 Bluesky PDS (only if `install_bluesky_pds: true` + you want federation)

| Type | Name | Content | Proxy | TTL |
|---|---|---|---|---|
| `A` | `bsky` | `<your-public-IP>` | DNS only | Auto |

### 3.3 Mail (only if `install_smtp_stalwart: true`)

| Type | Name | Content | Proxy | TTL |
|---|---|---|---|---|
| `A` | `mail` | `<your-public-IP>` | DNS only | Auto |
| `MX` | `@` | `mail.<your-domain>` (priority 10) | — | Auto |
| `TXT` | `@` | `v=spf1 mx ~all` | — | Auto |
| `TXT` | `_dmarc` | `v=DMARC1; p=quarantine; rua=mailto:dmarc@<your-domain>` | — | Auto |

DKIM key — paste from Stalwart's webadmin **after first deploy**:

| Type | Name | Content | Proxy | TTL |
|---|---|---|---|---|
| `TXT` | `default._domainkey` | (Stalwart shows the key on first boot) | — | Auto |

### 3.4 (future) Mastodon (`install_mastodon: true`)

| Type | Name | Content | Proxy | TTL |
|---|---|---|---|---|
| `A` | `social` | `<your-public-IP>` | DNS only | Auto |

---

## Step 4 — Router port forwarding

Forward these ports from your router's WAN side to your nOS host's LAN IP:

| Port | Protocol | Target | Purpose |
|---|---|---|---|
| 80 | TCP | host:80 | Traefik HTTP → 308 → HTTPS (and ACME HTTP-01 fallback) |
| 443 | TCP | host:443 | Traefik HTTPS — every web service |
| 25 | TCP | host:25 | Stalwart SMTP MTA (incoming mail) |
| 465 | TCP | host:465 | Stalwart implicit-TLS submission (clients) |
| 587 | TCP | host:587 | Stalwart STARTTLS submission (clients) |
| 993 | TCP | host:993 | Stalwart IMAPS (clients) |

> **Many home ISPs block outbound 25** to fight spam botnets. If your `swaks
> --to <you>@gmail.com --server localhost` succeeds locally but mail never
> arrives at gmail, your ISP is blocking 25. Two workarounds:
>
> 1. Ask the ISP to whitelist (sometimes free with a static IP)
> 2. Configure Stalwart to relay outbound mail through a paid SMTP relay
>    (Mailgun, Sendgrid free tier, or AWS SES) — keep your domain, hide your IP

### Tailscale Funnel alternative (no port forward, no public IP)

If your home doesn't have a routable public IPv4 (CGNAT, mobile broadband,
…) **or** you prefer not to expose your home IP:

1. Install Tailscale on the nOS host (`brew install --cask tailscale`)
2. `tailscale funnel 443` enables external HTTPS via Tailscale's edge
3. Set `<your-public-IP>` in step 3.1 to the Tailscale funnel hostname
   (`<machine>.<tailnet>.ts.net` resolves to a stable IP)
4. Stalwart SMTP requires raw TCP — Funnel is HTTPS-only as of 2026, so
   **mail can't go via Funnel**. Use a SMTP relay service instead.

---

## Step 5 — Flip the playbook

### 5.1 `config.yml`

```yaml
# Before:
instance_name: "nos"
instance_tld: "dev.local"
default_admin_email: "admin@dev.local"
external_storage_root: "/Volumes/SSD1TB"

# After:
instance_name: "nos"
tenant_domain: "<your-domain>"        # renamed from instance_tld (auto-promote covers legacy)
# host_alias: ""                       # set per-box for fleet (lab, factory, …)
external_storage_root: "/Volumes/SSD1TB"

# Production toggles (uncomment as you go):
# install_smtp_stalwart: true          # AFTER step 3.3 DNS records land
# bluesky_pds_public_federation: true  # AFTER step 3.2 DNS record + cert
# install_mastodon: true               # future
```

You can drop `default_admin_email` — the auto-derived `admin@<tenant_domain>`
is what every service uses by default.

### 5.2 `credentials.yml`

```yaml
# Add (replaces the empty default):
acme_cloudflare_api_token: "cf-…paste-from-step-1.2…"
```

### 5.3 First production blank

```bash
# This is the migration blank. Backs up current data, wipes it, redeploys
# under the new TLD. Allow ~30 min.
ansible-playbook main.yml -K -e blank=true
```

Expected progression:

1. Track F auto-promote pre-task fires, prints deprecation warning if you
   left `instance_tld` in config.yml — rename to `tenant_domain` and the
   warning goes away.
2. mkcert SKIPPED (because tenant_domain is non-local) → ACME runs
3. acme.sh registers LE account → DNS-01 challenge succeeds in ~10 s →
   wildcard cert lands in `~/stacks/infra/tls/acme/<your-domain>.crt`
4. Traefik picks up the new cert; every service now serves
   `https://<svc>.<your-domain>` with a green padlock
5. Smoke catalog probes the new hosts — all 39+ should return 200

If `acme.sh` step fails, see [`roles/pazny.acme/README.md`](../roles/pazny.acme/README.md)
troubleshooting section.

---

## Step 6 — Verify

```bash
# 1. DNS resolves your domain to your public IP
dig +short <your-domain> @1.1.1.1

# 2. Wildcard cert is real Let's Encrypt
echo | openssl s_client -servername wing.<your-domain> -connect <your-domain>:443 2>/dev/null \
  | openssl x509 -noout -issuer -subject -dates
# Expected: issuer = "C = US, O = Let's Encrypt, CN = R3" (or similar)

# 3. nos-smoke against the new domain
python3 tools/nos-smoke.py --tenant-domain "<your-domain>"

# 4. SSO end-to-end with tester identity
python3 tools/nos-smoke.py --tenant-domain "<your-domain>" --strict
# Expected: 39/39 OK · 0 failed

# 5. (if Stalwart on) send a test mail
swaks --to your-other-mailbox@gmail.com --server mail.<your-domain> \
      --auth-user admin --auth-password "<see credentials.yml>"
```

If any line is red, **don't blank again** — diagnose with `--failed-only` and
re-run individual roles via `--tags`.

---

## Step 7 — Rolling back

If you need to revert to dev:

```yaml
# config.yml
tenant_domain: "dev.local"
```

Run `ansible-playbook main.yml -K -e blank=true` again. mkcert takes over
the TLS layer; ACME goes dormant; the LE cert in `acme/` stays on disk
(it'll expire in 90 days but doesn't bother anything).

Cloudflare zone stays Active — no harm in leaving it for the next attempt.

---

## Reference

- [`roles/pazny.acme/README.md`](../roles/pazny.acme/README.md) —
  Cloudflare DNS-01 challenge mechanics
- [`roles/pazny.smtp_stalwart/`](../roles/pazny.smtp_stalwart/) — production
  mail server (SMTP/IMAP/JMAP)
- [`docs/operator-domain-naming.md`](operator-domain-naming.md) — Track F
  variable composition (tenant_domain + host_alias + apps_subdomain)
- [`docs/roadmap-2026q2.md`](roadmap-2026q2.md) Track G — full Track G plan
