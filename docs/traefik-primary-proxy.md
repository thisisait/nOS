# Traefik as primary edge proxy

As of C1 (2026-04-29), Traefik in a container is the **default and
only** edge proxy on a fresh nOS install. Host nginx (Homebrew) is
opt-in only via `install_nginx: true`, retained as a fallback for
operators with bespoke vhost-level constraints. The `pazny.nginx_container`
role and the legacy host-nginx-to-container migration (the D1 layer)
have been removed — they shipped briefly and never landed on a
deployed instance.

> **Why the cutover?** A reverse proxy that requires a Homebrew
> install pins nOS to macOS for the front door. Containerising it is
> a precondition for the Linux port. We considered nginx-in-container
> but Traefik's two-provider model (Docker labels for Tier-2,
> file provider for Tier-1) lets us auto-derive routing from
> `state/manifest.yml` without touching the existing 50+ `pazny.*`
> roles, which made the cutover materially cheaper.

---

## Architecture

Traefik runs as the `traefik` service in the `infra` compose stack.
It binds 80/443 unconditionally and reads two providers:

```yaml
# roles/pazny.traefik/templates/traefik.yml.j2 (static config)
providers:
  docker:
    exposedByDefault: false   # explicit opt-in via labels
    network: shared_net
  file:
    directory: /dynamic
    watch: true
```

### File provider (Tier-1)

`/dynamic/services.yml` is rendered from `state/manifest.yml` —
every service with `domain_var` + `port_var` set in the manifest
gets a router + service block. No per-role edits — one central YAML.

`/dynamic/middlewares.yml` defines:

- `authentik@file` — forward-auth → `http://authentik-server:9000/outpost.goauthentik.io/auth/traefik`
- `security-headers@file` — HSTS + content-type-nosniff + XSS filter
- `compress@file` — gzip + brotli
- `noverify@file` — `serversTransport` for self-signed upstream HTTPS

### Docker provider (Tier-2)

Apps in the `apps` compose stack emit Traefik labels in their compose
service block. The runner (`library/nos_apps_render.py`) auto-generates
labels from the manifest:

```
traefik.enable=true
traefik.docker.network=shared_net
traefik.http.routers.<slug>.rule=Host(`<slug>.apps.<tld>`)
traefik.http.routers.<slug>.entrypoints=websecure
traefik.http.routers.<slug>.tls=true
traefik.http.services.<slug>.loadbalancer.server.port=<port>
traefik.http.routers.<slug>.middlewares=authentik@file,security-headers@file,compress@file
```

The middleware list drops `authentik@file` for `nginx.auth: none` /
`oidc` apps.

### TLS

Traefik reads the same cert path nginx used to read
(`{{ tls_cert_path }}` / `{{ tls_key_path }}`). mkcert wildcards or
real LE wildcards Just Work — the `pazny.acme` task drops a copy at
`{{ traefik_certs_dir }}` so the file provider can mount it
read-only.

For a brand-new dev box, mkcert produces `*.dev.local` wildcards via
`pazny.dotfiles` and the rest is automatic.

---

## Tier-1 vs Tier-2

| Layer  | How services get routed                                               | Source of truth                |
| ------ | --------------------------------------------------------------------- | ------------------------------ |
| Tier-1 | File provider — `traefik_dynamic_dir/services.yml` rendered from manifest | `state/manifest.yml`           |
| Tier-2 | Docker provider — labels emitted by `nos_apps_render`                 | `apps/<name>.yml` manifests    |

**Why both?** The Tier-1 catalog is operator-edited per-instance via
the `install_*` flag set; routing it through file-provider keeps the
50+ existing `pazny.*` roles unmodified. The Tier-2 catalog is YAML-
driven by manifests — labels in compose are the natural fit for
templates the runner generates from a single source.

---

## Authentik forward-auth flow

User hits `https://<service>.<tld>` →

1. Traefik `authentik@file` middleware fires →
2. `http://authentik-server:9000/outpost.goauthentik.io/auth/traefik`
   over Docker DNS →
3. Authentik returns 302 → `https://auth.<tld>/...` →
4. User logs in (or session cookie matches) →
5. Authentik returns 302 → original URL →
6. Traefik forwards the request with `X-authentik-username`,
   `X-authentik-groups`, `X-authentik-email`, `X-authentik-name`,
   `X-authentik-uid` headers set →
7. Backend application sees the headers, treats user as logged in.

The `Location` rewrite (so the browser sees `auth.<tld>` instead of
the Docker-internal name) is handled by Authentik's outpost; we don't
patch headers at the Traefik level.

---

## Operator quick reference

### Where things live

```
roles/pazny.traefik/
  defaults/main.yml
  tasks/main.yml                  # renders all of the below
  templates/
    compose.yml.j2                # the traefik service definition
    traefik.yml.j2                # static config (entryPoints, providers)
    dynamic/middlewares.yml.j2    # authentik forward-auth + headers
    dynamic/services.yml.j2       # file provider — Tier-1 routes
    dynamic/origin-pull.yml.j2    # mTLS door option + catch-all (only when enabled)
  files/cloudflare-origin-pull-ca.crt   # Cloudflare AOP CA (public, vendored)
```

### Inspecting routing at runtime

```bash
# All routers (Tier-1 + Tier-2 combined)
curl -s http://127.0.0.1:8080/api/http/routers | jq '.[].name'

# A specific router's full config (rule, service, middlewares, status)
curl -s http://127.0.0.1:8080/api/http/routers/<slug>@docker | jq

# Live config from the file provider
curl -s http://127.0.0.1:8080/api/http/services | jq '.[] | select(.provider=="file")'
```

The dashboard at `http://127.0.0.1:8080` (insecure-mode binding only
to loopback) shows the same data graphically.

### Forcing a reload of file-provider config

`watch: true` is set in static config — Traefik picks up edits to
`{{ traefik_dynamic_dir }}/*.yml` within seconds. No restart needed.
Edits to the COMPOSE labels of a Tier-2 app DO require a re-up of the
container.

### Falling back to host nginx

```yaml
# config.yml
install_traefik: false
install_nginx: true
```

Re-runs the playbook in the host-nginx-only path. Tier-2 apps_runner
is incompatible with host nginx (the Docker provider has nothing to
scrape) — they'll render the compose override but the Traefik labels
won't be picked up. Use Tier-2 only when Traefik is the active edge.

---

## Cloudflare origin pulls (mTLS door)

**Problem (measured 2026-09-03, dtt `sec-origin-answers-anyone`).** Traefik
answers 80/443 from any source. Every public DNS record is Cloudflare-proxied,
but scanners hit the WAN IP directly: 4669 no-router requests in 24 h. An
`ipAllowList` of Cloudflare ranges cannot help. Docker Desktop NATs every
published-port source to `192.168.65.1`, so Traefik never sees a Cloudflare IP.
A client certificate arrives inside the TLS handshake, so mTLS is the one check
the NAT cannot erase.

**Design: a second door, not a lock on the first.** If `:443` required mTLS,
LAN access to the same hostnames would break, and so would the smoke's loopback
retry (`tools/nos-smoke.py` `_probe_via_loopback` hits `127.0.0.1:443`), the
e2e suite and every host-side tool. So `:443` stays exactly as it is, and
`traefik_origin_pull_enabled: true` adds the following:

| What | Where |
| --- | --- |
| entrypoint `websecure-origin` on container `:8443`, published as `traefik_origin_pull_port` (default `8443`) | `traefik.yml.j2`, `compose.yml.j2` |
| the same hardening as `websecure` (`aliasHeadersStrategy`, `encodedCharacters`, `forwardedHeaders`), but no `modern@file` model | `traefik.yml.j2` (a copy of the block; the gate fails if it drifts from websecure) |
| an `<name>-origin` twin of **every** websecure router: same rule, service, middlewares and priority, with `tls.options: origin-pull@file` | `services.yml.j2` (manifest, machine lanes, extra, dashboard), `pazny.keap` ext/ingest, `pazny.smtp_stalwart` labels, Tier-2 labels in `nos_apps_render.py` |
| TLS option `origin-pull`: `RequireAndVerifyClientCert` against Cloudflare's CA, `sniStrict: true` | `dynamic/origin-pull.yml.j2` → `conf.d/origin-pull.yml` |
| TCP `HostSNI(*)` catch-all on the door with the same option, aimed at nothing (`127.0.0.1:9`) | same file |
| `core.strictTLSOptions: true` | `traefik.yml.j2` |
| Cloudflare's public CA, copied to `/etc/traefik/` (the existing `:ro` config mount) | `roles/pazny.traefik/files/cloudflare-origin-pull-ca.crt` |

Why each of the less obvious pieces is there (verified against the Traefik
v3.7.13 source):

- **The catch-all.** When the SNI matches no router, Traefik uses the global
  `default` TLS option, which asks for no client certificate, and returns a 404.
  This is the IP-literal scanner case. On the TLS-fallback path, Traefik checks
  a TCP `HostSNI(*)` route after the HTTPS hosts (`router.go` `ServeTCP`). With
  `sniStrict`, that route refuses before any certificate is sent.
- **Twins, not a shared router.** One router listed on both entrypoints carries
  one `tls` block, so the door could not have its own option. Traefik also
  applies an entrypoint's `http.tls` model only to routers whose `tls` is nil
  (`aggregator.go` `applyModel`), and every router here has `tls: {}`.
- **`strictTLSOptions`.** If two routers serve the same host on one entrypoint
  with different TLS options, Traefik by default falls back to `default`, which
  means no client certificate is required (fail-open). With strict, the
  conflicting router is disabled instead.
- **The local-TLD refusal.** A `.local`/`.lan`/`.test` estate has no Cloudflare
  in front of it, so the converge asserts and stops.

Gate: `tests/anatomy/test_origin_pull_is_a_second_door.py`. It checks that the
off render is byte-identical, that on only adds, that every router has a twin
that carries the option, that the door is published and hardened, that the CA
is pinned, and that a local TLD is refused.

### Runbook (three steps, then verify)

Steps (i) and (ii) are harmless in either order, because the door carries no
traffic until (iii). Step (iii) must come last.

1. **Cloudflare: enable Authenticated Origin Pulls.** Dashboard → your zone →
   **SSL/TLS → Origin Server → Authenticated Origin Pulls** tab → **Global** →
   toggle **On**. The API equivalent is the zone setting `tls_client_auth` =
   `on`. Prerequisite: **SSL/TLS → Overview** must be set to **Full (strict)**,
   since AOP needs Full or higher. Cloudflare now presents its client
   certificate, and `:443` ignores it.
2. **Estate: open the door.** Set `traefik_origin_pull_enabled: true` in
   `config.yml` (and `traefik_origin_pull_port` if 8443 is taken), then run
   `ansible-playbook main.yml --tags traefik,keap,stalwart,apps` (or a full
   converge). `traefik` opens the door and recreates Traefik with the new port.
   The other tags render the twins that live outside the traefik role: the KEAP
   `/ext` and `/ingest` routers, the Stalwart admin labels and the Tier-2
   labels. Without them, those paths either fall to the gated router on the
   door or return 404 there.
3. **Router: move the forward.** Change the port-forward from `WAN:443 →
   <mac>:443` to `WAN:443 → <mac>:8443`. Keep the external port at 443:
   Cloudflare still connects to 443, and only the inside target changes.

**Verify.** Run these from **outside** the LAN (for example a phone hotspot),
because hairpin NAT on many routers skews the result:

| Probe | Expected |
| --- | --- |
| `curl -vk https://<WAN-IP>/` (an IP literal sends no SNI) | handshake fails with `unrecognized name` and no certificate is sent; was 404 before |
| `curl -vk --resolve <host>:443:<WAN-IP> https://<host>/` | handshake fails with `certificate required` (TLS 1.3 alert); no HTTP status |
| `curl -sI https://<host>/` (through Cloudflare) | same as before: 200 or 302 to `auth.<tld>` |
| on the Mac: `curl -skI --resolve <host>:443:127.0.0.1 https://<host>/` | unchanged, because LAN and the smoke still use `:443` |
| on the Mac: `curl -vk --resolve <host>:8443:127.0.0.1 https://<host>:8443/` | refused, which proves the door before step 3 |

**Rollback:** move the forward back to `:443`, which takes effect at once,
then set the flag to `false` and converge.

**Anything that resolves a public name straight to the WAN IP** (a
split-horizon DNS entry, a hairpin) now lands on the door and fails. Point LAN
clients at the Mac's LAN IP on `:443` instead.

### Port 80

Nothing new is added on the public side. Port 80 is a redirect-to-https only.
mTLS cannot exist on plain HTTP, and ACME uses DNS-01, which needs no inbound
port. **Recommendation: stop forwarding WAN:80.** First turn on **SSL/TLS →
Edge Certificates → Always Use HTTPS** in Cloudflare. Without it, in Full mode
Cloudflare fetches `http://` visitor requests from the origin on port 80. After
that, nothing legitimate reaches origin:80, and the forward only serves
scanners. The router checklist then becomes: remote management OFF, UPnP OFF,
and exactly one forward (`WAN:443 → <mac>:8443`).

### Ceilings (named, not fixed)

- **The shared certificate proves "some Cloudflare zone", not this zone.**
  Global AOP uses one Cloudflare certificate for all customers. Someone with
  their own Cloudflare zone pointed at this WAN IP also passes mTLS. They still
  need an SNI inside this zone's certificate, which `sniStrict` requires, so an
  SNI override on their side. What they would gain is a path that skips this
  zone's Cloudflare-side controls (WAF, rate limits, Access). The routes and
  auth they would reach are the same ones any visitor reaches through
  Cloudflare. **Zone-level AOP** (an operator CA, plus a leaf uploaded to
  Cloudflare) closes that gap. It is a follow-up, not built here. It becomes
  worth it once a Cloudflare-side control is load-bearing. The cost is a
  private key to custody and a leaf to rotate before it expires.
- **A scanner that already knows a hostname still sees the certificate.**
  In TLS the server's certificate precedes the request for the client's, so
  `sniStrict` hides it only for a missing or unknown SNI.
- **Plain HTTP sent to the door gets a Traefik 404.** No router there accepts
  plain HTTP.
- **`modern@file` on `websecure` is inert today.** Routers carry `tls: {}`, and
  the entrypoint model applies only to a nil `tls`, so `:443` negotiates with
  `default` (TLS 1.2+). This is a separate follow-up, because fixing it changes
  `:443`.
- **CA expiry:** Cloudflare's AOP CA expires on `2029-11-01`. The gate's
  `openssl -checkend 0` turns red once it has expired.

---

## Migration from host nginx (historical)

The host-nginx-only era ended in C1 (2026-04-29). The C1 commit
removes:

- `roles/pazny.nginx_container/` (the never-deployed bridge role)
- `docs/nginx-container-migration.md` (the D2 operator guide)
- `migrations/2026-05-15-nginx-host-to-container.yml` (the unfired migration)

Existing instances on host nginx need a single blank run to flip:

```bash
nos --remove=data --confirm
```

`tasks/nginx.yml` is gated behind `install_nginx | default(false)` —
the host nginx pieces stop being installed unless you explicitly opt
in. The playbook regenerates everything from scratch with Traefik as
the edge.

If you have bespoke vhost templates in `templates/nginx/sites-extra/`
or `nginx_sites_extra` and don't want to lose them, set
`install_nginx: true` AND `install_traefik: true` — they coexist on
different ports (Traefik on 80/443, nginx on whatever you bind it to)
but you'll be responsible for upstream wiring yourself. Most operators
don't need this.
