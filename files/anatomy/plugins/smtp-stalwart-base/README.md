# smtp-stalwart-base

Wiring layer for `pazny.smtp_stalwart` — Stalwart Mail Server, the
production-grade Rust SMTP / IMAP / JMAP stack that lives in the `infra`
compose stack and replaces Mailpit on public-TLD deployments. The plugin
declares the role binding, GDPR Article 30 row, Loki log labels, and a
Wing `/hub` deep-link card; it emits no `authentik:` block because mail
protocols (SMTP / IMAP / SASL) cannot be trampolined through Authentik
OAuth without breaking MUA compatibility — credentials live in Stalwart's
native user DB. The webadmin's optional Authentik OIDC integration lives
entirely on the role side, gated by `stalwart_authentik_oidc` (Track G
phase 3), and is intentionally not plugin-aggregated yet. The plugin
activates whenever `install_smtp_stalwart: true` flips the production
mail server on, and the loader's `post_compose` hook checks the SMTP
port (default 25) as a TCP-level liveness probe.
