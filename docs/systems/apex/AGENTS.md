# Apex Site — Agent Definition

## No agent

**System:** Apex Site (`iiab` stack) — the public anatomy page at the root domain.
**Domain:** `{tenant_domain}` itself (default `dev.local`) — the ROOT, not a subdomain.
**Role:** none for agents. This is the estate's outward face for anonymous humans;
it has no API, no accounts, and no write path.

### Context

- No API base exists. The service serves `index.html`, `public-anatomy.json` and
  `assets/` — static files only.
- **Auth:** N/A — nOS provisions no apex token and no service account, and there is
  nothing a credential could reach that an anonymous GET cannot.
- Human access is `none` (public by design; `traefik_auth_modes.apex: none`, justified
  per the REM-144 rule). There is no Authentik client for this surface, deliberately.
- Storage: none — stateless; the web root is derived content rebuilt at converge
  (same words as the README's storage row).
- Health: `GET /` → `200`.

### Capabilities

- None wired for agents. The one machine-consumable artifact is
  `GET https://{tenant_domain}/public-anatomy.json` — the operator-SIGNED public
  projection, readable anonymously like everything else here. An agent that wants
  the estate's real anatomy should read `state/anatomy-graph.json` in the repo
  instead; the public projection is deliberately the lesser document.

### For an agent

The interesting surface is upstream of the container: the build pipeline in
`files/anatomy/apex/` (`ruling.yml` → `projection.py` → `render.py`) and its gates
(`tests/anatomy/test_apex_public_projection.py`,
`tests/anatomy/test_apex_serving_is_signature_gated.py`). An agent proposing a change
to the PUBLIC page must change the ruling — and only the operator's signature makes
it servable.

### Skills Reference

See [SKILLS.md](SKILLS.md) — an honest absence.
