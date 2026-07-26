# SnappyMail — Agent Definition

## SnappyMailAgent

**System:** SnappyMail (webmail frontend, `iiab` stack)
**Node:** `nos.iiab.snappymail`
**Domain:** `webmail.<tenant_domain>` (default `webmail.dev.local`)
**Role:** Human-facing webmail UI over IMAP/SMTP. **No agent-invocable surface.**

### Context

- SSO bucket: `forward_auth`, Tier 3 — Authentik gates the UI; users log into
  their own IMAP account inside the app.
- Stateless (no database); config lives in the data directory, admin at `/?admin`.
- Connects to Stalwart (prod) or Mailpit (dev) as its IMAP/SMTP backend.

### Capabilities

- **None for agents.** There is no REST/bot API. Do not synthesize skills for
  this system — an agent that must read or send mail should call the mail server
  (Mailpit `nos.iiab.mailpit`, or Stalwart `nos.infra.smtp-stalwart`) instead.

### Skills Reference

See [SKILLS.md](SKILLS.md) — it documents, honestly, that there is no skill surface.
