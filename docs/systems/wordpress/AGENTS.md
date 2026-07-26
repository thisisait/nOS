# WordPress — Agent Definition

## ContentAgent

**System:** WordPress (CMS)
**Domain:** `wordpress.dev.local`
**Role:** Content management. Creates and manages posts, pages, and media.

### Context

- API base: `https://wordpress.dev.local/wp-json/wp/v2/`
- Auth: Basic auth (Application Password) from `~/.nos/secrets.yml::wordpress_devlog_app_password`
- Bot user: `nos-devlog-bot` (author role — can publish/edit its OWN posts, cannot create terms)
- REST API v2 (WP Core)

### Capabilities

- List, create, and update posts
- List, create, and update pages
- Upload and manage media files
- Manage categories and tags
- Search content

### Activation

```
Delegate to ContentAgent: [task description]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
