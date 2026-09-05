# Identity — the declared account roster

> Status: doctrine, live since 2026-08-19. Gates:
> `tests/anatomy/test_an_identity_is_declared_not_inherited.py`,
> `tests/anatomy/test_the_identity_reader_only_reads.py`,
> `tests/anatomy/test_the_agent_identity_survives_recreate.py`.
> Reader: `tools/identity-status.py`.

## 1. Why this exists

Until 2026-08-19 the estate declared no identities. `gitea_admin_user`
derived from `ansible_facts['user_id']` (whoever ran the playbook),
`WOODPECKER_ADMIN` inherited that, `akadmin` existed only inside an Authentik
blueprint template, and the agentic loop shipped four credential-level
identities on top of all of it. The measured cost: the operator signed into
Woodpecker as `akadmin`, the allowlist said `pazny`, and the fix was a
hand-edited `config.yml` line — a fifth undeclared place.

The rule this document sets: **an account exists because the roster declares
it, and a realm's admin/allowlist derives from the roster.** Never the other
way around, and never from the OS.

## 2. The model

An **identity** is `{name, kind, tier, email, realms}`:

- `kind` — `operator` (human, runs the estate), `user` (human, uses it),
  `service` (an account no human logs into interactively: nos-tester,
  break-glass), `agent` (an autonomous process).
- `tier` — the RBAC vocabulary already settled by `authentik_rbac_tiers` and
  the genome's `access.tier` (1 admin … 4 guest). One vocabulary, not a new
  one.
- `realms` — where the account must be able to exist/authenticate:
  `authentik | gitea | gitlab | woodpecker | wing`. A realm consumer var is a
  PROJECTION of the roster (e.g. `woodpecker_admin` = every identity whose
  realms include `woodpecker`, joined by commas).

## 3. One roster per credential channel — three channels, one reader

Re-typing a roster is how drift starts (the version-pin lesson,
`test_a_pin_is_declared_once`). So there are exactly three declarations, each
owning its channel, none copying another:

| channel | declaration | credential shape |
|---|---|---|
| accounts (humans + service) | `nos_identities` in `default.config.yml` | realm-native login / SSO |
| machine OIDC clients | `authentik_agent_clients` in `default.config.yml` | `client_credentials` JWT (`docs/sso-and-attribution.md`) |
| loop identities | `IDENTITIES` in `files/anatomy/bone/loopauth.py` | scoped bearer tokens (propose/judge/forget) |

`tools/identity-status.py` is the single reader that joins all three and asks
the realms. It is strictly a reader (gate above), exits 0 whatever it finds,
and reports an unreadable realm as UNKNOWN — never green.

## 4. Presence is not validity

The declaration is checked against the realm, both directions:

- **declared but absent** → `MISSING` (the account the model promises does
  not exist; Woodpecker rows materialize at first login, and the reader says
  it cannot distinguish never-logged-in from allowlist-refused).
- **present but undeclared** → `UNDECLARED`. The reader's first run found 65
  orphaned `nos-tester-e2e-*` Authentik accounts — ephemeral testers whose
  cleanup never ran — plus the outpost service account. An undeclared account
  is not automatically wrong (invitation-provisioned users are runtime
  population, §6), but it must be VISIBLE.
- **unreadable realm** → `?`. No data is not no problem.

Reconciliation is split by custody: the **playbook** may create/converge what
the roster declares (auditable, tagged); **deleting** a live account is an
operator act the reader may only recommend. The one narrow exception is
`pazny.woodpecker/tasks/post-agents.yml`, which deletes *agent rows* (not
users) stale on both `created` and `last_contact` — machine registrations,
not identities.

## 5. Target state — akadmin primary (OPERATOR ACT, not yet performed)

The declared intent (operator, 2026-08-19): `akadmin` is the primary account
everywhere including Gitea; agent service accounts inherit from it; `pazny`
is the first real END USER. The default roster still describes CURRENT truth
(local forge admin = OS username) so a converge is byte-identical. The flip
is a supervised sequence:

1. `akadmin` logs into Gitea once via Authentik (OIDC auto-creates the row —
   `gitea_allow_only_external_registration: true` permits this).
2. Grant admin: `PATCH /api/v1/admin/users/akadmin {"admin": true}` under the
   existing local admin, or `gitea admin user change-access`.
3. Re-home ownership: the nOS mirror repo, Woodpecker OAuth app, and the
   agent-forge PAT (`gitea_api_token` is minted for `gitea_admin_user` —
   post-forge.yml re-mints under the new owner on the next converge once the
   var flips).
4. Re-declare in the roster: `akadmin` gains realm `gitea`; the old local
   admin becomes `kind: service` (break-glass, local-form login only) or
   `kind: user, tier: 3` per the pazny-as-end-user intent.
5. Only then flip `gitea_admin_user`'s source. NOTE: `nos_primary_admin`
   currently names the LOCAL admin; the flip will introduce
   a distinct `gitea_admin_user` override in config.yml first, and promote it
   to the default only after a blank proves the sequence.
6. `tools/identity-status.py` must show `akadmin gitea=ok` before step 5, and
   no MISSING after it.

What a converge would do TODAY, unflipped: nothing. `gitea_admin_user`
renders to the same value as before; `woodpecker_admin` default becomes
`akadmin,<primary>` (on the live estate the config.yml override already says
the same set); the Woodpecker compose fragment change recreates the agent
container once, which mints one final agent row that then persists.

## 6. Where this goes next

- **Invitations** (`docs/invite-provisioning.md`) stay the runtime channel
  for humans: an invited user is Authentik-resident population, not a roster
  entry. The floor/population split is deliberate — the roster is the set
  that MUST exist for the estate to function; invitations grow the set that
  MAY. The reader should eventually join Wing's `user_invitations` table so
  invited users stop reporting as UNDECLARED.
- **Multi-tenant**: entries gain a `tenant` field; per-tenant projections
  (`woodpecker_admin`, Authentik group bindings) filter on it. The derivation
  pattern (§2) already supports this — it is a second `if` in the loop.
- **Per-agent service accounts**: when an agent needs a realm account a human
  never logs into (e.g. a Gitea account owning loop MRs instead of the
  admin's PAT), it enters `nos_identities` as `kind: agent` with the realm —
  the roster shape is ready; what is missing is the realm-side provisioner,
  which should follow the blueprint/post.yml pattern of its realm.
- **Genome**: the `access` facet collapsed five route declarations into one
  fact; an `identity` facet can do the same for the per-service admin
  accounts (`*_admin_email`, `*_admin_user` singletons scattered through
  `default.config.yml`) once services are genome-migrated. Do not build it
  speculatively — migrate consumers as they are touched.
- **DataTables principal vocabulary** (`dtt-share-model`, coordinated with KEAP
  2026-09-05): the `owner`/`shared_with` ACL keys on a DataTable row are
  `user:<canonicalUid>` and `agent:<name>` — NEVER `X-Authentik-Uid`, which is
  random and regenerates on a tenant blank (KEAP identity.ts doctrine; the same
  reason nothing durable here keys on it). `<canonicalUid>` = `canonicalUid(username)`,
  the key KEAP already scopes user rows/captures/fs-cards by; `<name>` = the
  AgentKit client-id (slug-safe, no `:`). Agent-side identity is COOPERATIVE in
  phase 1 (the door trusts `x-keap-agent` after bearer validation — any RW-token
  holder can claim any name; enforcement is real against humans-without-tier,
  advisory between token-sharing agents), tightening to per-agent bearers in
  phase 2 with no schema change. **Reserved external-agent principals** (so
  phase 2 renames nobody): `agent:cursor`, `agent:codex`, `agent:claude-code` —
  the external MCP coding agents that reach tables via `tools/mcp-tables-server.py`.
  The visibility GRADE ladder is KEAP's existing one (`private`/`tier-*`/`shared`
  + the new `system`), one source in KEAP `shared/contracts/visibility.ts`, not a
  nOS-side enum. Wiring waits on KEAP's contract-first zod draft.

## 7. What is deliberately NOT here

- No password/secret material — the roster names accounts; credentials stay
  in the credentials layering and Infisical (`docs/archive/secret-blast-radius.md`).
- No per-service admin singletons (yet) — see §6 genome.
- No automatic deletion of UNDECLARED accounts — visibility first, custody
  stays with the operator. The 65 orphaned e2e testers are a cleanup ticket,
  not a reader feature.
