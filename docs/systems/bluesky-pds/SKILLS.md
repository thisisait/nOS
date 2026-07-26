# Bluesky PDS — Skills

> Callable actions for Bluesky PDS. Each skill uses AT Protocol XRPC API.

## Authentication

- **Method:** Bearer JWT (AT Protocol session)
- **Base URL:** `http://127.0.0.1:2583` (loopback publish — the reliable path; there is no
  Traefik route and no `pds.<tld>` host). Use `https://{bluesky_pds_hostname}` only where
  that hostname resolves (opt-in nginx vhost, or public DNS + federation).
- **Header:** `Authorization: Bearer <jwt>`
- **Session creation:** `POST /xrpc/com.atproto.server.createSession` with
  `{ "identifier": "<handle>", "password": "..." }` — e.g. the admin handle
  `bluesky_pds_admin_handle` (default `pazny.bsky.dev.lan`) plus
  `bluesky_pds_admin_password` (`{global_password_prefix}_pw_bluesky`), or a
  bridge-provisioned `<username>.{bluesky_pds_hostname}` account.
  There is no pre-issued token file and no `openclaw-bot` account; that pairing is a
  convention in `files/openclaw/AGENTS.md` that nothing provisions.

---

## create-post

**Trigger:** "post to bluesky", "create post", "publish update"
**Method:** API
**Endpoint:** `POST /xrpc/com.atproto.repo.createRecord`
**Input:**
```json
{
  "repo": "<did>",
  "collection": "app.bsky.feed.post",
  "record": {
    "$type": "app.bsky.feed.post",
    "text": "<post text>",
    "createdAt": "<ISO timestamp>"
  }
}
```
**Output:** `{ "uri": "at://...", "cid": "..." }`

---

## list-feed

**Trigger:** "show feed", "list recent posts", "what has been posted"
**Method:** API
**Endpoint:** `GET /xrpc/app.bsky.feed.getAuthorFeed`
**Input:** Query params: `actor` (DID or handle), `limit` (optional)
**Output:** `{ "feed": [{ "post": { "uri": "...", "record": { "text": "..." }, "author": {...} } }] }`

---

## get-profile

**Trigger:** "show profile", "get account info", "who am I"
**Method:** API
**Endpoint:** `GET /xrpc/app.bsky.actor.getProfile`
**Input:** Query params: `actor` (DID or handle)
**Output:** `{ "did": "...", "handle": "...", "displayName": "...", "description": "...", "followersCount": 0 }`

---

## manage-account

**Trigger:** "update profile", "change handle", "account settings"
**Method:** API
**Endpoint:** `POST /xrpc/com.atproto.server.updateEmail` (email), `POST /xrpc/com.atproto.identity.updateHandle` (handle)
**Input:** Depends on operation
**Output:** `200 OK` on success
