# freepbx-base

Wiring layer for `pazny.freepbx` — the FreePBX + Asterisk PBX that lives in
the `voip` compose stack. The plugin declares the role binding, GDPR
Article 30 row, observability labels, and a Wing `/hub` deep-link card; it
emits no `authentik:` block because FreePBX is intentionally outside the
SSO trichotomy (per CLAUDE.md "No SSO: FreePBX"). Voice protocols
(SIP/IAX/RTP) can't trampoline through OAuth, and the admin webUI uses
its own PHP session auth — wrapping it in forward-auth would break
soft-phone registration without adding security. The plugin activates
whenever `install_freepbx: true` flips the voip stack on; the loader's
`post_compose` hook polls the admin webUI on `freepbx_port` (default
8088) until it responds with any 2xx/3xx/4xx (FreePBX redirects `/` to
`/admin`).
