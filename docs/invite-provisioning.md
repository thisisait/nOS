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
  ├── 2. maybeProvisionCredentials($emailHint, ...)              ⭐ A18 new
  │       │
  │       ├── 2a. InfisicalClient.createUserFolder('alice')      [if isConfigured]
  │       │        POST /api/v2/folders  (idempotent: /users + /users/alice)
  │       │
  │       ├── 2b. generateMailboxPassword()  → 24-char URL-safe
  │       │
  │       ├── 2c. InfisicalClient.upsertSecret('alice', 'mailbox_password', $pw)
  │       │        POST /api/v3/secrets/raw/mailbox_password (+ PATCH fallback)
  │       │
  │       └── 2d. StalwartProvisioner.createMailbox('alice', 'pazny.eu', $pw)
  │                POST /jmap   methodCalls=[["Principal/set",{create:...},"c0"]]
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

## Bootstrap

First-time setup, after a fresh blank with `install_infisical: true` +
`install_smtp_stalwart: true`:

1. **Let the playbook seed Infisical.** `roles/pazny.infisical/files/seed.py`
   creates the `nos-users` project among others. Look for the project ID:

   ```bash
   infisical projects list --plain | grep nos-users
   ```

   Copy the UUID into `config.yml`:

   ```yaml
   infisical_users_project_id: "00000000-0000-4000-8000-aaaaaaaaaaaa"
   ```

2. **Walk the Stalwart wizard once.** Open `https://mail.<tld>/admin`,
   log in with `admin` + `stalwart_admin_password`. The bootstrap wizard
   walks through domain + DKIM + TLS cert paths (mounted at
   `/etc/stalwart/certs/` when the tenant is public). Wizard generates
   `/etc/stalwart/config.json` — after that, JMAP is live on `/jmap`.

3. **Flip the master toggle:**

   ```yaml
   nos_invite_provisioning_enabled: true
   ```

4. **Re-run the playbook** so Wing's plist picks up the new env. Bone +
   Wing both restart via launchd handlers.

5. **Verify:**

   ```bash
   # Wing /users/invite — operator-facing form. Submit a test invitation
   # with email_hint="testuser@<tld>" and Tier-2. After the redirect:
   #   - /users/created shows the provisioning_json snapshot
   #   - /audit shows the user_invitation_provisioned event
   #   - infisical secrets list /users/testuser/ — mailbox_password exists
   #   - swaks --to testuser@<tld> ... — mailbox accepts the test message
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
