# MikoPBX

> The estate's phone system: Asterisk 22 packaged as MikoPBX (GPL-3.0). Extensions, SIP trunks, voicemail, recordings, CDR. Replaces the dead FreePBX role.

## Quick Reference

| | |
|---|---|
| **URL** | `https://pbx{host_alias_seg}.{tenant_domain}` (default `https://pbx.dev.local`) |
| **Port** | `8088` (`mikopbx_port`; loopback publish → container `80`) |
| **SIP** | `5060/udp+tcp` (`mikopbx_sip_port`), RTP `10000-10100/udp` (`mikopbx_rtp_start/_end`) |
| **Stack** | `voip` |
| **Toggle** | `install_mikopbx: false` (default OFF) |
| **Compose** | `~/stacks/voip/docker-compose.yml` (role fragment: `~/stacks/voip/overrides/mikopbx.yml`) |
| **Image** | `mikopbx/mikopbx:2026.3.40` (`mikopbx_version`; multi-arch, Asterisk 22.8.2 inside) |
| **DB** | none in infra — SQLite + Redis live inside the container (`/cf`) |
| **Data** | `mikopbx_data_dir/{cf,storage}` — config+SQLite, recordings/voicemail |
| **Admin** | login `admin`, password `nos_derived_secrets.mikopbx_admin` (`tools/nos-secret.py mikopbx_admin`) |

## Authentication — single login, stated plainly

`forward_auth`. Authentik gates the Traefik route; behind the gate MikoPBX
still asks for its own admin password. That is the ceiling MikoPBX sets
today, proven from `mikopbx/Core` source (2026-10-03):

| Path | Verdict | Where it is decided |
|---|---|---|
| OIDC / SAML in core | not supported | no handler in `src/AdminCabinet`, `src/PBXCoreREST`; no MIKO module |
| Header / trusted-proxy (Remote-User) | not supported | `PBXCoreREST/Http/Request.php::getBearerToken()` reads `Authorization: Bearer` and `X-Api-Key` only; `AdminCabinet/Plugins/SecurityPlugin.php` trusts `REMOTE_ADDR==127.0.0.1` only |
| LDAP login (Authentik LDAP outpost) | paid `ModuleUsersUI` — bind-auth, no group check | `Lib/UsersUILdapAuth.php` |
| API-minted session | only via core's one-time `sessionToken` (`Lib/Auth/LoginAction.php::authenticateWithSessionToken`), which needs code running inside the box | — |
| Community OIDC module | `davidjaksa/ModuleAuthentikSSO` (GPL, v1.0.5, one author, one commit) rides the sessionToken path; everyone becomes `admins` | opt-in follow-up, after review |

An Authentik LDAP outpost does not exist in nOS and would only buy a second
password prompt via a paid module, so none is prepared. The localhost bypass
(`REMOTE_ADDR==127.0.0.1` → no auth) is deliberately NOT used as "auto-login":
it keys on source address, not identity, and Traefik reaches the container
over the bridge anyway.

Phones never see Authentik: SIP is digest auth per extension (number + secret).

## Real calls behind Docker Desktop (macOS) — what was measured

Throwaway container `mikopbx/mikopbx:2026.3.40`, bridge mode, ports published
on 127.0.0.1 (2026-10-03, Docker Desktop 4.89, Apple Silicon):

- boots in 18 s; `GET /pbxcore/api/v3/system:ping` → 200 (public, used as healthcheck).
- SIP REGISTER over the published UDP port → `200 OK` (digest).
- INVITE to the built-in echo test `10003246`: with stock settings the SDP
  answer carries `c=172.17.0.x` (container IP) → no audio. Reason: Docker
  Desktop delivers every published UDP packet from the bridge gateway
  `172.17.0.1`, which is inside Asterisk's `local_net`, so Asterisk treats
  every phone as local and never uses `external_media_address`.
- Fix, all through MikoPBX's own API: `usenat`+`extipaddr=<host LAN IP>`,
  `autoUpdateExternalIp=false` (the env path forces it on and the public IP
  then overwrites the setting on every boot), and a custom-files *script* on
  `/etc/asterisk/pjsip.conf` that drops the `local_net=` lines. After that:
  `c=<host>`, RTP port inside the published range, echo test returned 39/50
  packets through the published UDP ports (the first ~10 are strict-RTP
  learning). Two-way audio through Docker Desktop works.
- `extra_hosts` is useless here: MikoPBX rewrites `/etc/hosts` at boot.
- Ceiling: all phones look like one peer (`172.17.0.1`) to fail2ban/ACLs; a
  changed LAN IP needs a converge (`mikopbx_external_ip` defaults to
  `ansible_facts.default_ipv4.address`). Long-idle UDP flows through Docker
  Desktop have known timeouts (docker/for-mac#7346, #7555): keep SIP
  registration expiry short (MikoPBX default 120 s).

Ubuntu 24.04: same bridge wiring works natively (no proxy rewrite);
`network_mode: host` is upstream's recommendation but breaks the Traefik /
shared-network shape, so bridge stays the one shape on both platforms.

## Provisioning (`roles/pazny.mikopbx/tasks/post.yml`)

Env vars land on FIRST boot only; every converge re-asserts through REST v3
with a JWT from the derived admin password (an API key cannot be derived —
MikoPBX generates it and stores a bcrypt hash):

1. `PATCH /general-settings` — RTP range, external SIP port, auto-external-IP off.
2. `POST /network:saveConfig` — NAT on, `extipaddr = mikopbx_external_ip`.
3. macOS only: `PUT /custom-files/{pjsip.conf}` script mode (`roles/pazny.mikopbx/files/pjsip-no-local-net.sh`).
4. `POST /employees` for each `mikopbx_extensions` row missing; secret =
   row's `secret` or `sha256(nos_derived_secrets.mikopbx_sip:number)[:24]`
   (read it in the UI → Employees).
5. `POST /sip-providers` for each `mikopbx_providers` row missing.
6. Read back employees / providers / NAT; `docker exec` the loaded
   `rtp.conf` + pjsip transport; restart once if the first-boot ordering
   left them stale (measured); assert — that is the success marker.

The image ships three demo employees (201–203). They are left alone;
declare your own numbers outside that range or delete them in the UI.

```yaml
# config.yml
install_mikopbx: true
mikopbx_lan_access: true          # SIP/RTP on 0.0.0.0 so LAN phones can reach it
mikopbx_extensions:
  - { number: "301", name: "Alice", email: "alice@example.com" }
mikopbx_providers:
  - { name: "provider", host: "sip.provider.example", username: "u", secret: "s" }
```

## Operations

- Enable live: `tools/nos-stacks.sh mikopbx` (or `ansible-playbook main.yml
  --tags "authentik,anatomy,mikopbx"` so the Authentik provider is applied by
  tofu before the route is gated), then `tools/e2e-plan.py` probes.
- Health: compose healthcheck `curl /pbxcore/api/v3/system:ping`; manifest
  `health_check` on the same URL.
- Backup: one source `mikopbx` = `mikopbx_data_dir` (cf/ SQLite config with the
  same torn-window honesty as the other SQLite apps, storage/ recordings +
  voicemail); restore target `mikopbx` in `tasks/restore.yml`.
- Removal: `nos --remove=data` wipes `mikopbx_data_dir` (removal-set clause).
