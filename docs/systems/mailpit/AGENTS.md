# Mailpit — Agent Definition

## MailpitAgent

**System:** Mailpit (SMTP capture sink + web UI, `iiab` stack)
**Node:** `nos.iiab.mailpit`
**Domain:** `mail.<tenant_domain>` (default `mail.dev.local`)
**Role:** Inspects mail captured from every relaying service, and accepts test
mail into the sink over SMTP. The estate's dev-grade mail observability surface.

### Context

- REST base: `http://127.0.0.1:8025/api/v1/` (loopback, unauthenticated) or
  `https://mail.<tenant_domain>` (edge, Authentik forward-auth gated).
- SMTP sink: `127.0.0.1:1025` — accepts any credentials (`MP_SMTP_AUTH_ACCEPT_ANY`).
- Store: SQLite at `/data/mailpit.db`, capped at 5000 messages.
- SSO bucket: `forward_auth`, Tier 1. No native OIDC; optional UI basic auth is
  disabled by default (`mailpit_ui_user`/`mailpit_ui_password` empty).

### Capabilities

- List, read, and search captured messages (headers, text, HTML, attachments).
- Delete individual messages or clear the whole inbox.
- Send test mail via SMTP `1025` to verify a service's mail path.
- Check liveness/readiness (`/livez`, `/readyz`).

### Limits

- Not a real MTA — no outbound delivery in dev (`tenant_domain=dev.local`). When
  Stalwart is enabled it becomes the real MTA and Mailpit is an archival mirror.
- Retention is bounded (5000 messages); older mail is pruned automatically.

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
