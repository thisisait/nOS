# Tier-2 app onboarding

The fast path for adding a self-hosted app to nOS. **Tier-2** is the
manifest-driven layer — drop a YAML file at `apps/<name>.yml`, run the
playbook, get a fully-routed Traefik vhost, Authentik gate, GDPR
register entry, Wing systems row, Bone deploy event, Uptime Kuma
probe, and a smoke catalog row. Total operator effort: ~10 minutes
of typing per app.

> **When NOT to use Tier-2:** if the service deserves dedicated RBAC
> tiers, custom OIDC blueprint policies, migration recipes, or any
> kind of cross-stack integration, give it a `pazny.<name>` role
> instead. Tier-2 is for the long-tail self-hosted catalog (the 200+
> apps you'd otherwise pick from Coolify / Cloudron / Yacht).

---

## TL;DR

```bash
# 1. Copy the template and edit
cp apps/_template.yml apps/myapp.yml
$EDITOR apps/myapp.yml

# 2. Smoke-parse (catches schema / GDPR errors before the playbook does)
python3 -m module_utils.nos_app_parser apps/myapp.yml

# 3. Run the playbook (apps_runner discovers the new manifest automatically)
ansible-playbook main.yml -K
```

The Tier-2 entrypoint is `tasks/stacks/apps-up.yml`, wired into
`main.yml` after the Tier-1 stacks come up. Empty `apps/` (only
`_template.yml`) is a clean no-op.

---

## What goes in a manifest

Three mandatory blocks. Schema enforced by
`state/schema/app.schema.json` + `module_utils/nos_app_parser.py`.

### 1. `meta:` — service identity

```yaml
meta:
  name: "myapp"           # slug ^[a-z][a-z0-9-]*$ — must match filename
  version: "1.2.3"        # upstream image tag pinned for THIS manifest
  summary: "What it does in one line."
  homepage: "https://upstream.example/"
  category: "productivity"
  ports: [8080]           # primary HTTP port (first = primary)
  tags: ["self-hosted", "demo"]
```

### 2. `gdpr:` — Article 30 register entry (MANDATORY)

```yaml
gdpr:
  purpose: |
    Plain-language explanation of why we process data.
  legal_basis: "legitimate_interests"  # see enum below
  data_categories: ["email", "ip_address"]
  data_subjects: ["end_users"]
  retention_days: 365
  processors: []
  transfers_outside_eu: false
```

**`legal_basis` enum** (Article 6(1)):

| Value                    | Use when                                                         |
| ------------------------ | ---------------------------------------------------------------- |
| `consent`                | Opt-in, withdrawable. **Triggers SSO gate** — auth must be wired. |
| `contract`               | Necessary to deliver the service to the user.                    |
| `legal_obligation`       | Required by law (accounting, KYC, etc.).                         |
| `vital_interests`        | Life-or-death. Rare.                                             |
| `public_task`            | Public-interest task. Rare.                                      |
| `legitimate_interests`   | Balancing test — document the interest in `purpose`.             |

**`data_subjects` drives the TLS gate.** If you list `end_users`,
`patients`, `minors`, or `employees`, the runner enforces TLS
termination (Traefik `tls=true` label is required). Manifests that
list only `operators` or `anonymous` get a softer gate.

**`transfers_outside_eu: false`** drives the EU-residency gate.
Every compose image must come from a registry in
`DEFAULT_EU_REGISTRIES` (`docker.io`, `ghcr.io`, `registry.gitlab.com`,
`lscr.io`, `quay.io`, `registry.k8s.io`). Setting `true` bypasses
this — the operator acknowledges the transfer.

### 3. `compose:` — verbatim docker-compose

```yaml
compose:
  services:
    myapp:
      image: "ghcr.io/example/myapp:1.2.3"
      ports:
        - "8080:8080"
      environment:
        - "DB_USER=$SERVICE_USER_DB"
        - "DB_PASSWORD=$SERVICE_PASSWORD_DB"
        - "PUBLIC_URL=https://$SERVICE_FQDN_MYAPP/"
      volumes:
        - myapp_data:/data
  volumes:
    myapp_data:
```

The whole compose dict is YAML-parsed, magic-token-resolved, then
emitted unchanged into `{{ stacks_dir }}/apps/overrides/<name>.yml`.
Whatever Docker Compose accepts, the runner accepts.

#### Magic tokens

The runner expands these BEFORE compose-up. Stable across runs (same
suffix → same value):

| Token                              | Expands to                                          |
| ---------------------------------- | --------------------------------------------------- |
| `$SERVICE_FQDN_<APP>`              | `<name>.apps.<instance_tld>` (default `apps.dev.local`) |
| `$SERVICE_USER_<SUFFIX>`           | `<name>_<suffix>` (lowercase)                       |
| `$SERVICE_PASSWORD_<SUFFIX>`       | 32-char random; same SUFFIX = same value            |
| `$SERVICE_BASE64_32_<NAME>`        | 32-byte base64                                      |
| `$SERVICE_BASE64_64_<NAME>`        | 64-byte base64                                      |

Generated secrets persist to `credentials.yml` under the
`app_secrets:` key (idempotent — re-running with the same prefix
preserves them so encrypted DBs don't break across runs).

### 4. `nginx:` — routing hints (optional)

```yaml
nginx:
  auth: "proxy"           # none | proxy | oidc  (default: proxy)
  oidc_callback: "/auth/callback"  # only used when auth=oidc
```

`proxy` (default) wires Authentik forward-auth via Traefik middleware
— users hit the app FQDN, get bounced to `auth.<tld>`, return signed
in. `oidc` skips the gate and instead pushes the app's OAuth client
config into Authentik (`authentik_oidc_apps` is extended at run
time).

---

## What the runner does

1. **Discover** — every `apps/*.yml` (skips `_*`-prefixed files,
   `.draft` suffix, `.draft.yml`, `.draft.yaml`).
2. **Parse + validate** — `nos_app_parser.parse_app_file()`.
   Schema-fails are collected and printed at the end, not one-by-one.
3. **Gates** — TLS / SSO / EU-residency. Hard fail unless
   `apps_force=true` (NOT recommended — gates exist for compliance).
4. **Token resolve** — magic tokens, with `app_secrets` as the seed
   (so existing PASSWORD / BASE64 values survive blank runs).
5. **Render** — single merged compose override at
   `{{ stacks_dir }}/apps/overrides/auto.yml`.
6. **Compose-up** — `docker compose -p apps up --wait --wait-timeout 120`
   with the override fragment + per-app overrides.
7. **Post-hooks** — service-registry append → Wing ingest → Authentik
   blueprint reconverge → Bone HMAC `app.deployed` events → Portainer
   apps endpoint reg → Kuma monitor extension → GDPR `upsertProcessing`
   → smoke-catalog runtime extension. See
   `roles/pazny.apps_runner/tasks/post.yml` for the full surface.

---

## Operator workflows

### Add a new app from scratch

```bash
cp apps/_template.yml apps/myapp.yml
# Edit meta + gdpr + compose blocks
python3 -m module_utils.nos_app_parser apps/myapp.yml
ansible-playbook main.yml -K
```

### Onboard from a Coolify template

Saves typing for apps with a known-good upstream compose. See
[`docs/coolify-import.md`](coolify-import.md) for the full guide.

```bash
python3 tools/import-coolify-template.py \
    --url https://raw.githubusercontent.com/coollabsio/coolify/main/templates/compose/<name>.yaml \
    --name myapp
# Edit apps/myapp.yml.draft (fill TODO sentinels in gdpr block)
mv apps/myapp.yml.draft apps/myapp.yml
ansible-playbook main.yml -K
```

### Stage a manifest without deploying it

Suffix the file with `.draft` (or rename to `.draft.yml` / prefix with
`_`). The runner skips it — useful for dry-running the parser, or
for keeping a heavy multi-container app off the next blank run while
you verify lighter pilots. Example: `apps/plane.yml.draft` ships in
the repo as a 13-container stress-test pilot — operator un-drafts
once they're ready.

### Disable Tier-2 entirely

```yaml
# config.yml
apps_runner_enabled: false
```

The render task skips, the apps stack is not deployed, no post-hooks
fire. Existing Tier-2 containers stay up (Docker doesn't tear them
down on a skipped task) — `docker compose -p apps down` cleans them
manually.

---

## Troubleshooting

### "FAIL: App 'myapp' failed validation"

The parser collected one or more issues. Common ones:

- **`meta.name 'myapp' must match [a-z][a-z0-9-]*`** — your slug
  starts with a digit or contains an underscore. Rename the file
  AND the `meta.name` value (they must match).
- **`gdpr.legal_basis 'TODO' not in [...]`** — you imported from
  Coolify and forgot to fill in the GDPR block.
- **`gate_eu_residency: <svc> -> <image> (registry <r>, not in allow-list)`**
  — the upstream image lives in a non-EU registry
  (gcr.io / public.ecr.aws / mcr.microsoft.com). Either set
  `transfers_outside_eu: true` (acknowledge the transfer) or push the
  image to an EU mirror and update the manifest.
- **`gate_sso_required: legal_basis=consent demands Authentik wiring`**
  — your manifest claims consent but `nginx.auth: none`. Set
  `auth: proxy` or change the legal basis if consent isn't actually
  what you mean.

### Apps stack containers come up but the FQDN 404s

- Check Traefik picked up the labels:
  `curl -s http://127.0.0.1:8080/api/http/routers | jq '.[].name'`
  — your app's slug should appear.
- Check the Authentik provider was created if `auth: proxy`:
  the Authentik admin UI lists it under Providers / Applications.
  If missing, `apps_runner_reconverge_blueprints: true` (default) was
  probably skipped — re-run with `--tags apps,authentik`.
- Check Docker DNS — apps in the apps stack reach Tier-1 services
  (Postgres, Redis) over their compose-project hostnames or via
  `nos-host:host-gateway` (Docker Desktop quirk).

### A secret got regenerated and a Postgres-backed app can't decrypt its DB

Don't blank=true unless you mean it. The runner persists generated
secrets to `credentials.yml`'s `app_secrets:` block — preserve that
file across reinstalls. If the file was lost, drop the volume too
(`docker volume rm apps_<app>_db`) — there's no recovery without the
secret.

### Smoke probe fails for a Tier-2 app

`tools/nos-smoke.py` reads `state/smoke-catalog.runtime.yml` (auto-
written by the runner) on top of `state/smoke-catalog.yml`. Each
Tier-2 entry expects 200 / 301 / 302 / 308 / 401. 401 covers the
Authentik proxy gate before the user logs in. Anything else (e.g.
404, 502, 503) means the container is up but something is wrong with
its routing or healthcheck — check logs with `docker compose -p apps
logs <service>`.

---

## Reference

- Schema: `state/schema/app.schema.json`
- Parser: `module_utils/nos_app_parser.py`
- Runner role: `roles/pazny.apps_runner/`
- Render module: `library/nos_apps_render.py`
- Orchestrator: `tasks/stacks/apps-up.yml`
- Pilot manifests: `apps/twofauth.yml`, `apps/roundcube.yml`,
  `apps/documenso.yml`, `apps/plane.yml.draft` (rename to enable)
