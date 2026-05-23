# Invite-flow Cesta B — Infisical + Stalwart provisioning

> **Authoritative guide for Anatomy A18 (2026-05-20).** When the operator
> invites a user from Wing's `/users/invite` page, Wing optionally mints
> additional artefacts alongside the Authentik invitation: an Infisical
> folder holding per-user credentials and a Stalwart mailbox provisioned
> via JMAP. The Authentik password stays user-picked via enrollment.

## Why "Cesta B Hybrid"

We surveyed three paths before locking the design:

- **Cesta A** — operator generates everything (incl. Authentik password)
  and hands the user a share link. Pros: one operator step. Cons: the
  admin technically knows the user's Authentik password; GDPR cost.
- **Cesta B Hybrid (chosen)** — Authentik password = user-picked via the
  existing enrollment flow; mailbox + future service creds are
  pre-provisioned by the operator and stored in Infisical for the user
  to retrieve. Best UX + lowest credential-leak surface.
- **Cesta C** — Infisical-only. Mailbox provisioning is deferred to the
  operator's manual webadmin work. The fallback path when Stalwart isn't
  deployed.

The runtime automatically degrades from B → C when Stalwart isn't live,
and from B → A15-only (Authentik invitation alone) when Infisical isn't
live either. Each downstream client is independently `isConfigured()`-gated.

## End-to-end flow

```
OPERATOR clicks "Invite alice@pazny.eu (Tier-2)" in Wing /users/invite
  │
  ▼
Wing UsersPresenter::actionInviteCreate
  │
  ├── 1. POST Authentik /api/v3/stages/invitation/invitations/  ✅ (A15, baseline)
  │       └── creates invitation stage with fixed_data.target_groups + apps
  │
  ├── 2. maybeProvisionCredentials($emailHint, $tenant, ...)     ⭐ A18 new
  │       │
  │       ├── 2.0 PREFLIGHT — InfisicalClient.listUserSecrets($tenant, 'alice')
  │       │        If non-empty → emit user_invitation_provisioning_skipped
  │       │        event and bail out (re-invite idempotency, security C4).
  │       │
  │       ├── 2a. InfisicalClient.createUserFolder($tenant, 'alice')
  │       │        POST /api/v2/folders  (idempotent: /users + /users/<tenant>
  │       │        + /users/<tenant>/alice)
  │       │
  │       ├── 2b. generateMailboxPassword()  → 24-char URL-safe
  │       │
  │       ├── 2c. InfisicalClient.upsertSecret($tenant, 'alice', 'mailbox_password', $pw)
  │       │        POST /api/v3/secrets/raw/mailbox_password (+ PATCH fallback)
  │       │
  │       └── 2d. StalwartProvisioner.createMailbox('alice', $mailDomain, $pw)
  │                POST 127.0.0.1:8080/jmap  methodCalls=[["Principal/set", ...]]
  │                $mailDomain comes from TENANT_DOMAIN env (operator's
  │                configured mail domain), NOT from email_hint's @-suffix.
  │
  ├── 3. events.insert(type='user_invitation_provisioned', ...)
  │       └── audit row with infisical_done / stalwart_done / errors[]
  │
  ├── 4. user_invitations.provisioning_json = $result (DB snapshot)
  │
  └── redirect /users/created?uuid=<invitation_uuid>
         │
         ▼
USER receives the enrollment URL (operator copies it from /users/created)
USER opens URL → picks own Authentik password → Authentik creates the user
  │
  ▼
USER retrieves mailbox password from Infisical share UI (operator gives them
the link or a one-shot tokenized URL from Infisical's "share secret" feature)
```

## Security model (post-2026-05-20 hardening pass)

The flow above absorbed seven security findings before going live:

| Code | Severity | Mitigation |
|---|---|---|
| **C1** | 🔴 Critical | Wing / Bone / Pulse plists are mode `0600`. They embed admin tokens (Infisical, Stalwart, Authentik bootstrap, Bone HMAC, deploy HMAC). 0644 would leak the whole credential surface to peer processes (Spotlight indexers, third-party backup agents, Full-Disk-Access apps). Pinned by `tests/anatomy/test_invite_provisioning.py::test_anatomy_plist_files_locked_to_0600`. |
| **C2** | 🔴 Critical | Stalwart's Traefik route is scoped to `PathPrefix(/admin)`. Without that, the same `Host(mail.<tld>)` rule would expose `/jmap` publicly behind forward-auth — and forward-auth gates ACCESS, not AUTHORIZATION, so any Tier-4 guest with a valid Authentik session could brute-force Basic-auth against admin creds. Wing reaches `/jmap` via `127.0.0.1:<stalwart_port_admin>` only. |
| **C3** | 🔴 Critical | Infisical paths are tenant-namespaced: `/users/<tenant>/<localPart>/<key>`. Two tenants inviting different humans named "alice" can't overwrite each other's `mailbox_password`. |
| **C4** | 🔴 Critical | Idempotency preflight: `InfisicalClient.listUserSecrets()` runs BEFORE any password generation. If the user folder already holds secrets, we emit a `user_invitation_provisioning_skipped` event and bail — prevents the "generate new pw, Infisical accepts, Stalwart rejects (already exists), user locked out" failure mode. |
| **C5** | 🟠 High | Username regex tightened to reject `..` substrings (RFC 5321 forbids consecutive dots anyway). Belt-and-suspenders: presenter, InfisicalClient, StalwartProvisioner all check. |
| **C6** | 🟠 High | Upstream response bodies are stripped from RuntimeException messages. Stalwart's `notCreated` echoes the existing principal's email (peer-user PII) — we collapse it to a calibrated `reason=<type>` slug. Both clients' generic error paths replace `substr($raw, 0, 500)` with `"HTTP <code> (body suppressed; check <svc> logs)"`. UsersPresenter additionally `sanitizeErrorMessage()`s anything stashed in `provisioning_json`. |
| **C7** | 🟠 High | Stalwart mailbox domain comes from `TENANT_DOMAIN` env, NOT from `email_hint`'s @-suffix. `email_hint` is just where the operator might forward the enrollment URL to (gmail.com is valid); the mailbox itself always lives on the operator's configured mail domain. |

### Known limitations (deferred)

- **No CSRF token** on `/users/invite-create` POST. The form is hand-rolled (not Nette UI Form) and BasePresenter only validates HTTP method. Mitigation today: the form is gated by `requireSuperAdmin()` (super-admin operators are trusted), but a malicious page combined with a logged-in operator session could mint invitations. **Status:** queued for a follow-up commit (Nette session-token middleware in BasePresenter).
- **Infisical admin token is not scoped.** Wing uses the full `infisical_admin_token` from `default.credentials.yml`. A Wing RCE = full vault compromise. **Status:** queued — needs a scoped Infisical machine identity (write-only on `/users/*`).
- **No rate limit on `/users/invite-create`.** Combined with the CSRF gap, a compromised super-admin session could spam invites. **Status:** low priority while super-admins are trusted; revisit when A14 agent flows can call presenters.
- **Race condition window remains.** Two concurrent invites for the same `localPart` within the millisecond gap between `listUserSecrets` (returns empty) and `upsertSecret` (writes) could still drift. Mitigation: super-admin operators are typically a single human; revisit if Pulse-driven auto-invites land.

## Configuration knobs

All flags live in `config.yml` overrides (defaults shown):

```yaml
# Master toggle. When false, the A18 extension is fully disabled and the
# invite flow behaves identically to A15.
nos_invite_provisioning_enabled: false

# Infisical project that holds per-user folders. Populated after first
# install (see "Bootstrap" below).
infisical_users_project_id: ""
infisical_users_environment: "prod"

# Stalwart admin user — wired into the JMAP Basic-auth header. Created
# at first boot via STALWART_RECOVERY_ADMIN env var (handled by the role).
stalwart_admin_username: "admin"
# stalwart_admin_password lives in default.credentials.yml
```

Wing reads these via the launchd plist (`roles/pazny.wing/templates/wing.plist.j2`):

```
NOS_INVITE_PROVISIONING_ENABLED   "1" when nos_invite_provisioning_enabled=true
INFISICAL_API_URL                 http://127.0.0.1:8075 (or operator override)
INFISICAL_API_TOKEN               infisical_admin_token from credentials
INFISICAL_USERS_PROJECT_ID        UUID of the nos-users project
INFISICAL_USERS_ENVIRONMENT       prod (configurable)
STALWART_API_URL                  http://127.0.0.1:8080
STALWART_ADMIN_USER               admin (configurable)
STALWART_ADMIN_PASSWORD           stalwart_admin_password from credentials
```

## Quick test — Infisical-only path (MVP, no Stalwart needed)

This is the smallest end-to-end loop you can run today to verify the
A18 wiring. Stalwart provisioning is graceful-degraded, so you can
test the Authentik invitation + Infisical credential push WITHOUT
ever touching the Stalwart admin wizard.

Prereqs:
- `install_infisical: true` in your config (already on by default)
- Wing + Bone + Authentik live (verify: `curl -sf http://127.0.0.1:9000/` returns 200)

### One-time: machine identity for the seeder (only if pre-existing Infisical)

If Infisical is **freshly installed** by this playbook run, `infisical
bootstrap` runs automatically + captures the admin token. **Skip this
section.**

If Infisical is **already running** from a prior install (admin user
exists, no `infisical_admin_token` in `~/.nos/secrets.yml`), the
bootstrap step returns "already bootstrapped" and the seed chain
stops. Recover by minting a machine identity ONCE:

1. Open `https://vault.<tld>` and log in:
   - email: `admin@<tld>`
   - password: value of `{{ global_password_prefix }}_pw_infisical_admin`
2. **Org Settings → Access Control → Identities → "Create identity"**
   - Name: `nos-seeder`
   - Organization role: `Admin`
3. Click the new identity → **Authentication → UniversalAuth → "Create Client Secret"**
4. Copy **Client ID** + **Client Secret** values.
5. Paste into `credentials.yml` (gitignored, alongside other operator overrides):
   ```yaml
   infisical_machine_id_client_id: "<paste>"
   infisical_machine_id_client_secret: "<paste>"
   ```

From now on, every playbook run exchanges these for a fresh access
token via `/api/v1/auth/universal-auth/login`. The JWT never sits on
disk and never expires from your perspective.

### Steps

1. **In `config.yml`:**
   ```yaml
   nos_invite_provisioning_enabled: true
   ```
   That's it — no Stalwart toggle, no UUID copy.

2. **Run the playbook:**
   ```bash
   ansible-playbook main.yml
   ```
   The infisical role's seeder creates `nos-users` project and writes its
   UUID to `~/.nos/secrets.yml::infisical_users_project_id` automatically
   (A18, 2026-05-23). Wing's plist picks it up on the same run. No manual
   UUID copy required.

3. **Verify the toggle propagated:**
   ```bash
   grep -E "NOS_INVITE_PROVISIONING|INFISICAL_USERS_PROJECT_ID" \
     ~/Library/LaunchAgents/eu.thisisait.nos.wing.plist
   ```
   Both lines should be non-empty.

4. **Submit a test invite** at `https://wing.<tld>/users/invite`:
   - Email hint: `testuser@<tld>`
   - Tier: 2 (manager)
   - Apps: leave empty for now

5. **Verify the result:**
   - `/users/created` lands with the enrollment URL + provisioning snapshot
   - `/audit` shows `user_invitation_provisioned` event with
     `infisical_done=true`, `stalwart_done=false` (skip — toggle off)
   - In Infisical UI (`https://vault.<tld>`), browse to project
     `nOS Users` → environment `prod` → path `/users/default/testuser/` →
     `mailbox_password` secret exists with a 24-char value

That's the Cesta B Infisical path verified. When you're ready to add
mailbox provisioning, see the next section.

## Full bootstrap (with Stalwart mailbox provisioning)

Once the Infisical path above works, add Stalwart for end-to-end
mailbox provisioning:

1. **Enable + walk the Stalwart wizard once.**
   ```yaml
   install_smtp_stalwart: true
   ```
   Re-run the playbook. Open `https://mail.<tld>/admin`, log in with
   `admin` + `stalwart_admin_password`. The bootstrap wizard walks
   through domain + DKIM + TLS cert paths. The wildcard cert from
   `pazny.acme` is mounted inside the container at:
   ```
   /certs/cert.pem
   /certs/key.pem
   ```
   (NOT `/etc/stalwart/certs/*` — Docker Desktop virtiofs on macOS
   can't handle nested file binds; details in
   `roles/pazny.smtp_stalwart/templates/compose.yml.j2` comment.)
   Wizard generates `/etc/stalwart/config.json`. After that, JMAP is
   live on the host at `http://127.0.0.1:8088/jmap`.

2. **Re-run the playbook** so Wing's plist picks up
   `STALWART_ADMIN_PASSWORD` + `STALWART_API_URL`.

3. **Verify** — same invite as in the MVP section, but now
   `stalwart_done=true` and the mailbox is reachable via swaks:
   ```bash
   swaks --to testuser@<tld> --server mail.<tld>:587 --auth LOGIN \
     --auth-user testuser --auth-password <pw-from-Infisical>
   ```

## Failure modes & graceful degradation

| Scenario | What happens | What the operator sees |
|---|---|---|
| `nos_invite_provisioning_enabled=false` | Step 2 skipped entirely. | A15 behaviour exactly — Authentik invitation only. |
| `INFISICAL_USERS_PROJECT_ID` empty | `InfisicalClient::isConfigured()` returns false. Step 2a–2c skipped. **Stalwart step 2d also skipped** (no password to use). | `provisioning_json.infisical_done=false`, `stalwart_done=false`. /users/created shows operator hint. |
| Infisical down (network/4xx/5xx) | RuntimeException caught; `errors[] += 'infisical: <msg>'`. `mailboxPassword=null` → Stalwart step also skipped. | `errors[]` visible in /users/created + /audit. |
| Stalwart down or `STALWART_ADMIN_PASSWORD` empty | RuntimeException caught; `errors[] += 'stalwart: <msg>'`. Infisical secret was already written, so operator can replay the mailbox creation manually using the password from Infisical. | `infisical_done=true`, `stalwart_done=false`. |
| Wrong email format (no `@`, bad local-part) | Step 2 skipped (no username anchor). | A15 behaviour; provisioning_json stays `{}`. |
| Authentik down | A15 path fails with HTTP 502; A18 step never reached. | Operator retries; A18 only triggers after A15 succeeds. |

**Hard guarantee:** A18 failures NEVER abort the Authentik invitation. If
the operator successfully mints an Authentik invitation, the URL is
always handed back via `/users/created` — any Cesta B downstream failure
is logged + surfaced, not propagated.

## Why these specific paths

- **Why a separate Wing `App\Model\InfisicalClient` from the agent-runtime
  `App\AgentKit\Vault\InfisicalClient`?** The AgentKit client is
  read-only and goes through the `infisical secrets get` CLI under
  hardened subprocess constraints (minimal env allowlist, no token in
  process env, secret never persisted). This Wing-side client is
  write-capable and lives on the FrankenPHP request path. Different
  threat models — mixing them would either widen the agent-runtime auth
  or leave the presenter without write reach.

- **Why JMAP, not REST, for Stalwart?** Stalwart v0.16 (2026-04-20)
  replaced the REST management API with JMAP entirely. The WebUI and
  `stalwart-cli` are now thin wrappers over `/jmap`. nOS pinned v0.11.8
  pre-A18 (REST-era); the A18 bundle bumps to v0.16.6 (the latest tag at
  ship time) — see `roles/pazny.smtp_stalwart/defaults/main.yml`.

- **Why a 24-char URL-safe password?** Crypto-strong (`random_bytes(24)`),
  no ambiguous chars (no `0/O/1/l/I`), URL-safe so it survives the
  Infisical share link encoding intact. The operator never sees it — it
  flows from `random_bytes` → Infisical → Stalwart → user via Infisical UI.

## What's deliberately NOT here

- **No password rotation.** Once the mailbox password is in Infisical,
  rotating it requires both a Stalwart webadmin step AND an Infisical
  update. No playbook gate exists today. Documented as
  "operator workflow" — flag it for a future A18.x refinement.
- **No service-creds beyond mailbox.** Bluesky PDS handles, Tier-2 app
  tokens, etc. are scoped out of A18. Adding them is a matter of one
  `$this->infisical->upsertSecret($localPart, '<service>_credential', ...)`
  call inside `maybeProvisionCredentials`.
- **No Authentik password generation.** Cesta A semantics — explicitly
  out of scope. Authentik enrollment owns that step.
- **No webhook from Authentik to mark Infisical "linked".** Today
  Infisical and Authentik both store the user identity but neither
  knows about the other. A future Authentik post-enrollment webhook
  could close that loop.

## Pinned by anatomy gates

`tests/anatomy/test_invite_provisioning.py` (31 tests) pins every layer
of this contract. A future PR that removes one of these layers (drops
the env wiring, reverts the Stalwart v0.16 image, deletes the schema
column, etc.) will fail CI rather than silently degrading the invite UX.
