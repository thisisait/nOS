# Break-glass runbook — SSO autologin lockout recovery

> **Authoritative spec:** [`docs/sso-autologin-plan.md`](sso-autologin-plan.md)
> §"Bezpečnost: break-glass + lockout". This runbook is the operator-facing
> procedure derived from that plan.
>
> **Pinned by:** `tests/anatomy/test_break_glass_runbook_present.py` (file
> exists + has the CLI recovery-key, restart, and per-service fallback
> truth-table sections).

## What this is for

When `sso_autologin` is enabled (it is **OFF by default** — `sso_autologin: false`),
native_oidc services that support force-OIDC will auto-redirect to Authentik
or hide their local login form. If **Authentik itself is down**, or a misconfig
locks the operator out, this runbook is the escape hatch.

**Design invariant (plan §"Bezpečnost"):** *SSO-down never permanently locks
admins out.* The break-glass model stands on three load-bearing layers — they
are complete **without** any optional Wing portal:

1. **Per-service break-glass** — a documented escape per service. Either a
   live URL param (form is still reachable) **or** an env-unset + container
   recreate (form is env-hidden, no runtime UI escape). See the truth-table.
2. **Per-service local-login fallback toggle** — `enable_<svc>_local_login: true`
   renders an `ALLOW_LOCAL_LOGIN`-style env into the compose-extension (where a
   service supports it). Default `false` (pure-SSO). See "Local-login fallback".
3. **Authentik recovery key** — CLI-provisioned offline escape (NOT a blueprint
   seed). See "CLI recovery-key usage".

A fourth layer — Wing `/api/unlock` admin recovery portal — is an **optional
greenfield add-on, NOT load-bearing** (it does not exist in the repo today; see
plan §"Bezpečnost" point 4). Do not rely on it; layers 1–3 are sufficient.

---

## Authentik down / health check

Before reaching for recovery, confirm whether Authentik is actually down vs. a
single service misconfig.

```bash
# Is the Authentik server container up + healthy?
docker ps --filter name=authentik --format '{{.Names}}\t{{.Status}}'

# Expected live names (A19 naming: <stack>-<service>-1):
#   infra-authentik-server-1   Up (healthy)
#   infra-authentik-worker-1   Up (healthy)

# Health endpoint (server):
docker exec infra-authentik-server-1 \
  curl -fsS http://localhost:9000/-/health/live/ && echo "  → live"
docker exec infra-authentik-server-1 \
  curl -fsS http://localhost:9000/-/health/ready/ && echo "  → ready"

# Recent server logs (look for DB / Redis connection errors):
docker logs --tail 80 infra-authentik-server-1
```

If `ready` fails but the container is up, Authentik usually can't reach
PostgreSQL or Redis — check `infra-postgresql-1` / `infra-redis-1` first.

If only *one* service redirects into a loop while Authentik is healthy, this is
a per-service misconfig — skip to the per-service truth-table below, you do not
need a recovery key.

---

## Container restart (first, least-destructive lever)

A restart fixes most transient Authentik wedges (stuck worker, post-upgrade
schema warm-up, Redis reconnect).

```bash
# Restart just the Authentik server + worker (data is in the DB, not the
# container — restart is safe and non-destructive):
docker restart infra-authentik-server-1 infra-authentik-worker-1

# Wait for ready, then re-test login:
docker exec infra-authentik-server-1 \
  curl -fsS http://localhost:9000/-/health/ready/ && echo "  → ready"
```

If a dependency is the culprit, restart it too (non-destructive — these are
stateful via volumes, not container-local):

```bash
docker restart infra-postgresql-1 infra-redis-1
docker restart infra-authentik-server-1 infra-authentik-worker-1
```

> Do **not** `docker compose down -v` or wipe the Authentik volume — that
> destroys the IdP database and is the nuke-and-reroll last resort, not a
> restart.

---

## CLI recovery-key usage (offline escape into Authentik)

**Doctrine (plan §"Bezpečnost" point 3):** the Authentik recovery key is an
operator **manual CLI intervention**, NOT nOS-config persistence and NOT a
blueprint seed. The `authentik_core.recoverytoken` model **does not exist** in
the Authentik blueprint schema — attempting to blueprint-provision it is a
critical lockout risk. Recovery tokens are minted **only** via the management
command.

When the Authentik UI is reachable but you have no working admin session (e.g.
the only admin's password is unknown and SSO is the only path), mint a
one-time recovery URL for an existing admin user:

```bash
# A19 live container name. Use `ak create_recovery_key` inside the server.
docker exec infra-authentik-server-1 ak create_recovery_key <admin>

# Time-boxed validity (optional first arg = days the link stays valid):
docker exec infra-authentik-server-1 ak create_recovery_key 1 <admin>
```

The command prints a single-use recovery URL of the form
`https://auth.<tld>/recovery/use-token/<token>/`. Open it in a browser; it
logs you straight into Authentik as `<admin>` so you can reset the password,
fix the broken flow/provider, or disable the offending autologin binding.

> The plan also documents the equivalent compose form
> `docker compose run --rm server create_recovery_key <username>` — use whichever
> matches your shell. The `docker exec ... ak create_recovery_key` form above
> targets the already-running A19 container and is the canonical nOS form.

**`<admin>` must be an existing Authentik superuser.** If no admin account
exists at all, create one first:

```bash
docker exec -it infra-authentik-server-1 ak create_admin_group <username>   # ensure admin group
docker exec -it infra-authentik-server-1 ak shell                            # then create/promote a user
```

### The nOS-side recovery key (input to the CLI, not a seed)

Per the plan, nOS generates an `authentik_recovery_key` (random bytes) on the
first blank run and stores it in `~/.nos/secrets.yml` (the real persistent
secrets store, read idempotently across re-runs). This key is the **offline
input** you feed to the CLI recovery procedure when the Authentik UI/admin is
unreachable — it is **not** a blueprint seed and not provisioned into the
Authentik DB. Its stability across re-runs is pinned by
`tests/anatomy/test_recovery_key_persists_across_reruns.py`.

> **Note:** the secrets-generation task that writes `authentik_recovery_key`
> is provisioned by the Batch-4 secrets layer (outside this runbook's scope).
> If `~/.nos/secrets.yml` does not yet carry the key, the CLI procedure above
> still works against any existing admin username.

---

## Per-service break-glass truth-table

Not every escape leads to a live login form. Autologin **never hides or
disables a local form where one physically exists and is reachable** — it only
tries OIDC first. But several services hide the form via an env var, so their
"break-glass" is an **env-unset + container recreate**, not a runtime URL param.

This table is harvested from the live `authentik.autologin` blocks in
`files/anatomy/plugins/<svc>-base/plugin.yml` (`break_glass`,
`hides_local_form`, `supports`). It is the authoritative per-service escape.

| Service | tier | supports | hides local form | break-glass | escape kind | live form reachable? |
|---|---|---|---|---|---|---|
| grafana | 1 | yes | yes | `?disableAutoLogin=true` (→ `/login`) | **URL param** | yes (form returns if `GF_AUTH_DISABLE_LOGIN_FORM` not set) |
| portainer | 1 | yes | yes | `/#!/internal-auth` | **URL param** | yes if `HideInternalAuth` not set; else API revert (`PUT /api/settings`) |
| infisical | 1 | partial | no | `/login/admin` (org-admin bypass) | **URL param** | yes (button-only; org-admin path) |
| bookstack | 3 | yes | yes | `?prevent_auto_init=true` | **URL param** | yes |
| nextcloud | 3 | yes | no | `?direct=1` | **URL param** | yes |
| homeassistant | 3 | yes | yes | `?skip_oidc_redirect=true` | **URL param** | yes |
| gitlab | 2 | partial | yes | `?auto_sign_in=false` | **URL param** | yes ONLY if `disable_password_authentication_for_web` ≠ true; else use recovery |
| superset | 2 | partial | no | `OAUTH_SKIP_PROVIDER_SELECTION=False` | **env-unset + recreate** | form stays; flag controls provider-skip |
| outline | 3 | partial | no | set `OIDC_DISABLE_REDIRECT=true` + recreate | **env-set + recreate** | re-render to stop auto-redirect |
| wordpress | 4 | partial | no | `/wp-login.php` (direct) | **URL param** | yes |
| nodered | 2 | partial | no | local admin fallback user in `adminAuth.users` | **config fallback** | yes (local admin in settings.js) |
| **gitea** | 2 | yes | yes | re-enable `ENABLE_PASSWORD_SIGNIN_FORM` env + recreate | **env-unset + recreate** | **no at runtime** — form is env-hidden |
| **miniflux** | 3 | partial | yes | unset `DISABLE_LOCAL_AUTH` + recreate | **env-unset + recreate** | **no at runtime** — form is env-hidden |
| **vaultwarden** | 3 | **no** | no | `/admin` (admin token panel) | **URL param** | button-only build; `SSO_ONLY=false` + recreate to restore master-password |

> `supports: no` services (vaultwarden here, plus n8n / hedgedoc / open-webui /
> erpnext / jellyfin / freescout-without-module) are **never force-OIDC'd** —
> their `enabled` is gate-locked to false (`test_autologin_no_means_no`). Their
> local login is always present, so they need no env-unset escape — they are
> listed for completeness where they carry an `autologin` block at all.

### Services WITHOUT a runtime UI escape (env-unset + recreate)

For **gitea**, **miniflux**, and (when locked to SSO_ONLY) **vaultwarden**, the
local form is **env-hidden** — there is no live URL param that brings it back.
Break-glass for these is a re-render **without** the force-OIDC env, followed by
a container recreate:

```bash
# 1. Turn autologin off (globally, or per-service) — re-render WITHOUT force-OIDC.
#    Either flip sso_autologin in your config.yml, or set the per-service var:
#      sso_autologin: false          # global
#      sso_autologin_gitea: false    # per-service (precedence: svc > tier > global)
#
# 2. Re-render the override + recreate just that container (the --tags <svc>
#    compose-up auto-fire renders the override AND recreates in one shot, A17):
ansible-playbook main.yml --tags gitea -e sso_autologin=false
#   (miniflux: --tags miniflux ; vaultwarden: --tags vaultwarden)
#
# 3. The compose-extension re-renders without GITEA__SERVICE__ENABLE_PASSWORD_SIGNIN_FORM=false
#    / DISABLE_LOCAL_AUTH=1 / SSO_ONLY=true, the container recreates, and the
#    local form is reachable again.
```

This is **full reversibility** (plan §"Feature flag + rollout"): OFF→ON and
ON→OFF are both just a re-run; there is no persistent autologin state.

---

## Local-login fallback (`ALLOW_LOCAL_LOGIN` pattern)

**Layer 2** of the break-glass model. For a service that physically supports a
local-login bypass env, the plan's contract carries a `local_login_fallback`
field and an `enable_<svc>_local_login` operator toggle (plan §"Bezpečnost"
point 2 + §contract lines 52–53):

```yaml
# files/anatomy/plugins/<svc>-base/plugin.yml — authentik.autologin block
autologin:
  supports: yes
  enabled: "{{ (sso_autologin_<svc> | default(...)) | bool }}"
  local_login_fallback: "{{ enable_<svc>_local_login | default(false) | bool }}"
```

```yaml
# default.config.yml — operator toggle, default OFF (pure-SSO):
enable_<svc>_local_login: false
```

```jinja
{# files/anatomy/plugins/<svc>-base/templates/<svc>-base.compose.yml.j2 #}
{% if enable_<svc>_local_login | default(false) | bool %}
      ALLOW_LOCAL_LOGIN: "true"   {# or the service's equivalent env #}
{% endif %}
```

When `enable_<svc>_local_login: true`, the compose-extension conditionally
renders an `ALLOW_LOCAL_LOGIN`-style env so the local form stays reachable even
with autologin on — a permanent, configured break-glass rather than an ad-hoc
recreate.

> **Current state:** no service wires this env yet — it is a documented pattern,
> not a live wiring. The gate `tests/anatomy/test_local_login_fallback_renders_when_enabled.py`
> is **tolerant**: it skips when no plugin declares `local_login_fallback`, and
> asserts the conditional render only once a service adopts the pattern. This
> runbook section IS the documentation the gate's skip path points operators to.
> Adopting it for a service is a per-service compose-extension edit (out of
> Batch-4 scope — Batch 4 wires the mechanism + docs, not the per-service env).

The toggle is only meaningful for services that physically have a local-login
UI (the URL-param rows in the truth-table). For gitea / miniflux / vaultwarden
the "fallback" is the env-unset + recreate above, not a live `ALLOW_LOCAL_LOGIN`.

---

## `~/.nos/secrets.yml` backup

`~/.nos/secrets.yml` is the persistent secrets store. It holds
`authentik_recovery_key` (the offline input for CLI recovery) and other
generated secrets, read idempotently across playbook re-runs.

**Back it up off-box.** If Authentik is unreachable AND you have no local copy
of the recovery key, you lose the offline escape path:

```bash
# Copy somewhere outside the nOS tree / off the host (encrypted, e.g. a vault
# entry or an encrypted USB). Treat it like a root credential.
cp ~/.nos/secrets.yml ~/secure-backup/nos-secrets-$(date +%F).yml
chmod 600 ~/secure-backup/nos-secrets-*.yml
```

> Plan instruction (verbatim intent): *"back up `~/.nos/secrets.yml` outside nOS
> — it is the only offline input for CLI recovery if Authentik is unavailable."*
>
> The backup files (`backup.sh`) already encrypt at rest (AES-256, gov batch),
> but a manual off-box copy of `secrets.yml` is the deliberate redundancy for the
> break-glass path specifically.

---

## Last resort — nuke-and-reroll

Only when Authentik's database is irrecoverably corrupt and no recovery key /
admin exists. This **destroys the Authentik IdP database** (all users, groups,
providers, OIDC clients) and re-provisions from blueprints + plugin manifests.
Every service's OIDC binding is re-minted; per-user identities in services that
auto-provision from SSO will re-create on next login.

```bash
# 1. PRESERVE the break-glass key + any non-Authentik secrets FIRST:
cp ~/.nos/secrets.yml ~/secure-backup/nos-secrets-prereroll.yml

# 2. Turn autologin OFF so the reroll doesn't lock you out mid-reprovision:
#    set sso_autologin: false in config.yml

# 3. Stop + wipe ONLY the Authentik DB state (NOT the whole infra stack).
#    Authentik stores in PostgreSQL (infra-postgresql-1) under its own DB;
#    dropping + recreating that DB then re-running the playbook re-seeds it:
docker exec infra-postgresql-1 psql -U postgres -c \
  "DROP DATABASE authentik; CREATE DATABASE authentik OWNER authentik;"

# 4. Re-run the playbook — Authentik blueprints + per-plugin authentik: blocks
#    re-provision providers/apps/flows; first-admin via Wing invite-onboarding
#    (A15, ?itoken=). Autologin stays OFF until you re-enable post-recovery.
ansible-playbook main.yml --tags ssh,authentik   # or a full run
```

If even PostgreSQL is unrecoverable, a full `ansible-playbook main.yml -e blank=true`
wipes and reinstalls everything from scratch (the documented clean-reinstall
path) — losing all service data, so this is the genuine last resort.

---

## Pre-existing risk note

Pure-SSO without a local fallback = lockout if Authentik is down — this is true
**today** for every native_oidc service, independent of autologin. Autologin
does not make it worse (it adds the per-service escapes above). Mitigations:
run Authentik HA (2+ replicas), keep `~/.nos/secrets.yml` backed up off-box, or
accept the downtime risk. See plan §"Bezpečnost" closing note.
