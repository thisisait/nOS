# Vaultwarden — Skills

> Callable actions for Vaultwarden (Bitwarden-compatible API).
>
> **Scope warning:** the two cipher/organisation skills below were written against the
> Bitwarden API shape, but nOS provisions **no agent identity** for Vaultwarden and vault
> items are **end-to-end encrypted** — an authenticated caller receives ciphertext it cannot
> decrypt without the user's master-password-derived key. They are kept here as the API
> surface of record, flagged as **not usable by an agent as written**. Do not build a skill
> chain on them.

## Authentication

- **Method:** Bearer token from the Bitwarden identity flow
  (`POST /identity/connect/token`), obtained with a real user's credentials — or, for the
  admin plane, `vaultwarden_admin_token` = `{global_password_prefix}_pw_vaultwarden_admin`
  against `/admin` (stored in `~/.nos/secrets.yml`).
- **No pre-issued token file:** `~/agents/tokens/vaultwarden.token` does not exist and no
  `openclaw-bot` account is created; that pairing is a convention in
  `files/openclaw/AGENTS.md` that nothing provisions.
- **Base URL:** `https://{vaultwarden_domain}` (default `https://pass.dev.local`), or
  `http://127.0.0.1:8062` from the host (loopback publish, plain HTTP).
- **Header:** `Authorization: Bearer <token>`

---

## list-vaults

**Trigger:** "list vaults", "show organizations", "what vaults exist"
**Method:** API
**Endpoint:** `GET /api/organizations`
**Input:** None
**Output:** `{ "data": [{ "id": "...", "name": "...", "object": "organization" }] }`

**Status: NOT AGENT-USABLE.** Requires a logged-in user session; nOS provisions no agent
account for Vaultwarden.

---

## get-item

**Trigger:** "get password for", "find login for", "show vault item"
**Method:** API
**Endpoint:** `GET /api/ciphers/<id>`
**Input:** Cipher ID
**Output:** `{ "id": "...", "name": "...", "login": { "username": "...", "password": "..." }, "type": 1 }`

**Status: NOT AGENT-USABLE.** The response fields are ciphertext. Decryption needs the
user's master-password-derived key, which never leaves the client — this is the zero-knowledge
model, not a missing permission. For agent-reachable secrets use **Infisical**
(`docs/systems/infisical/`), which is the infrastructure vault; Vaultwarden is the *personal*
vault by design.
