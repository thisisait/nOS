# Puter + the KEAP document-flow bridge — investigation & incremental plan

> Deep investigation 2026-07-18 (upstream Puter + nOS impl). Supersedes the
> `fs-doctrine.md` phrasing "Puter mounts the user's `documents/`; euro-office
> edits the same files" — that is **infeasible** against upstream Puter (see §Verdict).

## Load-bearing finding: Puter is a class-1 engine, not a class-3 FS surface

Puter's per-user filesystem is **DB metadata + opaque UUID-keyed blobs**, NOT real
files at real paths:
- **Tree/metadata** (path, owner, uuid) lives in **SQLite** (`/var/puter/puter-database.sqlite`,
  `fsentries` table). Every path resolves by DB lookup to a UUID.
- **Content** is an opaque blob keyed by internal id — local "faux-S3" driver in
  nOS (`/var/puter/fauxqs-*`), or RustFS/S3 in distributed mode.
- So `Documents/report.docx` is a **DB row → UUID blob**; there is **no real file**
  at `.../users/<uid>/documents/report.docx`. Repointing Puter's storage root at the
  per-user tree deposits UUID blobs, not readable documents.
- Puter's only first-class real-file export is its **WebDAV** service.

**Verdict:** Puter's VFS **cannot be bind-bridged** to the KEAP-watched per-user tree
(KEAP `server/fs-sync.ts` needs real files at `<uid>/<top>/<realpath>` — it hashes the
relPath into the object id and reads the file body). The KEAP document flow must ride a
**real-file surface**:
- **Recommended: Nextcloud as the class-3 document producer** — it stores real files;
  point its per-user data at `tenants/<t>/users/<uid>/documents/` (KEAP already mounts
  `tenants/<slug>/users:/user-files:ro`). Puter stays the desktop shell (Nextcloud iframe
  app). **KEAP needs no change.**
- **If Puter must produce docs:** a one-way WebDAV/FSEntry **materializer** Pulse job that
  renders each user's Puter `Documents` into the per-user tree as real files (sync, not
  mount) + an Authentik-uid ↔ Puter-username map.

**Doctrine correction to make:** `docs/doctrine/filesystem.md` / `fs-doctrine.md` — Puter
is class-1 (internal multi-user over one DB+object store); the class-3 document producer
feeding KEAP is a **real-file** service (Nextcloud), not Puter.

## nOS implementation (summary)

Built from source: `files/puter/Dockerfile` `FROM ghcr.io/heyputer/puter:latest`
(**unpinned** — reproducibility gap), local tag `nos/puter:v2.5.1`. Six `find`/`sed`/`node`
patches (CSS, CORS `Allow-Credentials`, Socket.IO CORS, cookie `domain=.<tld>` for os↔api,
recommended-apps, disable camera) — each **skips with only a WARNING if its needle is
missing** (latent auth bug on upstream drift). Loopback `127.0.0.1:5050→4100`; SSO =
`forward_auth` only (no header-provisioning of Puter users from `X-Authentik-*`); Traefik
file-provider makes **exactly one** router `Host(os.<tld>)→4100` — **no `api.os.<tld>`
router**. Puter data is filed **class-1** (`platform/services/puter/data`).

## The 404 (`{"error":"Not Found","code":"not_found"}`) — refined diagnosis

Live checks 2026-07-18: `os.pazny.eu`→302, GUI serves; loopback `Host=os.pazny.eu /whoami`
→ **404** (GUI host doesn't serve the API), `Host=api.os.pazny.eu /whoami` → **401**
(API host DOES serve it); `api.os.pazny.eu` **via Traefik → 404** (no router). The admin
user **HAS a filesystem root** (10 fsentries incl. Desktop/Documents) — so the "missing
FS root" hypothesis is **disproven**. Root cause is the **API-host routing / frontend
API-target**: after login the GUI's API XHR does not reach Puter's API handler —
either the frontend targets `api.os.<tld>` (no Traefik route → 404) or targets the GUI
host (Puter 404s API paths there). Aggravated by (a) no `api.` Traefik route, (b) possible
silently-skipped cookie/CORS Dockerfile patch on the unpinned base image.

## Incremental improvements (ordered, each independently shippable)

1. **[S] Pin the upstream base image + fail-loud patches** — `FROM …@sha256:` (or a real
   tag); the 6 Dockerfile patches HARD-FAIL on a missing needle (a silently-skipped
   cookie/CORS patch is a real auth bug). De-risks everything below. `files/puter/Dockerfile`.
2. **[S–M] Route `api.os.<tld>` (or Puter no-subdomain mode)** — add the API-host Traefik
   route to `:4100` **without** `authentik@file` (forward-auth breaks XHR — the API uses
   Puter's own cookie); `*.<tld>` dnsmasq already resolves. **TLS caveat:** an LE
   `*.<tld>` wildcard does NOT cover `api.os.<tld>` (deeper level) — needs a `*.os.<tld>`
   cert or Puter's no-subdomain mode (upstream #2770). Verify the cookie-domain patch
   applied. `roles/pazny.traefik/*`, `templates/puter/config.json.j2`.
3. **[S] Deeper Puter health probe** — authenticated `/whoami` or admin-home `readdir`, so
   the 404-after-auth state fails the STRICT gate instead of shipping green (Puter is on
   the health-blind allowlist today). `compose.yml.j2` / `puter-base` plugin.
4. **[L] Document-flow bridge = Nextcloud as class-3 producer** (centerpiece) — point
   Nextcloud per-user data at `tenants/<t>/users/<uid>/documents/`; KEAP already watches
   it RO. Expose Nextcloud inside Puter as an iframe app. Zero KEAP change.
5. **[M–L] euro-office on the real-file surface** — wire OnlyOffice/euro-office to
   Nextcloud (existing integration + the euro-office fork already supported); Puter iframe
   → Nextcloud → euro-office → save → real file in the per-user tree → KEAP ingests.
6. **[M] Isolation/RBAC + uid map** — class-3 per-uid `0700` keyed by `X-Authentik-uid`;
   Puter usernames ≠ Authentik uids (forward_auth doesn't provision), so any materializer
   needs an explicit map. macOS = structure-only; Linux = real uids.
7. **[S] Reproducibility** — the `puter_version` pin only names the LOCAL tag; the real
   pin is the Dockerfile `FROM` (see #1).

## Sources

Puter GitHub (HeyPuter/puter), DeepWiki filesystem-architecture + deployment, Puter
self-hosters wiki, issues #784/#251/#287/#221/#2770/#580/#696, Puter docs/developer.
Full URLs in the 2026-07-18 research transcript.
