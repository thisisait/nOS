# ADR-0003 — Cloudflare Authenticated Origin Pulls on the Traefik edge

Status: **accepted design, prepared-not-armed** · 2026-09-03 ·
Roadmap: `sec-origin-answers-anyone` (operator chose option (a), 2026-09-03)

## The problem, measured

24h of edge log (2026-09-03): ~60 requests carry an IP-literal Host — mass-IPv4
scanners hold the WAN IP despite fully CF-proxied DNS — plus 4,669 no-router
requests of hostname noise, incl. router-RCE probes (`/cgi-bin/luci`). All died
in Traefik 404s, but the origin answers 80/443 **from any source**, so the CF
proxy is anonymity, not a gate.

The obvious fix is dead on arrival: an `ipAllowList` of CF ranges cannot work,
because Docker port-publish NATs every external source to `192.168.65.1`
(measured in the same log). mTLS is NAT-immune — the client's certificate
arrives inside the handshake, not in the IP header.

## The mechanism

Cloudflare's *Authenticated Origin Pulls*: when enabled per zone, every CF→origin
TLS connection presents a client certificate signed by Cloudflare's origin-pull
CA. The origin requires and verifies it; any handshake without it — every
scanner — dies before a byte of HTTP.

**Where it lands is one place.** `traefik.yml.j2` already sets a default TLS
option for the whole `websecure` entrypoint (`options: "modern@file"`), and
`middlewares.yml.j2` §TLS options owns `modern`. The entire change:

```yaml
# middlewares.yml.j2 — inside tls.options.modern, Jinja-gated:
{% if traefik_origin_mtls | default(false) %}
      clientAuth:
        caFiles:
          - /etc/traefik/origin-pull-ca.pem
        clientAuthType: RequireAndVerifyClientCert
{% endif %}
```

plus the CA PEM vendored into the role (`files/origin-pull-ca.pem`, from
https://developers.cloudflare.com/ssl/origin-configuration/authenticated-origin-pull/
— a foreign property: record its NotAfter and let `brew-pin`-style staleness
reporting own the expiry watch), mounted by the compose template beside the
existing certs.

## Why the flag, and its gates (prepared-not-armed doctrine)

`traefik_origin_mtls: false` in `default.config.yml`. Arming is an operator
edit in `config.yml` **after** the CF-zone half exists — the two halves fail
closed in opposite directions and must flip in this order:

1. CF zone: enable Authenticated Origin Pulls (dashboard/API). CF now SENDS
   the cert; origins that ignore it are unaffected.
2. Estate: `traefik_origin_mtls: true` + converge. Origin now REQUIRES it.

Flipping (2) before (1) is a self-inflicted outage of every public route; the
converge must refuse it. The preflight gate: when `traefik_origin_mtls` is
true, an `openssl s_client` probe through the CF edge must show CF presenting
a client-cert request being satisfied — concretely, `curl https://<apex>` via
CF answers 2xx/3xx while a direct `--resolve <apex>:443:127.0.0.1` handshake
WITHOUT a client cert is refused. Both measured, neither assumed.

## Every non-CF handshaker, enumerated

| caller | today | under mTLS | verdict |
| --- | --- | --- | --- |
| browsers, LAN + Tailscale | DNS → CF → origin | unchanged (CF carries the cert) | fine |
| smoke, primary probes | via CF | unchanged | fine |
| smoke, **loopback retry** | direct 127.0.0.1:443 | handshake refused | acceptable: the retry only fires when the CF path already failed; a refused rescue is honest UNREACH, not a false DEAD. Note in `_probe_via_loopback`. |
| CI wet-test (`dev.local`) | direct, no CF exists | would break everything | **flag stays false**: `tenant_domain_is_local` estates never arm; the preflight refuses `traefik_origin_mtls=true` + local TLD as a contradiction |
| internal callers (Bone, Wing, outpost, connectors, Kuma) | loopback ports / container aliases, never the public 443 | unaffected | verified pattern: every post-start task talks to `127.0.0.1:<port>` or `<svc>:<port>` |
| fee-43 debug recipe (`docker exec … curl -H Host:` at Traefik) | direct | refused | update the recipe text: add `--cert/--key` with the CF cert is NOT possible (we hold only the CA) — the in-container probe moves to the service port, not the edge |
| port 80 | redirect-to-https for anyone | mTLS cannot exist on plain HTTP | residual knock accepted; CF "Always Use HTTPS" + (operator router checklist) consider dropping the :80 forward entirely |

## What this deliberately does not do

- **No second entrypoint** for LAN/tailscale direct access — nothing measured
  uses one today. If a direct-to-origin consumer ever appears, it gets its own
  entrypoint with its own declared TLS options; punching a hole in `modern` is
  refused in advance.
- **No per-router carve-outs** — the default-option design is the point: one
  decision, every public router, no drift surface.
- **No CRL/OCSP machinery** — the CA file is the trust root; rotation is a
  vendored-file bump, same class as any other pin.

## Gates that ship with the implementation

1. Shape: `modern` carries `clientAuth` iff the flag renders true; the CA file
   is mounted iff the flag is true (mkcert-CA-gate precedent — key on the
   container path, not a var name).
2. Contradiction: `traefik_origin_mtls=true` with a local TLD refuses at
   preflight (same voice as the forward-auth-without-Authentik refusal).
3. Live (`--tags verify`, armed estates only): the two-sided probe above —
   through-CF answers, direct-without-cert is refused. A gate that only
   checks the config would certify the flag, not the lock.

## Rollout

1. This ADR + role changes land dormant (flag false, CA vendored, gates 1–2).
2. Operator flips the CF zone toggle (their dashboard, their act).
3. Operator sets `traefik_origin_mtls: true` in config.yml; converge; gate 3
   runs; `tools/edge-scan` (the 24h log reader) should show IP-literal and
   hostname-noise requests dying at handshake — the knock is gone.
