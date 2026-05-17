# Users + Invitations console (Wing A15, 2026-05-17)

Operator-facing identity surface in Wing: see every Authentik user with
their RBAC tier(s) and tenant scope(s), mint operator-issued invitation
links with a per-app role overlay, audit issued invitations, and revoke
outstanding ones — all without leaving Wing.

This document is the operator runbook + structural spec. Anatomy gates
in `tests/anatomy/test_users_and_invitations.py` pin every contract
mentioned below; if a change to this doc isn't mirrored by a change to
a gate (or vice-versa), one of them is lying.

## Surfaces

| URL                      | Method | Tier-1? | What it does                                  |
|--------------------------|--------|---------|-----------------------------------------------|
| `/users`                 | GET    | yes     | Directory: every Authentik user + groups      |
| `/users/invite`          | GET    | yes     | Invitation form (tier + tenant + apps)        |
| `/users/invite-create`   | POST   | yes     | Mint the invitation (Authentik + audit row)   |
| `/users/created?uuid=…`  | GET    | yes     | Show shareable URL after a fresh mint         |
| `/users/invitations`     | GET    | yes     | Audit table: every issued invitation          |
| `/users/revoke`          | POST   | yes     | Revoke an outstanding (unredeemed) invitation |

Tier-1 = `nos-providers` OR `nos-admins` (per CLAUDE.md RBAC table,
locked by `BasePresenter::requireSuperAdmin()` since 2026-05-17). The
gate lives in `UsersPresenter::startup()` so every action inherits it
without per-method re-checks.

## Data flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Wing /users/invite (browser)                                            │
│                                                                          │
│   pick: tier + tenant + apps + ttl + email/name hints                    │
│   submit POST /users/invite-create                                       │
│                                                                          │
└────────────────────────────┬─────────────────────────────────────────────┘
                             │
                             ▼
                ┌─────────────────────────┐
                │  UsersPresenter         │
                │  ::actionInviteCreate   │
                │                         │
                │  1. validate inputs     │
                │  2. build groups list   │
                │     (tier + optional    │
                │     tenant prefix)     │
                │  3. mint UUID           │
                │  4. call Authentik      │
                └───────────┬─────────────┘
                            │
                            ▼
              ┌────────────────────────────────┐
              │  Authentik /api/v3/stages/      │
              │  invitation/invitations/  POST  │
              │                                 │
              │  fixed_data: { target_groups,   │
              │                target_apps,     │
              │                tenant, ... }    │
              │  flow: <nos-enrollment pk>      │
              │  single_use: true               │
              │  expires: <iso8601>             │
              └───────────┬─────────────────────┘
                          │
              returns { pk, expires, ... }
                          │
                          ▼
              ┌──────────────────────────┐
              │  UserInvitationRepository │
              │  ::insert  (wing.db audit)│
              │                          │
              │  + EventRepository       │
              │  ::insert (user_invita-  │
              │  tion_issued event)      │
              └───────────┬──────────────┘
                          │
                          ▼
              redirect → /users/created?uuid=…
              (operator copies invitation_url)
```

When the invitee redeems the link:

```
invitee opens https://auth.<tld>/if/flow/nos-enrollment/?itoken=<pk>
   │
   ▼
Authentik nos-enrollment flow (blueprint 40-enrollment-flow.yaml)
   ├─ stage 10: invitation-stage   (matches token, surfaces fixed_data)
   ├─ stage 20: prompt-stage       (collect email, name, username, password)
   ├─ stage 30: user-write          (mint the user row)
   │      └─ policy binding: nos-assign-target-groups
   │            └─ adds user to each group in fixed_data.target_groups
   └─ stage 40: user-login         (auto-sign-in into the session)
```

Authentik garbage-collects single-use invitations after redemption, but
`wing.db.user_invitations` keeps the audit row forever — that's why we
duplicate `target_groups_json` + `target_apps_json` locally rather than
just storing the Authentik `pk`.

## Multi-tenant model

A single nOS install can host multiple logical tenants. Each tenant is a
slug (`[a-z0-9-]{1,40}`) declared via `tenants_extra` in
`default.config.yml`; Wing surfaces them in the invite form's tenant
`<select>` (passed through as `TENANT_SLUGS` env on the wing daemon).

When the operator picks a non-`default` tenant + a tier, the invitation
binds the new user to BOTH groups (additive):

- `nos-<tier>`                       — base RBAC tier (Tier-1/2/3/4)
- `nos-tenant-<slug>-<tier-suffix>`  — tenant-scoped overlay

Example: tier `nos-managers` + tenant `acme-corp` →
`nos-managers` + `nos-tenant-acme-corp-managers`.

The base group keeps global RBAC policies (`authentik_rbac_tiers` in
`default.config.yml`) authoritative; the tenant overlay is your hook
point for per-tenant policy bindings (filtering applications, dashboards,
quotas, etc.) — those are not auto-provisioned by this slice.

## Operator pre-flight

The `/users` page surfaces a one-line diagnostic when its prerequisites
are not met. Two gates:

1. **`AUTHENTIK_BOOTSTRAP_TOKEN` env empty** → run
   `python3 tools/fetch-authentik-bootstrap-token.py` to capture the
   `nos-api` admin-API token from Authentik UI into
   `~/.nos/secrets.yml`, then re-run `ansible-playbook main.yml --tags wing`
   so the wing launchd plist picks up the new env. The page renders a
   yellow callout with the exact command instead of bleeding raw 401s.

2. **`nos-enrollment` flow not present** → re-run the playbook to
   converge the `40-enrollment-flow.yaml` blueprint. The page won't
   accept invitation submissions until Authentik confirms the flow
   exists (otherwise the invitation would be unbindable to any flow at
   mint time).

## Audit trail

Every issue + revoke writes:

- `wing.db.user_invitations` row (state machine: pending → redeemed | revoked | expired)
- `wing.db.events` row (`user_invitation_issued` / `user_invitation_revoked`)
- A10 `actor_id` = `operator:<X-Authentik-Username>` (forward-auth header)
- A10 `actor_action_id` = UUID shared between the user_invitations row
  and the corresponding event row, so a `WHERE actor_action_id=?` in
  /audit reconstructs both halves.

The presenter MUST NOT read attribution fields from the request body —
the X-Authentik-Username header is the only legitimate source.
`test_users_presenter_actor_id_from_forward_auth_headers` pins this so
a future refactor that accepts `$body['invited_by']` can't sneak
through unreviewed (regression of the 2026-05-17 GitleaksPresenter
fix that surfaced this anti-pattern).

## Adding a new tenant slug

```yaml
# config.yml (operator override of default.config.yml)
tenants_extra:
  - acme-corp
  - widgets-llc
```

Re-run `ansible-playbook main.yml --tags wing`. The `TENANT_SLUGS` env
on the wing daemon picks up the new list; refresh `/users/invite` and
the tenant `<select>` shows `default`, `acme-corp`, `widgets-llc`.

There is intentionally no auto-provisioning of the
`nos-tenant-<slug>-<tier>` groups in this slice — Authentik will create
them implicitly on first invitation that lands a user there (Authentik
group create-on-write is idempotent). If you want them pre-created with
expression policies attached, drop a tenant blueprint into
`files/anatomy/plugins/authentik-base/blueprints/50-tenants.yaml.j2`
following the same `authentik_core.group` shape as `00-admin-groups`.

## Pinned contracts (anatomy gates)

Run: `python3 -m pytest tests/anatomy/test_users_and_invitations.py -v`.

The gates pin (alphabetical):

- AuthentikClient surface + bootstrap-token env + pagination
- Bone + Wing event-type whitelist alignment
- DI registration in common.neon
- Enrollment-flow blueprint completeness + `continue_flow_without_invitation: false`
- Latte template presence + POST-only forms
- Schema (`user_invitations` columns + indexes)
- Tenant slug regex + tier whitelist
- Tier-1 `requireSuperAdmin` gate on every action
- UsersPresenter writes audit events for issue + revoke
- Wing.plist propagates `AUTHENTIK_BOOTSTRAP_TOKEN` + `TENANT_SLUGS`

## Deferred (out of this slice)

- **Webhook-driven redemption ingest**: Authentik can fire a webhook on
  `events.user_write` containing the redeemed user PK. Wiring that
  into Wing's Bone HMAC endpoint would auto-stamp
  `user_invitations.redeemed_at` + `redeemed_user_pk`. Today the operator
  sees "pending" until they manually click "View users" and notice
  the new user landed — fine for human scale, automate-able later.
- **Per-tenant policy auto-provisioning**: see "Adding a new tenant
  slug" above — pre-creating tenant groups + bindings is a separate
  blueprint slice, not bundled here.
- **Tenant-scoped /users filter**: today `/users` lists every user
  across all tenants. A tenant `<select>` filter on top of the
  directory view would compose with the existing search box.
