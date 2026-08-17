# Apex Site

> The public anatomy page at the **root domain** — the estate's front door for
> anonymous visitors. Unlike WordPress (accounts, comments, a MariaDB schema),
> this is static files with **no application behind them at all**: nginx serving
> a byte-deterministic build of the operator-signed apex ruling. Stateless —
> the web root is derived content, rebuilt from the repo on every converge.

## Quick Reference

| | |
|---|---|
| **URL** | `https://{tenant_domain}` — the ROOT domain itself, not a subdomain (default `https://dev.local`; `host_alias` deliberately does not apply) |
| **Port** | `8061` (`apex_port`; loopback publish `127.0.0.1:8061` → container `80`) |
| **Stack** | `iiab` |
| **Node id** | `nos.iiab.apex` |
| **Toggle** | `install_apex: false` — default OFF; flipping it on before the ruling is signed produces a loud converge refusal, not a page |
| **Image** | `nginx:1.30.4-alpine@sha256:97d490c1…` (`apex_version` — tag AND multi-arch index digest) |
| **Compose** | `~/stacks/iiab/docker-compose.yml` + `~/stacks/iiab/overrides/apex.yml` (role; no plugin compose extension) |
| **Container** | `iiab-apex-1` |
| **Data** | None — stateless. The web root `~/stacks/iiab/apex-www` → `/usr/share/nginx/html:ro` is DERIVED content (`build.py --require-signed --out`), rebuilt at converge; a blank may wipe it freely. |
| **Config** | `~/stacks/iiab/apex-nginx.conf` (rendered by the role) → `/etc/nginx/conf.d/default.conf:ro` — `server_tokens off` |
| **Memory limit** | `256m` (`docker_mem_limit_light`) |
| **Networks** | `gated_net` ONLY (SEC-02 posture, calibre-web precedent) — shares a network with nothing but Traefik |

`apex_domain`, `apex_port`, `apex_version` pin in `default.config.yml`. The container runs
`read_only: true` with tmpfs scratch at `/var/cache/nginx` and `/var/run`; every bind mount
is `:ro`.

**External-storage override:** none — `tasks/stacks/external-paths.yml` names no apex var,
and there is nothing to relocate.

## The signature gate

The content pipeline is `state/anatomy-graph.json` → `files/anatomy/apex/ruling.yml`
(the operator-signable allow-list: 63 `speaks:` phrases in 13 organs, everything else
withheld and leak-checked) → `files/anatomy/apex/projection.py` → static pages.
While the ruling says `status: PROPOSED`, `roles/pazny.apex` **fails the converge**
(an Ansible assert AND `build.py --require-signed`, which exits 4) — it does not
skip, and it renders nothing a later `docker compose up` could serve. Pinned by
`tests/anatomy/test_apex_serving_is_signature_gated.py`.

## Authentication

- **Admin user:** N/A — no accounts, no sessions, no cookies, no forms.
- **SSO:** `none`, public by design — the only routed service whose purpose is to be
  read by strangers. `traefik_auth_modes.apex: none` with the REM-144 justification
  FIELD in `roles/pazny.traefik/vars/main.yml` (`traefik_auth_none_justification.apex`).
  There is no `authentik:` block in `files/anatomy/plugins/apex-base/plugin.yml`,
  deliberately.
- **Autologin:** N/A — nothing to log into.

## API Access

None. The service exposes static files (`index.html`, `public-anatomy.json`,
`assets/`) and nothing else — no API, no query surface, no write path. The
machine-readable `public-anatomy.json` is the same signed projection the page
renders, published as data.

## Health Check

- **Container healthcheck:** `wget -q -O /dev/null http://127.0.0.1/` (busybox wget
  from the alpine base; interval 30s, timeout 5s, retries 3, start period 10s).
- **Edge:** anonymous `GET https://{tenant_domain}/` answers `200` — the smoke
  runner auto-derives this probe from the manifest entry once `install_apex` is on.

## Dependencies

- None at runtime — apex serves prebuilt files and can outlive every other
  container (`depends_on: []` in `apex-base/plugin.yml` is the surveyed positive
  statement, not an omission). Build-time inputs (the anatomy artifact + the
  signed ruling) are repo substrate, not running services.
