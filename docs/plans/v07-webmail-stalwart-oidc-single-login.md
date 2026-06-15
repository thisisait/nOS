# v0.7 — Webmail single-login: Stalwart OIDC + XOAUTH2 (snappymail / roundcube)

Status: PLAN (do not rush — this is the deferred Track-G phase-3 feature, not a
quick fix). Branch: `feat/v0.7-overnight`.
Source: SSO fleet diagnosis 2026-06 (`docs/sso-fleet-diagnosis-2026-06.md`) +
operator ask "close the webmail double-login". Companion to the shipped Kuma
single-login (`roles/pazny.uptime_kuma/tasks/monitors.yml`).

## Problem / why

SnappyMail and Roundcube sit behind the Authentik forward_auth gate, so the user
signs in ONCE at Authentik for ACCESS. But webmail is a *client* to a mail server
(Stalwart): after the gate, the webmail still asks for the **mailbox IMAP/SMTP
credential**, because that is a real, separate secret in Stalwart's native user
DB. So the user types a second password — the wart the operator flagged.

This is NOT the forward_auth "no button" non-bug (that's expected). It is a real
second credential, and unlike infisical (vendor-locked CE) it IS closeable —
Stalwart 0.16+ supports OIDC for the admin webui **and IMAP/SMTP SASL
`OAUTHBEARER` / `XOAUTH2`**. The capability exists but is gated off:
`roles/pazny.smtp_stalwart/defaults/main.yml` → `stalwart_authentik_oidc: false`
("Disabled until Track G phase 3"). The smtp-stalwart-base README is explicit that
this must be done carefully so it does not break plain-IMAP MUA compatibility.

## Approach (three coordinated parts)

1. **Stalwart side — enable OIDC + OAUTHBEARER (gated, MUA-safe).**
   Flip `stalwart_authentik_oidc: true` and render the Stalwart OIDC config
   (`roles/pazny.smtp_stalwart`): register Authentik as an OpenID provider, map
   the `preferred_username`/`email` claim to the Stalwart principal, and enable
   the `OAUTHBEARER`/`XOAUTH2` SASL mechanism on IMAP+SMTP **alongside** PLAIN
   (do NOT remove PLAIN — desktop MUAs without OAuth must keep working; that is
   the README's hard constraint). Authentik provider = a new native_oidc client
   `nos-stalwart` (per-plugin `authentik:` block → registry → tofu).

2. **Webmail side — XOAUTH2 against Authentik tokens.**
   - **SnappyMail**: ships an OAuth/`XOAUTH2` capability + a header/SSO plugin.
     Configure the IMAP/SMTP domain to use `XOAUTH2`, and wire the
     "auto-login from the Authentik forward-auth identity" path so the
     `Remote-User`/`Remote-Email` header the outpost already forwards seeds the
     account and the token is fetched via the client-credentials/redirect flow.
   - **Roundcube** (Tier-2 `apps/roundcube.yml`): the `oauth2`/`XOAUTH2` config
     keys (`oauth_*`) point at the Authentik token/authorize endpoints — INTERNAL
     `http://authentik-server:9000` for token, PUBLIC `https://auth.<tld>` for the
     browser authorize (the Portainer split — verified necessary, NOT the discovery
     trap). Roundcube then logs into Stalwart via `XOAUTH2` with the user's token.

3. **Identity coherence.** The Authentik `preferred_username` must match the
   Stalwart mailbox principal (the A18 invite flow already provisions
   `/users/<name>/` + a Stalwart mailbox — reuse that username as the OIDC subject
   so the token maps to the right mailbox). No new account namespace.

## Risks / what NOT to do

- **Never drop PLAIN SASL** — breaks desktop MUAs (Thunderbird etc.). OAUTHBEARER
  is additive.
- The Authentik token audience/scope must be accepted by Stalwart's resource
  server — mismatch = silent IMAP auth fail. Verify with a real `XOAUTH2` IMAP
  handshake, not just the webui OIDC button.
- Roundcube is Tier-2 (manifest) — the OAuth env must survive the apps_runner
  render; don't hand-edit the container.
- This touches live mail auth — do it on a branch with a wet-test, never rushed
  before a release tag.

## Gates

- `test_stalwart_oauthbearer_keeps_plain.py` — assert the SASL config enables
  OAUTHBEARER **and still** lists PLAIN (MUA-safety contract).
- `test_webmail_xoauth2_url_split.py` — SnappyMail/Roundcube token URL is internal,
  authorize URL is public (the Portainer split).
- Extend the SSO doctrine survey with a "webmail = OAUTHBEARER single-login" row.

## Verification recipe

1. Offline: the two gates + syntax-check.
2. Live: from the webmail UI behind the Authentik gate, open a mailbox with NO
   second password prompt (the token auto-authenticates IMAP). Then prove a plain
   desktop MUA (PLAIN SASL) still logs in — the additive contract.
3. `XOAUTH2` IMAP handshake test against Stalwart with a real Authentik token.

## Why deferred, not done now

Live mail-auth wiring with a token audience contract is a multi-part feature with
its own wet-test; rushing it before the v0.7 tag risks breaking working webmail +
desktop MUA auth. Kuma's single-login shipped (a self-contained DB setting);
webmail waits for a dedicated pass.
