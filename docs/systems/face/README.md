# nOS face

> The unified web-desktop shell — a liquid-glass macOS-style desktop that composes
> the existing nOS surfaces (Wing app catalog, iframe-embedded services, Bone VFS,
> KEAP explore + config DataTables) behind Authentik header-SSO. It is a stateless
> BFF (backend-for-frontend), not a data store.

## Quick Reference

| | |
|---|---|
| **URL** | `https://os{host_alias_seg}.{tenant_domain}` (default `https://os.dev.local`) |
| **Port** | `5090` (loopback debug publish; container binds `face_internal_port` 5090, routed by Traefik on `gated_net`) |
| **Stack** | `iiab` |
| **Node id** | `nos.iiab.face` |
| **Toggle** | `install_face: true` |
| **Image** | `nos/face:{{ face_version }}` (default tag `latest`) — BUILT FROM SOURCE, vendored at `files/anatomy/face` |
| **Data** | none — stateless BFF, no volume mount. Per-user state lives in Bone VFS + KEAP DataTables, never in face |
| **Memory limit** | `512m` (`docker_mem_limit_light`) |
| **Network** | `gated_net` only (Traefik-only; SEC-02) |

Domain and port are operator pins in `default.config.yml` (`face_domain`, `face_port`,
`face_version`); the role defaults in `roles/pazny.face/defaults/main.yml` are fallbacks
only. The domain is derived from `tenant_domain` + optional `host_alias` — it is NOT a
hardcoded `dev.local`.

## Authentication

- **Model:** `forward_auth` (Authentik proxy outpost). No local accounts, no login form.
- **Identity source:** `X-Authentik-uid` / `X-Authentik-username` / `X-Authentik-groups`
  forwarded headers. The signed-in Authentik user IS the face user.
- **Anti-spoof:** the BFF believes those headers ONLY when the request also carries
  `X-Face-Edge-Token` (env `FACE_EDGE_TOKEN`), injected by the `face-edge` Traefik
  middleware. A peer container on `gated_net` cannot present it.
- **RBAC tier:** 3 (`nos-users`). App visibility in the desktop is filtered by the
  caller's Authentik tier via the Wing catalog.
- **Admin user:** none.

## API and Health

- **Health endpoint:** `GET /health` — the image bakes a Docker `HEALTHCHECK` on it,
  and the A19 in-stream health-wait polls `http://127.0.0.1:5090/health` (timeout 60s).
- **Agent API:** none. face is a browser-facing BFF; it has no agent-invocable surface
  of its own. See `SKILLS.md`.

## Host-Loopback Dependencies (consumed, all graceful)

face reaches host daemons over `host.docker.internal`; each degrades gracefully when off:

| Env var | Target | Purpose |
|---------|--------|---------|
| `NOS_HUB_API_URL` | Wing `:{{ wing_port }}` `/api/v1/hub/systems` | App catalog (which apps to show) |
| `NOS_VFS_API_URL` | Bone `:{{ bone_port }}` `/api/v1/vfs` | File browser over the per-user tree |
| `NOS_KEAP_TABLES_URL` | KEAP `:{{ keap_port }}` `/agent/v1/tables` | Config DataTables (shell layout SoT) |
| `NOS_KEAP_EXPLORE_URL` | `https://{keap_domain}/explore` | Explore graph iframe |
| `NOS_OLLAMA_URL` | host Ollama `:{{ ollama_port }}` | Command-palette "ask" LLM |

## Dependencies

- Authentik (forward-auth gate + identity headers)
- Wing (app catalog, host loopback — optional, degrades)
- Bone (VFS file browser, host loopback — optional, degrades)
- KEAP (config DataTables + explore iframe — gated behind `install_keap`)
- host Ollama (command palette — optional)
