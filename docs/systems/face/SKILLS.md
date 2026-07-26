# nOS face — Skills

> face has NO external skill surface. This file states that plainly rather than
> inventing endpoints — a confident wrong endpoint is worse than an honest absence.

## No invocable surface

nOS face is a stateless web-desktop BFF that renders a UI for a signed-in human.
It exposes exactly one HTTP endpoint, `GET /health`, used only by the Docker
`HEALTHCHECK` and the A19 health-wait. There is no agent-facing API, no bearer
token, and no command surface. Nothing here is invocable by an agent.

## Where the real surfaces live

Everything face does, it does by calling other systems on the user's behalf. An
agent that needs those capabilities calls them directly, not through face:

- App catalog — Wing `/api/v1/hub/systems` (host daemon).
- File operations — Bone `/api/v1/vfs` (host daemon).
- Knowledge / config DataTables and the explore graph — KEAP `/agent/v1`
  (`nos.iiab.keap`, scope-split bearer tokens). See `docs/systems/keap/SKILLS.md`.
- Command-palette "ask" — host Ollama.

## Why access is header-gated, not token-gated

face trusts `X-Authentik-*` identity headers only when the request also carries
`X-Face-Edge-Token` (`FACE_EDGE_TOKEN`), injected by the `face-edge` Traefik
middleware. This is an anti-spoof gate for the browser path, not an agent
credential — there is nothing for an agent to authenticate against.
