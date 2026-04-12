# Outline — Skills

> Callable actions for Outline wiki. API-first using personal API token.

## Authentication

- **Method:** Bearer token
- **Token:** `~/agents/tokens/outline.token`
- **Base URL:** `https://wiki.dev.local`
- **Header:** `Authorization: Bearer <token>`

---

## search-documents

**Trigger:** "search wiki for [query]", "find documentation about [topic]"
**Method:** API
**Endpoint:** `POST /api/documents.search`
**Input:** `{ "query": "search term", "limit": 10 }`
**Output:** `{ "data": [{ "document": { "id": "...", "title": "...", "text": "..." } }] }`

---

## create-document

**Trigger:** "create wiki page", "write documentation for [topic]"
**Method:** API
**Endpoint:** `POST /api/documents.create`
**Input:** `{ "title": "...", "text": "# Markdown content", "collectionId": "...", "publish": true }`
**Output:** Document object with ID and URL

---

## update-document

**Trigger:** "update wiki page [title]", "edit documentation"
**Method:** API
**Endpoint:** `POST /api/documents.update`
**Input:** `{ "id": "...", "title": "...", "text": "..." }`
**Output:** Updated document object

---

## list-collections

**Trigger:** "show wiki collections", "list knowledge base sections"
**Method:** API
**Endpoint:** `POST /api/collections.list`
**Input:** `{ "limit": 25 }`
**Output:** `{ "data": [{ "id": "...", "name": "...", "description": "..." }] }`

---

## get-document

**Trigger:** "show wiki page [title]", "read document [id]"
**Method:** API
**Endpoint:** `POST /api/documents.info`
**Input:** `{ "id": "document-uuid" }`
**Output:** Full document with Markdown text
