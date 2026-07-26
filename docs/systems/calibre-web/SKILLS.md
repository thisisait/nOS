# Calibre-Web — Skills

> Callable actions for Calibre-Web. No REST API — uses the `calibredb` CLI (through
> `docker compose exec`) and the OPDS feed.

## Authentication

- **Method:** N/A (CLI via `docker compose exec`; OPDS sits behind the Authentik forward-auth gate)
- **Container:** `iiab-calibre-web-1` (compose service `calibre-web`, project `iiab`)
- **Exec user:** `abc` (the image's PUID user — the library is owned by it)
- **Library path:** `/books` — every `calibredb` call must pass `--library-path /books`
- **OPDS URL:** `https://books{host_alias_seg}.{tenant_domain}/opds`

---

## search-books

**Trigger:** "search books", "find book", "look up author"
**Method:** CLI
**Command:** `docker compose -p iiab exec -T -u abc calibre-web calibredb search "<query>" --library-path /books`
**Input:** Search query (title, author, tag)
**Output:** List of matching book IDs

**Alternative (OPDS):**
**Endpoint:** `GET /opds/search?query=<query>`
**Output:** Atom XML feed with matching books

---

## get-book-info

**Trigger:** "book details", "show book info", "what is book [id]"
**Method:** CLI
**Command:** `docker compose -p iiab exec -T -u abc calibre-web calibredb show_metadata <book-id> --library-path /books`
**Input:** Book ID
**Output:** Book metadata (title, author, publisher, tags, format, description)
