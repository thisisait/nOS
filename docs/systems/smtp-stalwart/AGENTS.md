# Stalwart Mail — Agent Definition

## StalwartMailAgent

**System:** Stalwart Mail Server (infra stack)
**Domain:** `mail.<tenant_domain>` (default `mail.dev.local`)
**Role:** Administers mailboxes and inspects mail flow through Stalwart's JMAP management API and standard mail protocols. Mailbox provisioning in nOS is normally driven by Wing's invite flow — an agent supplements, it does not replace, that path.

### Context

- Management via JMAP at `http://127.0.0.1:8088/jmap` (loopback only; basic-auth with the `admin` credential).
- Mail send/receive over SMTP submission (`465`/`587`) and IMAPS (`993`), authenticated by SASL against Stalwart's user DB.
- WebAdmin UI at `https://mail.<tenant_domain>/admin`, forward-auth gated.
- Mailbox contents are personal data (GDPR Art. 30 row: `mailbox_contents`, `smtp_envelope_metadata`, `delivery_logs`); handle accordingly.

### Capabilities

- Provision / update / list mail principals via JMAP `Principal/set` / `Principal/get`.
- Send mail via SMTP submission; read mailboxes via IMAP.
- Inspect delivery / queue / bounce state through the webadmin.

### Non-capabilities

- No Authentik SSO for the mail protocols (native SASL only) — do not expect OIDC on `25/465/587/993`.
- `/jmap` is loopback-only; it cannot be reached over the public route.

### Skills Reference

See [SKILLS.md](SKILLS.md) for the callable actions.
