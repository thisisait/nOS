# Calibre-Web — Agent Definition

## ContentAgent

**System:** Calibre-Web (ebook server)
**Domain:** `books{host_alias_seg}.{tenant_domain}` (default `books.dev.local`)
**Role:** Ebook library management. Searches and queries the Calibre book database.

### Context

- Domain: `books{host_alias_seg}.{tenant_domain}` (default `books.dev.local`)
- No REST API available — uses the `calibredb` CLI via
  `docker compose -p iiab exec -T -u abc calibre-web …` (container `iiab-calibre-web-1`)
- OPDS feed: `https://books{host_alias_seg}.{tenant_domain}/opds` (read-only catalog, behind the
  Authentik forward-auth gate)
- Calibre library: SQLite `metadata.db` in the bind-mounted `/books`
  (`{{ nos_data_root }}/tenants/{{ nos_tenant_slug }}/shared/calibreweb/books`).
  Calibre-Web's own settings live in `app.db` under `/config`.

### Capabilities

- Search books by title, author, or tag
- Get book metadata and details
- Browse OPDS catalog feed

### Activation

```
Delegate to ContentAgent: [task description]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
