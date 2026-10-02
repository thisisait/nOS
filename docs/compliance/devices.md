# Devices — what they are and what data may exist

**Status:** CONFIRMED by the operator, 2026-10-02 (all seven decisions below,
as written). Change a number here AND in the register row
(`files/anatomy/plugins/device-gateway-base/plugin.yml`); the gate ties the two.

Grounded in what the code stores today. Pinned by
`tests/anatomy/test_device_gateway_art30.py`.

## 1. What a "device" is in nOS

Two nouns exist. They share a word and nothing else.

| Noun | Table | What it is | Policy |
|---|---|---|---|
| **Device client** | `device-client` | A handheld, phone or wearable that **calls** nOS through the device gateway (`device.<tld>`) with the user's own Authentik token. | This document. |
| **Digest device** | `device` + `device-extraction` | A physical unit the operator **owns and backs up**; a parse of that backup. | `docs/plans/digest-device-doctrine.md` (consent, Art. 9, deny-by-default profile, retention until consent withdrawn). |

Supported device-client kinds are exactly the table enum: `handheld`, `phone`,
`wearable`. Sensors, IoT nodes, MQTT publishers and voice clients are **not**
devices under this policy until the enum grows and this page is amended.

The **ear** (`roles/pazny.ears`, the Mac's own microphone) is not a device
client. It is a host organ; audio is never stored, transcripts live 90 days in
`~/ears/turns/`. It has **no Art-30 row today** — named here so it is not
mistaken for covered. (Finding, out of scope for this page.)

What a device client can do today: `GET /health`, `GET /manifest`,
`GET /tables/<id>` for six allowlisted, column-projected KEAP tables
(roadmap, current-state, todos-akadmin, repo, application, package).
No push, no upload, no write. A guest- or user-tier account is refused (403):
only manager tier and above can pair today — **CONFIRMED 2026-10-02** that this stays until
per-device revocation (`device-pairing`) ships.

## 2. Data that may exist, per place

| Where | Fields | Purpose | Basis | Retention |
|---|---|---|---|---|
| `device-client` row (KEAP) | `slug`, `type`, `owner` (Authentik username), `fingerprint` (**hash**), `scopes`, `paired_at`, `last_seen` (**day precision**, overwritten), `status`, `revoked_at` | know which device belongs to whom, revoke it | contract, Art. 6(1)(b) — **CONFIRMED 2026-10-02** | until unpair, then **30 days** after `revoked_at` — **CONFIRMED 2026-10-02** |
| Authentik (infra) | device-code grant, access token, refresh token | authenticate the device | contract | access **10 min**, refresh **30 days**, rotates on every use — **CONFIRMED 2026-10-02** |
| Traefik access log → Loki | client IP, path, status, user agent (no headers, no bodies) | security, debugging | legitimate interest (estate log, `svc_loki`) | `loki_retention`, **31 days** — **CONFIRMED 2026-10-02** |
| Gateway process | 30-second in-memory row cache | performance | — | not persisted |

Today the registry holds **zero rows**: nothing writes `device-client` yet
(pairing runtime is dtt `device-pairing`, queued). The only live per-device
state is the Authentik token.

## 3. Never stored

- Raw hardware identifiers: serial, IMEI, UDID, MAC, advertising id. Hash only.
- Location, GPS traces, cell or Wi-Fi positioning.
- Audio, voice recordings, transcripts of a device's microphone.
- Message content, contacts, photos, health or biometric data (Art. 9).
- The bearer token itself, request bodies, `Authorization` headers in any log.
- Per-request history of a device (`last_seen` is one overwritten day, not a trail).

A column named like any of these on `device-client` fails the gate.

## 4. Subjects, processors, residency

- **Subjects:** every nOS account holder who pairs a device (`end_users`); operators.
- **Processors:** none. Gateway, KEAP, Authentik and Loki run on this host.
- **EU residency:** yes; no transfer outside the EU. If the tenant domain is
  fronted by a CDN edge, that edge sees the TLS endpoint and must be declared
  as a processor before the gateway is exposed through it — **CONFIRMED 2026-10-02** n/a.

## 5. Unpair, leave, DSAR

- **Unpair (user):** set `status=revoked` + `revoked_at` on the row, revoke the
  user's `nos-device-gateway` tokens in Authentik. Today: manual (no runtime).
  Target (`device-pairing`): one action does both and the gateway refuses the
  old refresh token.
- **Leave / erasure (Art. 17):** `tasks/gdpr-forget.yml` deletes the Authentik
  user, which kills every grant; the `svc_device-gateway` entry in
  `state/gdpr-erasure-map.yml` names the KEAP row delete (manual).
- **Access (Art. 15):** `svc_device-gateway` in `state/gdpr-export-map.yml`:
  the subject's rows by `owner` + their token list in Authentik.
- **Retention:** **not enforced by a job yet** (`retention_enforced: false` in
  the register note). The gate demands a Pulse job `device-client-retention`
  the moment any code writes `device-client` rows.

## 6. Security floor

- Gateway binds `127.0.0.1`; only Traefik reaches it; TLS at the edge.
- Every request: bearer → Authentik userinfo (verified) → `azp`/`aud` must be
  `nos-device-gateway` → a tier-2 group must be present. Fail closed.
- Allowlist first: PII and financial tables (`invoice`, `party`,
  `journal-entry`, `account`, `kolben-*`) are 403 before KEAP is called.
- Pairing secret = the refresh token. It rotates on every use; idle 30 days
  → the device must pair again. Revocation = Authentik token revoke.
- `GATEWAY_TOKEN` (host curl escape) is dead on a converged estate: the plist
  always sets `AUTHENTIK_USERINFO_URL`, which takes the branch first.
- Before any tier below manager is admitted: per-device revocation and a
  scope model (`device-scopes`) must exist. **CONFIRMED 2026-10-02** this ordering.

## 7. Where the code and the policy disagree today

- `last_seen` is declared `text` with no precision; the policy says day
  precision. Enforced only once a writer exists.
- No writer, no retention job, no consent/contract record beyond the Authentik
  grant (the authorization flow is implicit-consent, so Authentik keeps no
  consent object). The register says so rather than claiming otherwise.
