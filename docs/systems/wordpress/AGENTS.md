# WordPress — Agent Definition

## ContentAgent

**System:** WordPress (CMS)
**Domain:** `wp.dev.local`
**Role:** Content management. Creates and manages posts, pages, and media.

### Context

- API base: `https://wp.dev.local/wp-json/wp/v2/`
- Auth: Basic auth (Application Password) from `~/agents/tokens/wordpress.token`
- Bot user: `openclaw-bot` (WordPress Application Password, Editor role)
- REST API v2 (WP Core)

### Capabilities

- List, create, and update posts
- List, create, and update pages
- Upload and manage media files
- Manage categories and tags
- Search content

### Activation

```
Deleguj na ContentAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
