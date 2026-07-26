# Kiwix — Skills

> Callable actions for Kiwix. Read-only API with no app-level authentication; the public route is
> gated by Authentik forward-auth, the host loopback port is not.

## Authentication

- **Method:** None inside the service. The FQDN route sits behind the `authentik@file` forward-auth
  middleware (a valid Authentik session is required); `http://127.0.0.1:8888` bypasses it and is
  reachable only from the host.
- **Base URL:** `https://kiwix{host_alias_seg}.{tenant_domain}` (default `https://kiwix.dev.local`)

---

## search-content

**Trigger:** "search Wikipedia", "find article", "look up [topic]", "search offline"
**Method:** API
**Endpoint:** `GET /search?pattern=<query>&books=<book-name>`
**Input:** Query params: `pattern` (search query), `books` (optional, ZIM library name), `pageLength` (optional)
**Output:** HTML search results page with matching articles

**Example:**
```
"Search for Prague in offline Wikipedia"
GET /search?pattern=Prague&books=wikipedia
```

**When** a blank run has only seeded the demo archive, the only `books` value that resolves is
`alpinelinux` — a `books=wikipedia` query returns nothing until the operator downloads a Wikipedia ZIM.

---

## list-libraries

**Trigger:** "list libraries", "what content is available", "show ZIM files"
**Method:** API
**Endpoint:** `GET /catalog/search`
**Input:** None
**Output:** OPDS Atom feed listing available ZIM content libraries with titles, descriptions, and sizes
