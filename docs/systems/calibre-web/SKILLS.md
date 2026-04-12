# Calibre-Web — Skills

> Callable actions for Calibre-Web. No REST API — uses CLI (docker exec) and OPDS feed.

## Authentication

- **Method:** N/A (CLI via docker exec, OPDS is public or behind Authentik Proxy)
- **Container:** `calibre-web`
- **OPDS URL:** `https://books.dev.local/opds`

---

## search-books

**Trigger:** "search books", "find book", "look up author"
**Method:** CLI
**Command:** `docker exec calibre-web calibredb search "<query>"`
**Input:** Search query (title, author, tag)
**Output:** List of matching book IDs

**Alternative (OPDS):**
**Endpoint:** `GET /opds/search?query=<query>`
**Output:** Atom XML feed with matching books

---

## get-book-info

**Trigger:** "book details", "show book info", "what is book [id]"
**Method:** CLI
**Command:** `docker exec calibre-web calibredb show_metadata <book-id>`
**Input:** Book ID
**Output:** Book metadata (title, author, publisher, tags, format, description)
