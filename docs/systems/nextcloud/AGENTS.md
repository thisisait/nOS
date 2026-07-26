# Nextcloud — Agent Definition

## StorageAgent (Nextcloud)

**System:** Nextcloud (iiab stack) — files, sharing, calendar, contacts.
**Domain:** `cloud{host_alias_seg}.{tenant_domain}` (default `cloud.dev.local`).
**Role:** File and collaboration store, addressable over WebDAV and the OCS API — with
an operator-generated App Password, not a provisioned agent identity.

### Context

- OCS API: `https://{nextcloud_domain}/ocs/v2.php/` (header `OCS-APIRequest: true`)
- WebDAV: `https://{nextcloud_domain}/remote.php/dav/`
- **Auth: an App Password the operator generates in Settings → Security for a real
  account.** nOS provisions no service account and writes no token file.
- Human access is `native_oidc` (Authentik client `nos-nextcloud`, RBAC tier 3),
  configured via `occ user_oidc` post-up — not via compose env.
- Storage split: `/var/www/html` ← `~/projects/nextcloud` (app + `config.php`),
  `/data` ← `{{ nos_data_root }}/tenants/{{ nos_tenant_slug }}/shared/nextcloud/data`
  (user files); metadata, shares and users live in the MariaDB `nextcloud` schema.
- CLI fallback (authoritative, playbook-used):
  `docker compose -p iiab exec -T -u www-data nextcloud php occ <cmd>`

### Capabilities

Reachable once an App Password exists — all of these are real Nextcloud endpoints:

- Upload, download, and manage files (WebDAV)
- Create and manage shares (links, users, groups)
- Search files by name or content
- Manage users and groups (OCS provisioning API)
- Access calendar and contacts (CalDAV / CardDAV under `/remote.php/dav/`)
- Read storage quota

### Credential caveat

There is no playbook-managed agent credential. The only account nOS creates is the
`admin` operator login (`nextcloud_admin_user` /
`{global_password_prefix}_pw_nextcloud_admin`); every other user arrives through
Authentik OIDC. An agent needs a human to mint an App Password first — treat the
capability list above as "possible", not "already wired".

### Skills Reference

See [SKILLS.md](SKILLS.md) for the callable actions and their real path shapes.
