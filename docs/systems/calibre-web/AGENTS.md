# Calibre-Web — Agent Definition

## ContentAgent

**System:** Calibre-Web (ebook server)
**Domain:** `books.dev.local`
**Role:** Ebook library management. Searches and queries the Calibre book database.

### Context

- Domain: `books.dev.local`
- No REST API available — uses CLI via `docker exec calibre-web`
- OPDS feed: `https://books.dev.local/opds` (read-only catalog)
- Calibre database: SQLite at mounted volume

### Capabilities

- Search books by title, author, or tag
- Get book metadata and details
- Browse OPDS catalog feed

### Activation

```
Deleguj na ContentAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
