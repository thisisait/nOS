# 52 — A migration that certified itself

**Found** 2026-09-02; **closed** 2026-09-03.

D2 (CLAUDE.md, "Recently shipped"): role compose templates carry no OIDC env;
plugin compose-extensions are the live render path. Declared 2026-05-05,
scrubbed 2026-05-20 — and never gated. `roles/pazny.nodered` still rendered
`NODERED_OIDC_CLIENT_ID/SECRET` sixteen weeks later.

Close: the env moved to the nodered-base compose-extension, and D2 finally has
its gate — `test_no_role_compose_carries_an_oidc_client` sweeps every role
template. Residue, named not hidden: spacetimedb's role compose carries an
`SPACETIMEDB_OIDC_ISSUER` (config, not a credential — outside this gate's
class, inside D2's spirit; move it with the next spacetimedb touch).
