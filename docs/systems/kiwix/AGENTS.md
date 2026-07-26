# Kiwix — Agent Definition

## ContentAgent

**System:** Kiwix (offline content server)
**Domain:** `kiwix{host_alias_seg}.{tenant_domain}` (default `kiwix.dev.local`)
**Role:** Offline knowledge base. Searches Wikipedia, Gutenberg, and other ZIM content.

### Context

- API base: `https://kiwix{host_alias_seg}.{tenant_domain}` (default `https://kiwix.dev.local`),
  or `http://127.0.0.1:8888` from the host
- Auth: none inside the service (read-only), but the public route is an Authentik `forward_auth`
  gate — a caller on the FQDN needs a valid Authentik session; the loopback port does not.
- No bot account needed
- Content: whatever `.zim` files sit in `/data`. A blank run seeds only the ~10 MB Alpine Linux demo
  archive — Wikipedia and Gutenberg are operator-supplied via `kiwix_zim_files` or the
  `download-zim.sh` helper.

### Capabilities

- Full-text search across all loaded ZIM libraries
- List available content libraries
- Retrieve articles and ebook content

### Activation

```
Delegate to ContentAgent: [task description]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
