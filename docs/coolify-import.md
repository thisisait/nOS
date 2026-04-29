# Coolify hybrid importer

A pragmatic shortcut for onboarding self-hosted apps from
[coollabsio/coolify](https://github.com/coollabsio/coolify) (Apache-2.0)
into nOS Tier-2. The Coolify project maintains ~280 curated compose
templates under `templates/compose/` — instead of forking that catalog
or rewriting each template by hand, we pull them on demand and rewrite
their token syntax + scaffold the `gdpr:` block the nOS parser demands.

The importer **never deploys anything**. It produces a `*.yml.draft`
that the parser explicitly refuses (the GDPR block is full of `TODO`
sentinels) until the operator fills it in and renames the file to drop
the `.draft` suffix.

---

## When to use it

- You found a Coolify template for the app you want.
- You're OK answering ~6 GDPR Article 30 questions about how the app
  processes personal data — _that_ is the price of admission for
  Tier-2, not running the importer.
- You're NOT trying to onboard a Tier-1-grade service (Authentik,
  Postgres, Grafana, Wing — these get a full `pazny.<name>` role with
  RBAC tiers, OIDC blueprint entries, migration recipes etc.).

If you want the app for ad-hoc personal use on a single tenant box,
this is the fastest path: minutes, not hours.

---

## Usage

```bash
# From a raw Coolify template URL
python3 tools/import-coolify-template.py \
    --url https://raw.githubusercontent.com/coollabsio/coolify/main/templates/compose/uptime-kuma.yaml \
    --name kuma2

# Or from a local file (e.g. when iterating on a fork)
python3 tools/import-coolify-template.py \
    --file ~/forks/coolify/templates/compose/uptime-kuma.yaml \
    --name kuma2

# Override output dir (default is ./apps)
python3 tools/import-coolify-template.py --url <…> --name foo --out apps/draft

# --force is needed to re-import over an existing .yml.draft
```

The importer prints a numbered next-steps list. The short version:

1. Open `apps/<name>.yml.draft`.
2. Replace every `TODO` in the `gdpr:` block — at minimum:
   - `purpose:` (one or two plain-language sentences)
   - `legal_basis:` (one of `consent`, `contract`, `legal_obligation`,
     `vital_interests`, `public_task`, `legitimate_interests`)
   - `data_categories:` (specific items like `email`, `ip_address`,
     `photos`, `health_data`, …)
3. If the upstream template referenced operator-supplied env vars
   (e.g. `${SMTP_HOST}`, `${RESEND_API_KEY}`), the preamble lists them
   — set values via the manifest's compose `environment:` block, a
   `.env` file, or shell exports before the next playbook run.
4. Smoke-parse:
   ```bash
   python3 -m module_utils.nos_app_parser apps/<name>.yml.draft
   ```
   Clean exit (rc=0) means the parser is satisfied.
5. Rename `apps/<name>.yml.draft` → `apps/<name>.yml`.
6. Run the playbook — `pazny.apps_runner` discovers the manifest,
   resolves magic tokens, registers Authentik / Wing / Bone / Kuma /
   Portainer / GDPR entries automatically.

---

## Token mapping (Coolify → nOS)

The importer rewrites these token shapes in place. Mapping is
deterministic and idempotent (re-running on a partially-edited file
won't double-rewrite).

| Coolify (upstream)               | nOS (`module_utils/nos_app_parser`) |
| -------------------------------- | ---------------------------------- |
| `${SERVICE_URL_<NAME>_<PORT>}`   | `https://$SERVICE_FQDN_<APP>` (port stripped — Traefik knows it) |
| `${SERVICE_URL_<NAME>}`          | `https://$SERVICE_FQDN_<APP>`      |
| `${SERVICE_FQDN_<NAME>}`         | `$SERVICE_FQDN_<APP>`              |
| `${SERVICE_USER_<KEY>}`          | `$SERVICE_USER_<KEY>` (lowercase `<app>_<key>`) |
| `${SERVICE_PASSWORD_<KEY>}`      | `$SERVICE_PASSWORD_<KEY>` (32-char random; same `<KEY>` = same value) |
| `${SERVICE_BASE64_<KEY>}`        | `$SERVICE_BASE64_64_<KEY>` (default 64 bytes) |
| `${SERVICE_BASE64_64_<KEY>}`     | `$SERVICE_BASE64_64_<KEY>` (preserved) |
| `${SERVICE_BASE64_32_<KEY>}`     | `$SERVICE_BASE64_32_<KEY>` (preserved) |
| `${VAR:-default}`                | `$VAR` + TODO entry in preamble (default value preserved as a comment) |
| `${VAR}` (no SERVICE_ prefix)    | `$VAR` + TODO entry flagged REQUIRED |

The preamble lists every operator-TODO env var so you know what to
fill in before deploying. Tokens that already collide with our suffix
grouping (`SERVICE_PASSWORD_DB` repeated across services in the same
manifest = same generated value) keep that semantic.

---

## What the importer does NOT do

- **It does not validate the GDPR block.** That's deliberate — the
  parser does it on the next playbook run. We want operators to read
  the comments and think about the answers, not autocomplete them.
- **It does not pick a port.** The port comes from Coolify's
  `# port:` header. If the upstream template gets a port wrong, edit
  `meta.ports` after import.
- **It does not handle non-trivial entrypoint scripts.** Some Coolify
  templates inline 100-line bash entrypoints (Documenso is an example).
  These are imported verbatim — review them, they often hardcode paths
  or assume Coolify-specific runtime conditions.
- **It does not pin image digests.** Same as our roles — operators who
  want SHA256 pinning add it manually after import. Tag-based pinning
  (Coolify's default) is preserved.
- **It does not deal with Coolify-specific labels** (`coolify.managed`,
  `coolify.healthcheck`, …). These pass through harmlessly — the apps
  stack ignores them.

---

## Catalog discovery

Coolify's templates live at:
<https://github.com/coollabsio/coolify/tree/main/templates/compose>

Every directory entry is a single YAML file with the same conventions
(see e.g. [`uptime-kuma.yaml`](https://raw.githubusercontent.com/coollabsio/coolify/main/templates/compose/uptime-kuma.yaml)
or [`documenso.yaml`](https://raw.githubusercontent.com/coollabsio/coolify/main/templates/compose/documenso.yaml)).
The raw URL pattern:

```
https://raw.githubusercontent.com/coollabsio/coolify/main/templates/compose/<name>.yaml
```

Pasting that into `--url` is the standard workflow.

---

## Why we're not contributing the GDPR block upstream (yet)

We've considered an upstream PR proposing `# gdpr_*` meta-keys to the
Coolify header convention. See `docs/coolify-rfc-gdpr-metadata.md`.
The TL;DR is that a header-only metadata addition (no behavioural
change for non-EU users) is the lowest-friction path. Operators who
care about EU compliance get a baseline they can edit; everyone else
ignores the keys.

If you've successfully onboarded an app and want to share its GDPR
block back to the community, drop it in `state/gdpr-library/<name>.yml`
on this repo (path tbd) — D8+ will surface those as defaults the
importer can pre-fill.
