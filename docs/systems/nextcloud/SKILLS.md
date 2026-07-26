# Nextcloud — Skills

> Callable actions for Nextcloud. WebDAV for files, OCS API for shares/users. The
> endpoints are real; the credential is NOT provisioned by nOS — read the access model
> before treating any card below as wired.

## Authentication

- **Method:** Basic auth (App Password) — human-minted, NOT provisioned by nOS
- **Where the password comes from:** a human generates it in Settings → Security for a
  real account. Substitute that account name for `{user}` in every WebDAV path below.
- **No service account.** `openclaw-bot` does not exist. Nothing in the repo creates a
  Nextcloud user beyond the `admin` operator account; every other user arrives through
  Authentik OIDC (`occ user_oidc`).
- **No token file.** `~/agents/tokens/nextcloud.token` does not exist. No task writes it
  and no code reads it.
- **Base URL:** `https://{nextcloud_domain}` (default `https://cloud.dev.local`), or
  `http://127.0.0.1:8085` from the host (loopback publish; peer containers cannot reach
  it).
- **Required header:** `OCS-APIRequest: true` for every `/ocs/` endpoint.
- **Authoritative admin path is `occ`, not HTTP:**
  `docker compose -p iiab exec -T -u www-data nextcloud php occ <cmd>`.

---

## upload-file

**Trigger:** "upload file", "save [file] to cloud", "store document"
**Method:** WebDAV
**Endpoint:** `PUT /remote.php/dav/files/{user}/{path}`
**Input:** File content as request body
**Output:** `201 Created`

---

## download-file

**Trigger:** "download [file]", "get file from cloud"
**Method:** WebDAV
**Endpoint:** `GET /remote.php/dav/files/{user}/{path}`
**Input:** File path
**Output:** File content

---

## list-files

**Trigger:** "list files", "show directory contents", "what's in [folder]"
**Method:** WebDAV
**Endpoint:** `PROPFIND /remote.php/dav/files/{user}/{path}`
**Input:** Depth header (0=file, 1=directory)
**Output:** XML with file/folder metadata

---

## create-share

**Trigger:** "share [file] with [user]", "create share link"
**Method:** API
**Endpoint:** `POST /ocs/v2.php/apps/files_sharing/api/v1/shares`
**Input:** `{ "path": "/file.txt", "shareType": 3, "permissions": 1 }` (3=public link)
**Output:** `{ "url": "https://{nextcloud_domain}/s/..." }`

---

## search-files

**Trigger:** "find files named [query]", "search cloud for [term]"
**Method:** API
**Endpoint:** `SEARCH /remote.php/dav/`
**Input:** WebDAV SEARCH XML body
**Output:** Matching files with metadata

---

## get-user-info

**Trigger:** "cloud storage usage", "who uses most space"
**Method:** API
**Endpoint:** `GET /ocs/v2.php/cloud/users/{userId}`
**Input:** User ID
**Output:** `{ "quota": { "used": ..., "total": ..., "relative": ... } }`

---

## Notes

- Files written through WebDAV land under
  `{{ nos_data_root }}/tenants/{{ nos_tenant_slug }}/shared/nextcloud/data` on the host
  (default `~/nos/tenants/dev/shared/nextcloud/data`). The app tree at
  `~/projects/nextcloud` is config, not user data — do not confuse the two when
  inspecting or backing up.
- Share and user metadata is in the MariaDB `nextcloud` schema, not on disk. A filesystem
  copy alone is not a restorable backup.
