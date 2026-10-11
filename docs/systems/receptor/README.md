# Receptor

> A host login reaches KEAP's human door as the person it maps to. The kernel
> says which login is calling; the identity map says which person that is.
> Nobody holds a KEAP token for it, and a header the caller sends is dropped.

## Quick Reference

| | |
|---|---|
| **Type** | Host organ (non-Docker), stdlib Python |
| **Socket** | `~/.nos/keap-identity.sock`, mode 0600 (`receptor_socket`) |
| **Toggle** | `install_receptor` (default: on wherever `install_openhuman` is) |
| **Map** | `~/.nos/identity-map.yml` (`nos_identity_map`; `{}` = from the roster) |
| **Manifest id** | `receptor` |
| **launchd label** | `eu.thisisait.nos.receptor` (systemd --user on Linux) |
| **Runtime** | `~/receptor/receptor.py` (copied from source on converge) |
| **Logs** | `~/receptor/log/` |

Values from `roles/pazny.receptor/`, `files/anatomy/receptor/receptor.py`,
`default.config.yml`, `state/manifest.yml`.

## The identity map

One file, rendered by this role, read on every request (a new map needs no
restart). The Thalamus will read the same file. Shape (JSON, which is YAML):

```yaml
{"logins": {"<host login>": {"username": "<Authentik username>", "groups": ["nos-admins"]}}}
```

`nos_identity_map: {}` derives it from the roster: your login is
`nos_primary_admin` with its tier's group, and each `nos_extra_identities`
name is a login of its own name. Set `nos_identity_map` to replace it whole.
A login that is not in the map gets 403. It is never given a default person.

## Who uses it

- **OpenHuman.** Its `nos-tables` MCP server sets
  `KEAP_IDENTITY_URL=http+unix://<socket>` and `NOS_MCP_READ_ONLY=1`.
- **Host tools.** `tools/keap_api.py` and `tools/mcp-tables-server.py` take the
  human door through it when `KEAP_IDENTITY_URL` is set, for reads only.

## What it relays

`GET` and `HEAD` on `/api` paths, nothing else. Any other method gets 405
before KEAP is contacted: OpenHuman is read-only by contract and has a shell,
so the client flag alone does not hold. Approved writes will take the
Thalamus's own proxy-secret path (operator ruling 2026-10-11). A head with a
bare CR or LF, a NUL, a folded line, a non-token header name, two
`Content-Length`s, or a target outside `/api` (or with `..`, `.`, `//`, `\`,
`%2e`/`%2f`/`%5c`) gets 400.

## Holders of the KEAP proxy secret

Traefik, face and the receptor (operator ruling 2026-10-11). On the Mac the
receptor runs as your login, so the secret is in a 0600 plist your own
processes could read. That is the "runs as the user" class
(`ssot/doctrine/session-threat-model.md`); the socket mode keeps other logins out.

## Health

`ansible-playbook main.yml --tags receptor,verify`: the socket is 0600 and
answers your login as a person: `GET /api/me` must be 200. Anything else fails
the play and names the status (403 = map, 503 = no secret, 502 = KEAP down).

Sibling on the Linux DGX bootstrap: `bootstrap/minimal-linux-dgx/identity/keap-identity.py`
(Linux groups instead of a map).
