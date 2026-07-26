# Outline — Agent Definition

## ContentAgent (Outline)

**System:** Outline (b2b stack)
**Domain:** `wiki.dev.local`
**Role:** Manages knowledge base documents, collections, and search.

### Context

- API base: `https://wiki.dev.local/api/`
- Auth: Bearer Personal API Token, `Authorization: Bearer <token>`
- Bot user: none provisioned — log in via SSO, then mint a token in Settings -> API Tokens

### Capabilities

- Search documents by keyword
- Create and update documents (Markdown)
- Manage collections (folders)
- List recent/popular documents
- Export documents

### Activation

```
Delegate to ContentAgent: [task description]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
