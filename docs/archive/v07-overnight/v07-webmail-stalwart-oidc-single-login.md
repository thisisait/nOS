# v0.7 — Webmail single-login (snappymail / roundcube ↔ Stalwart ↔ Authentik)

Status: PLAN — BUILD-READY but GREENFIELD (multi-step; security-sensitive; needs a
dedicated wet-test, NOT a pre-tag config tweak). Branch: `feat/v0.7-overnight`.
Source: SSO fleet diagnosis + a deep capability research pass (current Stalwart
0.16 / SnappyMail / Roundcube / Authentik docs), 2026-06-15. Companion to the
shipped Kuma single-login.

## The brutal-honest verdict (read first)

- **XOAUTH2 / OAUTHBEARER driven by the forward_auth gate is ARCHITECTURALLY
  IMPOSSIBLE.** An Authentik proxy (forward_auth) provider **strips** the
  `Authorization` header and injects only `X-authentik-*` identity headers — it
  never forwards an OAuth access token. So the webmail cannot obtain a token from
  the gate to do XOAUTH2 IMAP. Any attempt down this road "almost works" and is a
  trap. (Authentik proxy header-auth docs, confirmed.)
- **The one robust path: SnappyMail → Stalwart MASTER-USER (impersonation) login,
  driven by the trusted `X-authentik-username` header.** Stalwart 0.16.6 supports
  impersonation: a service account with an `impersonate` Role logs in as any user
  via the composite credential `<target>%<impersonator>` using the impersonator's
  password — over **PLAIN SASL**, so it is purely ADDITIVE and never breaks the
  desktop-MUA PLAIN path (the smtp-stalwart-base doctrine constraint holds).
- **This is greenfield, not a tweak.** The live `smtp_stalwart` runs a stale
  minimal v0.11-style config (the role is a scaffold), SnappyMail has zero domains
  configured, and SnappyMail ships **no** stock generic-OIDC/master-user plugin.
- **Hard prerequisite (do FIRST): identity coherence.** Authentik
  `preferred_username` is **user-chosen at enrollment** (`40-enrollment-flow.yaml.j2`
  has a `type: username` prompt), while the Stalwart mailbox is minted as
  `<email-localpart>@<tenant_domain>` (`StalwartProvisioner::createMailbox`). They
  diverge → the header maps to the wrong mailbox or none. **Until one canonical
  username flows through enrollment → forward_auth header → Stalwart principal,
  nothing below can be trusted.**
- **Security: the master-user header trust is a full impersonation bypass if the
  trusted header is not IP-restricted to the Traefik/embedded-outpost source.** A
  request that reaches SnappyMail with a forged `X-authentik-username` would log in
  as anyone. Non-negotiable: restrict by source IP + only trust the header on the
  authentik@file-gated route.

## Build sequence (each step gated, with its own verify)

**Step 0 — Identity coherence (the blocker).** Make the enrollment username
deterministic and equal to the mailbox local-part: pre-seed the invitation's
`fixed_data`/`prompt_data` with `username = <localpart>` and make the
`40-enrollment-flow.yaml.j2` username prompt read-only/hidden; OR set Stalwart
`claimUsername=email` + create the mailbox principal = the full Authentik email,
and pin the Authentik email to `<localpart>@<tenant_domain>`. Verify: a freshly
invited user's `preferred_username` == their Stalwart principal `name`.

**Step 1 — Stalwart master-user account.** Provision a `mailproxy@<tenant>` account
with a Role carrying the `impersonate` permission (Stalwart admin API / config),
secret vaulted in `credentials.yml` (`{{ global_password_prefix }}_pw_mailproxy`).
Verify: `imap` login `someuser%mailproxy@<tenant>` with the proxy password opens
someuser's mailbox; a plain desktop MUA PLAIN login still works (additive proof).

**Step 2 — SnappyMail master-user plugin + domain config.** Add a custom
`nos-proxyauth` plugin to `roles/pazny.snappymail/` (adapt the mundhenk.org
SnappyMail-SSO Dovecot reference to Stalwart's `%` separator): reads
`X-authentik-username` (lowercased), logs in via the `mailproxy` master credential,
**IP-restricted** to the Traefik/outpost source. Render `domains/<tenant>.json`
(imap `mail.<tenant>:993 SSL`, smtp `:465 SSL`, SASL PLAIN) + `application.ini`
with the plugin enabled, via a new `tasks/post.yml`. Keep the existing
`authentik@file` forward_auth middleware (it supplies the trusted header). Verify:
hitting `webmail.<tenant>` behind the gate opens the mailbox with NO second prompt;
a direct (non-Traefik-source) request with a forged header is REJECTED.

**Step 3 (optional, cleaner long-term) — Roundcube native XOAUTH2.** Roundcube 1.6
does a real OIDC code-flow itself (bypassing forward_auth). Flip
`apps/roundcube.yml` `authentik.mode: forward_auth → native_oidc` (an Authentik
OAuth2 provider, redirect `https://roundcube.apps.<tenant>/index.php/login/oauth`),
DROP the forward_auth middleware on that route (forward_auth + native OIDC =
double login), seed `config.docker.inc.php` into the mounted `rcube_config` with
`oauth_provider=generic` + the Authentik auth/token/userinfo URIs +
`imap_auth_type=XOAUTH2`. **Gated on Stalwart's OIDC directory (Step 4) being live
AND PLAIN-coexistence verified** — the public docs do NOT confirm app-passwords
stay locally-validated while the active directory is external OIDC, so this needs a
live wet-test before shipping.

**Step 4 (only if Step 3 is pursued) — Stalwart OIDC directory.** Add an `Oidc`
Directory object (issuer `https://auth.<tenant>/application/o/<slug>/`,
`requireAudience=nos-stalwart-mail`, `claimUsername=preferred_username`) for the
mail domain. RISK: setting a domain's `directoryId` to OIDC routes that domain's
PLAIN logins to the OIDC directory → can kill desktop-MUA PLAIN. Stalwart's
documented fallback is per-user **App Passwords**; whether those stay valid under
an active external-OIDC directory is UNVERIFIED on 0.16.6 — wet-test or don't ship.

## Gates

- `test_webmail_master_user_ip_restricted.py` — the SnappyMail proxyauth plugin
  config MUST carry a source-IP restriction (no open impersonation).
- `test_enrollment_username_deterministic.py` — enrollment forces username =
  mailbox local-part (Step 0).
- `test_stalwart_oauthbearer_keeps_plain.py` — if Step 4 ships, PLAIN stays enabled.

## Why this is NOT in the v0.7 verification run

Webmail IMAP SSO is the single hardest SSO integration in the fleet (the codebase
deferred it for real reasons). It is greenfield (unprovisioned Stalwart config,
unconfigured SnappyMail, a custom security-sensitive plugin), it has a load-bearing
prerequisite (identity coherence), and the impersonation-bypass risk means it MUST
have its own wet-test — a half-working version is worse than none. Ship it as a
focused, sequenced effort with the proof above; do not fold it into the v0.7 tag
run alongside the (done, verified) tofu / Portainer / Hermes / Kuma / NC fixes.

Sources: Stalwart OIDC + impersonate docs, Authentik proxy header-auth docs,
SnappyMail SSO master-user reference, Roundcube OAuth2 wiki (see the 2026-06-15
research pass).
