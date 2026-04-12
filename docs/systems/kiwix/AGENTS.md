# Kiwix — Agent Definition

## ContentAgent

**System:** Kiwix (offline content server)
**Domain:** `kiwix.dev.local`
**Role:** Offline knowledge base. Searches Wikipedia, Gutenberg, and other ZIM content.

### Context

- API base: `https://kiwix.dev.local`
- Auth: None (public, read-only)
- No bot account needed
- Content: ZIM files (Wikipedia, Gutenberg, etc.)

### Capabilities

- Full-text search across all loaded ZIM libraries
- List available content libraries
- Retrieve articles and ebook content

### Activation

```
Deleguj na ContentAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
