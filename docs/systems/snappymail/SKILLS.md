# SnappyMail — Skills

> **SnappyMail has no external skill surface.** It is a human-facing webmail UI,
> not an agent-invocable service — there is no REST/bot API for an agent to call.
> This file is intentionally skill-free so recall never routes an agent to a
> fabricated endpoint (a confident-wrong route is worse than no route).

## Why there is no skill surface

- SnappyMail is a **webmail client**: a human logs into their IMAP/SMTP account
  through the browser UI. The mail account is the identity; nothing is invoked
  on behalf of an agent.
- **No bot/REST API** is exposed or provisioned. The only programmatic-looking
  surface is the `/?admin` **admin panel**, which is an interactive HTML console
  for configuring domains, plugins, and contacts — not a machine API, and its
  admin password lives in the data directory, unmanaged by the playbook.
- The `SNAPPYMAIL_DEFAULT_IMAP_HOST` / `SNAPPYMAIL_DEFAULT_SMTP_HOST` env vars in
  the compose fragment are **informational/reserved** — the image does not read
  them to configure anything.

## If you need to act on mail programmatically

Talk to the **mail server**, not the webmail frontend:

- **Read/send captured dev mail** → use Mailpit's REST/SMTP API
  (`nos.iiab.mailpit`).
- **Real IMAP/SMTP/JMAP** → talk to Stalwart (`nos.infra.smtp_stalwart`) directly.

SnappyMail sits *on top of* those; it adds no callable capability of its own.
