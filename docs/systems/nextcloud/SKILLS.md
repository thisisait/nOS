# Nextcloud — Skills

> Callable actions for Nextcloud. WebDAV for files, OCS API for shares/users.

## Authentication

- **Method:** Basic auth (App Password)
- **Token:** `~/agents/tokens/nextcloud.token`
- **Base URL:** `https://cloud.dev.local`
- **Required header:** `OCS-APIRequest: true` (for OCS endpoints)

---

## upload-file

**Trigger:** "upload file", "save [file] to cloud", "store document"
**Method:** WebDAV
**Endpoint:** `PUT /remote.php/dav/files/openclaw-bot/{path}`
**Input:** File content as request body
**Output:** `201 Created`

---

## download-file

**Trigger:** "download [file]", "get file from cloud"
**Method:** WebDAV
**Endpoint:** `GET /remote.php/dav/files/openclaw-bot/{path}`
**Input:** File path
**Output:** File content

---

## list-files

**Trigger:** "list files", "show directory contents", "what's in [folder]"
**Method:** WebDAV
**Endpoint:** `PROPFIND /remote.php/dav/files/openclaw-bot/{path}`
**Input:** Depth header (0=file, 1=directory)
**Output:** XML with file/folder metadata

---

## create-share

**Trigger:** "share [file] with [user]", "create share link"
**Method:** API
**Endpoint:** `POST /ocs/v2.php/apps/files_sharing/api/v1/shares`
**Input:** `{ "path": "/file.txt", "shareType": 3, "permissions": 1 }` (3=public link)
**Output:** `{ "url": "https://cloud.dev.local/s/..." }`

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
