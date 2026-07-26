# Stalwart Mail

> Stalwart — a Rust all-in-one mail server (SMTP + IMAP/POP3 + JMAP) in the infra stack. The production mail path; Mailpit stays as the local-dev capture sink.

## Quick Reference

| | |
|---|---|
| **WebAdmin URL** | `https://mail.<tenant_domain>/admin` (derived from `stalwart_domain`; default `mail.dev.local`) |
| **Mail ports (host)** | `25` SMTP (MTA), `465` SMTPS, `587` submission STARTTLS, `993` IMAPS |
| **Admin/JMAP port** | `127.0.0.1:8088` → container `8080` (`stalwart_port_admin`; host 8088 avoids cAdvisor's :8080) |
| **Stack** | `infra` |
| **Toggle** | `install_smtp_stalwart: false` (default; the role refuses to render on a local TLD) |
| **Image** | `stalwartlabs/stalwart:v0.16.6` (`stalwart_image`) |
| **Data** | `{{ nos_data_root }}/platform/services/stalwart/data` → `/etc/stalwart` (`/etc`) + `/var/lib/stalwart` (`/var`) (default `~/nos/platform/services/stalwart/data`) |
| **Container** | `smtp_stalwart` |
| **Manifest node** | `nos.infra.smtp-stalwart` |

## Authentication

- **Admin user:** `admin` (`stalwart_admin_username`), pre-pinned on first boot via `STALWART_RECOVERY_ADMIN`.
- **Admin password:** `{global_password_prefix}_pw_stalwart_admin` (`stalwart_admin_password`).
- **Mailbox users:** SMTP/IMAP SASL credentials in Stalwart's own user DB — not Authentik.
- **SSO bucket:** `none` for the mail protocols (SASL against Stalwart's DB — OAuth cannot be trampolined through SMTP/IMAP without breaking MUA compatibility). The **webadmin `/admin` route** is `forward_auth`-gated at Traefik (`authentik@file`). Webadmin OIDC is gated behind `stalwart_authentik_oidc: false` (Track G phase 3).

## Management API (JMAP)

- **Endpoint:** `http://127.0.0.1:8088/jmap` (loopback only — Wing, a host launchd daemon, reaches it here; it is never exposed publicly).
- Wing's invite flow provisions mailboxes through it (`App\Model\StalwartProvisioner`, `Principal/set` methodCalls).
- The public Traefik router is deliberately scoped to `PathPrefix(/admin)` so `/jmap` is never reachable behind the guest-accessible forward-auth session.

## Health Check

- **Container healthcheck:** TCP liveness on internal management `:8080` (`:>/dev/tcp/127.0.0.1/8080`).
- **Plugin `wait_health`:** TCP probe of SMTP `:25` (the SMTP `220` greeting is not HTTP, so the loader's TCP fallback handles it).

## Dependencies

- Public DNS records for production: `MX`, `A mail.<td>`, SPF/DMARC `TXT`, and a DKIM selector (Stalwart auto-generates the key; operator pastes it into DNS).
- Open router ports `25/465/587/993` (many home ISPs block `25`).
- Traefik + Authentik (webadmin `/admin` forward-auth gate).
- Wing (consumes JMAP for invite-driven mailbox provisioning).
