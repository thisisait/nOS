# Open WebUI — Skills

> Callable actions for Open WebUI. API-first using `openclaw-bot` JWT token.

## Authentication

- **Method:** Bearer JWT (obtained via `POST /api/v1/auths/signin`)
- **Token:** `~/agents/tokens/open-webui.token`
- **Base URL:** `https://ai.dev.local`

---

## list-models

**Trigger:** "list models", "what models are available", "show Ollama models"
**Method:** API
**Endpoint:** `GET /api/models`
**Input:** None
**Output:** `{ "data": [{ "id": "llama3:latest", "name": "...", "size": ... }] }`

---

## chat-completion

**Trigger:** "ask AI", "send prompt to [model]", "generate response"
**Method:** API
**Endpoint:** `POST /api/chat/completions`
**Input:**
```json
{
  "model": "llama3:latest",
  "messages": [{"role": "user", "content": "..."}],
  "stream": false
}
```
**Output:** `{ "choices": [{ "message": { "content": "..." } }] }`

---

## list-chats

**Trigger:** "show chat history", "list conversations"
**Method:** API
**Endpoint:** `GET /api/v1/chats`
**Input:** Query params: `page`, `limit`
**Output:** `[{ "id": "...", "title": "...", "created_at": "..." }]`

---

## list-users

**Trigger:** "list users", "who has access"
**Method:** API
**Endpoint:** `GET /api/v1/users`
**Input:** None (admin only)
**Output:** `[{ "id": "...", "name": "...", "email": "...", "role": "..." }]`

---

## manage-knowledge

**Trigger:** "add knowledge base", "upload documents for RAG"
**Method:** API
**Endpoint:** `POST /api/v1/knowledge/create`
**Input:** `{ "name": "...", "description": "..." }` + file upload
**Output:** Knowledge base object with ID
