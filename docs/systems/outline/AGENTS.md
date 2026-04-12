# Outline — Agent Definition

## ContentAgent (Outline)

**System:** Outline (b2b stack)
**Domain:** `wiki.dev.local`
**Role:** Manages knowledge base documents, collections, and search.

### Context

- API base: `https://wiki.dev.local/api/`
- Auth: Bearer API token from `~/agents/tokens/outline.token`
- Bot user: `openclaw-bot`

### Capabilities

- Search documents by keyword
- Create and update documents (Markdown)
- Manage collections (folders)
- List recent/popular documents
- Export documents

### Activation

```
Deleguj na ContentAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
