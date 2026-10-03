# nos-forum — what it stores and for how long

**Status:** PROPOSED, not yet confirmed by the operator. Change a number here AND in the
register row (`files/anatomy/plugins/nos-forum-base/plugin.yml`); the gate ties the two.
Pinned by `tests/anatomy/test_nos_forum_art30.py`. Product spec: github.com/pazny/nos-forum
`docs/spec/08-gdpr.md`.

## Data, per place

| Where | What | Basis | Retention |
|---|---|---|---|
| SpacetimeDB `nos-forum` | messages, forum topics and posts, reactions, read markers | legitimate_interests | **365 days** declared; **not enforced in v0.1** (no archiver) — rows stay until a user or moderator deletes them; deleted messages become tombstones |
| SpacetimeDB `nos-forum` | profile (username, display name, presence), memberships and roles | legitimate_interests | until the user leaves or is erased |
| SpacetimeDB `acl` / `peer` | pseudonymous membership graph (identity hashes, ids) | legitimate_interests | rebuilt on every membership change |
| Browser cookie `forum_session` | AES-256-GCM sealed id_token + refresh token | legitimate_interests | 30 days |
| Authentik | the account, OIDC grants | (svc_authentik row) | (svc_authentik row) |

Processors: none in v0.1 — everything runs on this host. Calls (v0.2) add LiveKit and,
when `nos_forum_cloudflare_turn` is on, Cloudflare as a TURN relay processor; that
change must add a row here and in `processors:` before the toggle ships.

## Rights

Erasure and export are **manual** in v0.1 (`state/gdpr-erasure-map.yml`,
`state/gdpr-export-map.yml`, entry `svc_nos-forum`): the module owner runs
`erase_subject` / SQL selects. A `forget` / `export` CLI lands with the archiver.

## Known limit

Any registered user can read the membership graph (identity hashes, server and channel
ids, moderator flags) — never names or content. Forced by the SpacetimeDB 2.7 RLS engine;
see the product spec 02, "Known limit", and open question Q15.
