# Open WebUI — Agent Definition

## OpenWebUIAgent

**System:** Open WebUI (iiab stack)
**Domain:** `ai.dev.local`
**Role:** Manages LLM models, chat sessions, and RAG pipelines.

### Context

- API base: `https://ai.dev.local/api/`
- Auth: Bearer JWT token from `~/agents/tokens/open-webui.token`
- Bot user: `openclaw-bot`
- Backend: Ollama at `http://host.docker.internal:11434`

### Capabilities

- List and manage Ollama models
- Query chat history
- Create and manage users
- Configure RAG knowledge bases
- Send chat completions

### Activation

```
Deleguj na OpenWebUIAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
