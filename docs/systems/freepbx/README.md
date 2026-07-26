# FreePBX

> FreePBX + Asterisk — the telephony control surface. Configures extensions,
> trunks, dial plans and call detail records: real phone calls, not chat.

## Quick Reference

| | |
|---|---|
| **URL** | `https://pbx.<tenant_domain>` (local default `https://pbx.dev.local`) |
| **Web UI port** | `8088` (bound `127.0.0.1:8088` → container `80`) |
| **SIP** | `5060/udp` + `5060/tcp` (loopback unless `freepbx_lan_access`/`services_lan_access: true`) |
| **IAX2** | `4569/udp` · **RTP media** | `10000-10100/udp` |
| **Stack** | `voip` (taxonomy anchor `nos.voip.freepbx`) |
| **Toggle** | `install_freepbx: true` (default `false`) |
| **Image** | `tiredofit/freepbx:latest` |
| **Data** | `{{ nos_data_root }}/platform/services/freepbx/data` (mounts `/certs`, `/data`, `/logs`, `/custom`) |
| **SSO** | **None** — self-managed webUI session; no Authentik block |

`nos_data_root` defaults to `~/nos`; the segment `platform/services/freepbx/data`
is constant. Voice protocols cannot trampoline through OAuth, so the PBX is
deliberately outside the SSO trichotomy — end-user identity is the Asterisk
extension number, not an Authentik subject. The Tier-1 admin webUI is reachable
via the Traefik file-provider router with **no** forward-auth middleware.

> **Vendor-blocked image.** `tiredofit/freepbx` was abandoned upstream
> (2022-04-30). CRITICAL CVEs are unfixable in this image (REM-014 / 046 / 113);
> operators accept the risk. FreePBX is excluded from the all-on test profile —
> enable it only for a supervised run.

## Authentication

- **Web UI admin:** `admin` / password **set during the first-boot wizard** (no
  default admin password is provisioned by the playbook).
- **Database:** MariaDB, DB `asterisk`, user `asterisk`, password
  `{global_password_prefix}_pw_freepbx` (`freepbx_db_password`).
- **SIP/IAX endpoints:** authenticate with per-extension secrets (hashed in the
  `asterisk` DB), not with Authentik.

## Health Check

- **Endpoint:** `GET /` → `302` redirect to `/admin` (the webUI landing).
- The plugin `wait_health` accepts any 2xx/3xx/4xx as healthy (the redirect is expected).

## Dependencies

- MariaDB (the `asterisk` dialplan/extension database) — hard dependency.
- Timezone `Europe/Prague` (`freepbx_timezone`), `fail2ban` enabled in-container.
