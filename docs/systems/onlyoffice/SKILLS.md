# ONLYOFFICE Document Server — Skills

> No external skill surface managed by nOS.

## No nOS-managed invocable surface

ONLYOFFICE Document Server in nOS is a **backend embedded by other services**, not an agent-driven app, read from source:

- **No user login, no bot account.** End-users never authenticate here directly (`roles/pazny.onlyoffice/defaults/main.yml`: "End-users do not log in here directly — integration runs via JWT token shared with the host application"). There is no service account and no nOS-provisioned agent token.
- **The API is JWT-signed and host-app-driven.** The document endpoints (conversion, command service) are authenticated by a JWT signed with `onlyoffice_jwt_secret`, and are invoked **by the host apps** (Nextcloud, BookStack, Outline) as part of embedding the editor — not by nOS agents. The signing contract and request bodies are not defined in nOS source, so no exact callable can be documented here without inventing one.
- **Only one endpoint is verifiable and unauthenticated:** `GET /healthcheck` (returns `true`; the compose healthcheck curls it). That is a liveness probe, documented in the README health section — not an agent skill.

If an agent genuinely needed to drive conversions, an operator would build JWT-signed requests against the upstream ONLYOFFICE conversion/command API using `onlyoffice_jwt_secret`; that belongs in a deliberately-authored, verified skill sheet at that time. Until then, listing a callable document API here would be a confident-but-wrong answer, so it is omitted.
