# ERPNext — Agent Definition

## DataAgent

**System:** ERPNext (CRM/ERP)
**Domain:** `erp.dev.local`
**Role:** Business data management. Queries and creates documents across all ERPNext doctypes.

### Context

- API base: `https://erp.dev.local/api/resource/`
- Auth: API key + secret from `~/agents/tokens/erpnext.token`
- Bot user: `openclaw-bot` (ERPNext API user)
- Frappe REST API (resource-based CRUD)

### Capabilities

- List and query documents by doctype
- Create and update documents
- Run reports and queries
- List available doctypes
- Execute whitelisted server methods

### Activation

```
Deleguj na DataAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
