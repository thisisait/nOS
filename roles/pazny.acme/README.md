# pazny.acme — Let's Encrypt wildcard via acme.sh + Cloudflare DNS-01

**Status:** scaffolded since Track A (2026-04-26), production-ready since Track G (2026-05-01).

Issues a wildcard cert (`*.<tenant_domain>` + `*.<apps_subdomain>.<tenant_domain>`)
via the [acme.sh](https://acme.sh) CLI, using the Cloudflare DNS-01
challenge. Output lands in the same shared TLS tree (`{{ tls_cert_dir }}/acme/`)
that mkcert writes to in dev mode — Traefik consumes both transparently.

## When does it run

Auto-derived from `tenant_domain`:

- `tenant_domain` ends in `.local` / `.lan` / `.test` / `.localhost` →
  `tenant_domain_is_local: true` → ACME **disabled**, mkcert generates a
  self-signed wildcard for the dev CA.
- Anything else → `tenant_domain_is_local: false` → `install_acme: true`
  by default → ACME runs.

## Operator setup (one-time per host)

### 1. Cloudflare API token

Get a token with `Zone:DNS:Edit` + `Zone:Zone:Read` scopes:

```
https://dash.cloudflare.com/profile/api-tokens
  → Create Token → "Edit zone DNS" template
  → Zone Resources: Include → Specific zone → <your domain>
  → Continue → Create Token → COPY THE TOKEN (shown once)
```

Paste into `credentials.yml`:

```yaml
acme_cloudflare_api_token: "cf-NjU2ZjY1NmY2NTZmNjU2ZjY1NmY2NTZmNjU2Zg…"
```

### 2. Tenant domain in `config.yml`

```yaml
tenant_domain: "your-domain.example"
# host_alias: ""   # uncomment for fleet deploys (lab.your-domain.example)
```

### 3. Run the role

```bash
ansible-playbook main.yml -K --tags acme
```

First run takes ~30 s — acme.sh registers the LE account, requests the
wildcard, waits for DNS propagation (a few seconds via the CF API), and
symlinks the resulting fullchain into `{{ ssl_cert_path }}` so Traefik
reads it on the next reload.

## What gets issued

With `tenant_domain: pazny.eu` + default `host_alias=""`:

```
Subject: *.pazny.eu
SANs:    pazny.eu
         *.apps.pazny.eu
```

With `host_alias: lab` + `tenant_domain: pazny.eu`:

```
Subject: *.lab.pazny.eu
SANs:    lab.pazny.eu
         *.lab.apps.pazny.eu
```

The cert filename uses the wildcard apex (`acme_cert_zone`) — so multiple
host_alias deploys against the same tenant get separate cert files in the
same `acme/` directory, no collision.

## Renewal

`pazny.acme` installs a launchd plist (`eu.thisisait.nos.acme-renew`) that
runs daily at 03:30 local time. acme.sh internally checks the cert expiry
and only renews when it's within `acme_renewal_days` (default 60) of expiry
— so a daily run is cheap (one HTTPS call to LE's OCSP) and only re-issues
~ once every 60 days.

After a renewal, the launchd job runs the `--renew-hook` which restarts
Traefik (or host nginx if `install_nginx: true`) to pick up the new file.

## Troubleshooting

**`Cert success` not in stdout, but task didn't fail**

The renewal task accepts `'is not expired yet' in stdout` as a success
signal — acme.sh's idempotency message. The current cert is still valid.

**`error: Cannot validate domain` from the DNS-01 challenge**

Cloudflare token is wrong / lacks scopes. Confirm:

```bash
curl -fsS -H "Authorization: Bearer $CF_TOKEN" \
     https://api.cloudflare.com/client/v4/user/tokens/verify
```

Expect `"status": "active"`. Re-issue with the right scopes if not.

**`Nameserver of <domain> is not Cloudflare`**

You haven't pointed your registrar's nameservers to Cloudflare yet.
See [`docs/operator-domain-switch.md`](../../docs/operator-domain-switch.md)
for the wedos → Cloudflare nameserver flip.

**Acme.sh stuck "still waiting for DNS propagation"**

DNS-01 challenge cycle is normally < 10 s; if it loops > 60 s, check that
the zone is **active** in Cloudflare (not pending NS verification) and
that no other DNS provider holds an old `_acme-challenge.<td>` record.
