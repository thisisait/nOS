# nOS face — Agent Definition

## FaceShell

**System:** nOS face (iiab stack) — the unified web-desktop shell.
**Domain:** `os{host_alias_seg}.{tenant_domain}` (default `os.dev.local`).
**Role:** A browser-facing BFF that composes other nOS surfaces into one desktop.
It is NOT an agent target and holds no independent state.

### Context

- Built from source (`nos/face`) from the vendored tree at `files/anatomy/face`.
- Identity is forward-auth only — `X-Authentik-*` headers gated by `FACE_EDGE_TOKEN`.
- Stateless: per-user desktop state lives in Bone VFS and KEAP config DataTables,
  the app catalog in Wing, never in face.
- Health: `GET http://127.0.0.1:5090/health`.

### Capabilities

- None invocable by an agent. face renders a UI for a human; it consumes the Wing,
  Bone, KEAP and Ollama surfaces on the user's behalf but exposes no agent API.

### For an agent

To act on the surfaces face presents, call the underlying systems directly:
Wing (`nos.devops`-adjacent host daemon), Bone (host daemon), and KEAP
(`nos.iiab.keap`, `/agent/v1`). See each system's own `SKILLS.md`.
