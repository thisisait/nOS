# Kiwix — Skills

> Callable actions for Kiwix. Public read-only API, no authentication required.

## Authentication

- **Method:** None (public access)
- **Base URL:** `https://kiwix.dev.local`

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

---

## list-libraries

**Trigger:** "list libraries", "what content is available", "show ZIM files"
**Method:** API
**Endpoint:** `GET /catalog/search`
**Input:** None
**Output:** OPDS Atom feed listing available ZIM content libraries with titles, descriptions, and sizes
