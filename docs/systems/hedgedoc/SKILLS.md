# HedgeDoc — Skills

> No external skill surface managed by nOS.

## No nOS-managed invocable surface

HedgeDoc in nOS exposes **no agent-invocable action**, read from source:

- **No bot account, no token.** The HedgeDoc role does no post-start setup at all (`roles/pazny.hedgedoc/tasks/main.yml`: "HedgeDoc has native OIDC … no post-start setup is required"). No service account, no API token file is created.
- **OIDC-only, per-user.** Access is `native_oidc` (Authentik client `nos-hedgedoc`, tier 3) with `CMD_ALLOW_ANONYMOUS: false` and `CMD_ALLOW_EMAIL_REGISTER: false`. Every principal authenticates interactively as themselves; there is no machine identity to hand an agent.
- **No stable nOS-wired API.** HedgeDoc's note operations are driven through its collaborative web/socket UI after an OIDC session, not a documented token API that nOS provisions. There is no verified endpoint + credential pair to write here.

The only non-UI endpoint touched from source is `GET /status` (a readiness probe used by the plugin health-wait), documented in the README health section — it is a liveness check, not an agent skill. Inventing a callable notes API here would be a confident-but-wrong answer, so it is omitted.
