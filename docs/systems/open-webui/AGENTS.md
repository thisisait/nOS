# Open WebUI — Agent Definition

## OpenWebUIAgent

**System:** Open WebUI (iiab stack)
**Domain:** `ai{host_alias_seg}.{tenant_domain}` (default `ai.dev.local`)
**Role:** Manages LLM models, chat sessions, and RAG pipelines.

### Context

- API base: `https://ai{host_alias_seg}.{tenant_domain}/api/` (default `https://ai.dev.local/api/`)
- Auth: Bearer JWT from `POST /api/v1/auths/signin`. The playbook provisions **no** bot account and
  **no** token file — there is no `openclaw-bot` and no `~/agents/tokens/open-webui.token`. Sign in as
  the DB-seeded admin (`{{ default_admin_email }}`) or a user created in the UI.
- Backend: Ollama on the host at `http://host.docker.internal:11434`
- Storage: SQLite `webui.db` in `/app/backend/data`
  (`{{ nos_data_root }}/platform/services/openwebui/data`)

### Capabilities

- List and manage Ollama models
- Query chat history
- Create and manage users
- Configure RAG knowledge bases
- Send chat completions

### Activation

```
Delegate to OpenWebUIAgent: [task description]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
