# keap-base — CORTEX (knowledge layer)

KEAP (Knowledge Explorer and Preserver) is the **cortex** of the nOS anatomy —
the part of the brain that *remembers*. Bones carry signals, Wings observe,
Pulse keeps time; the cortex holds the curated knowledge map:

- **Taxonomy** — a curated ~790-node knowledge tree, Admin-editable after seeding.
- **Content links** — `requiredData` refs (e.g. `kiwix:wikipedia_en`) resolved
  into live deep links across the nOS content services (Kiwix, Calibre-Web,
  Nextcloud, Open WebUI) under one SSO session.
- **Preservation** — page metadata captured by the companion userscript or
  submitted by agents into a human-review queue.
- **Agent surface** — `/agent/v1` (taxonomy search, node lookup, content
  resolve, captures) on the loopback port for host-side AgentKit processes,
  authenticated by scope-split bearer tokens (`keap_agent_token_ro/rw`),
  responses sized for the 16 KiB tool cap.

## Wiring

| Piece | Where |
|---|---|
| Role (clone + build + compose) | `roles/pazny.keap/` |
| Source repo | `thisisait/nos-keap` (public; org-transferred 2026-07-13) |
| SSO | `header_oidc` — outpost injects `X-Authentik-*`, backend keys rows on uid |
| Network | `gated_net` only (SEC-02); loopback publish = AgentKit surface |
| Traefik | file provider row (`state/manifest.yml`) + `traefik_container_upstreams: keap: {port: 8080}` |
| Health | Docker HEALTHCHECK + `wait_health` on `/api/health` |

Planned (Phase 6): `KeapTool.php` AgentKit tool (`mcp-keap`) + optional
`keap_knowledge` Qdrant collection synced through Bone's embeddings proxy —
the first real corpus for the deferred `librarian` agent.
