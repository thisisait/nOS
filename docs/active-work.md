# Active work — what to do right now

> **Always-current pointer for the next session.** Read this BEFORE
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md) (long-form historical
> record) and [`docs/bones-and-wings-bulk-plan.md`](bones-and-wings-bulk-plan.md)
> (multi-lane coordination plan).
>
> Last updated: 2026-05-05 evening • after D-series Authentik refactor
> + β1 SSO trichotomy + D2 outline prototype.

---

## Current track: **D2 + A5/A7-A10 ramp-up**

Phase 1 multi-agent + D-series + β1 closed Track Q's structural arc:
the central `authentik_oidc_apps` list was retired in D1.3, blueprint
generation now flows from per-plugin `authentik:` blocks via the
aggregator (`tools/aggregator-dry-run.py` gates correctness). Next
arc is **A5 contracts → A7 gitleaks → A8 conductor → A10 audit →
Phase 5 ceremony** (first non-operator-identity end-to-end write).

### Last verified state (2026-05-05 evening)

- **21 commits ahead of origin** (master @ `2324b6d`); operator push pending.
- 68/68 anatomy tests + 135/135 callback tests green.
- `python3 tools/aggregator-dry-run.py` exit 0: 34 aligned, 0
  central-only, 2 plugin-only (qdrant + woodpecker), 0 field-diffs.
- `ansible-playbook main.yml --syntax-check` clean.
- 43 plugins live (incl. spacetimedb-base stub from D1.1).
- Authentik blueprint render path: per-plugin `authentik:` block →
  `authentik-base.inputs.clients` → `10-oidc-apps.yaml.j2` +
  `20-rbac-policies.yaml.j2`. Tier-2 apps_runner extras still flow
  through the empty-stub `authentik_oidc_apps` list (long-term:
  extend aggregator with `from: app_manifest` source).

### What just landed (D-series + β1, 11 commits `fc43941..2324b6d`)

| Tag | Commit | Title |
|---|---|---|
| D3 | `fc43941` | aggregator dry-run + parity report |
| D1.0 | `6256944` | flip 4 mis-classified plugin modes to native_oidc (erpnext / homeassistant / jellyfin / superset) |
| β1.A | `74d2314` | header_oidc trichotomy + firefly reclassified |
| β1.B | `067df9f` | Node-RED true native OIDC via passport-openidconnect |
| β1.C/D | `c0d5ea1` | metabase OSS verdict + upstream PR roadmap |
| D1.1 | `176edbb` | spacetimedb-base stub closes last C1 blocker |
| D1.2 | `eea0e12` | blueprint pivots to inputs.clients (aggregator pre-render + feature_flag filter) |
| D1.3 | `fd5081c` | retire central authentik_oidc_apps |
| D1.4 | `06bccfc` | CLAUDE.md sync (3-bucket SSO trichotomy) |
| D2 | `2324b6d` | outline prototype — drop role-side OIDC env (plugin authoritative) |

### Doctrine docs born today

- `docs/native-sso-survey.md` — β1 audit of every proxy-auth service
- `docs/upstream-pr-opportunities.md` — FOSS contributions roadmap
- `docs/aggregator-parity-report.md` — D3 dry-run baseline
- `docs/multi-agent-batch.md` — coordinator pattern from Phase 1 retro
- `docs/track-q-residue-analysis.md` — 7 plugin-less roles + verdict
- Tools: `tools/aggregator-dry-run.py` (gating), `tools/d12-annotate-plugins.py`

---

## Punch list

Numbered for the loop prompt; each line ≤ 2 sentences.

1. **D2 batch 1** (8 clean-parity rolí) — replikuj outline pattern (commit `2324b6d`) na bookstack, freescout, hedgedoc, infisical, miniflux, n8n, open-webui, wordpress; po každé roli ověř `aggregator-dry-run.py` exit 0 + syntax-check.
2. **D2 special-syntax** — grafana (plugin 20 envů > role 2: smazat 2 v roli), gitlab (`omniauth-openid-connect` env block), vaultwarden (`SSO_*` prefix env block).
3. **D2 follow-up** — retire standalone `authentik_oidc_<svc>_client_id/_secret` helpers v `default.config.yml` po D2 (kompletně už nikdo nečte).
4. **A5 — Wing OpenAPI/DDL exports** — regenerate `files/anatomy/skills/contracts/{wing,bone}.openapi.yml` + `wing.db-schema.sql`, ověř `--check-summaries` v export-openapi.php (P0.4 advisory → error).
5. **Pulse Wing endpoints** — `PulsePresenter.php` (`pulse_jobs/due` GET + `pulse_runs` POST start/finish); odblokuje A7 + ukončí Pulse 404 warn.
6. **A7 — gitleaks plugin (skill+scheduled-job shape)** — `files/anatomy/plugins/gitleaks/{plugin.yml,skills/run-gitleaks.sh}` + Wing presenter pro `gitleaks_findings` table + Pulse trigger.
7. **A8.a — pulse-run-agent.sh** — `files/anatomy/scripts/pulse-run-agent.sh` (Authentik client_credentials → exec claude → POST /events s `actor_id=conductor`).
8. **A8.b — conductor agent profile** — `files/anatomy/agents/conductor.yml` (system prompt + capability scopes + schedule).
9. **A8.c — Wing /inbox + /approvals views** — Latte presenters pro pending-approvals + drift reports + gitleaks findings.
10. **A10 — actor audit migration** — `actor_id` (FK authentik_clients) + `actor_action_id` (UUID) + `acted_at` na všech wing.db write tables + presenter updates v 2-3 batch.
11. **Phase 5 ceremony** — `conductor-self-test-001` Pulse one-shot job (8-step e2e: health → trigger gitleaks → verify findings → events → contracts diff → wing tests → markdown report); pass = první non-operator end-to-end write do wing.db.
12. **Tier-2 aggregator path** — extend `run_aggregators` o `from: app_manifest` source, retire `authentik_oidc_apps: []` Tier-2 stub.

KEEP role-side (don't touch in D2): firefly (header_oidc REMOTE_USER), nodered (β1.B), paperclip (staged toggle), uptime-kuma + spacetimedb (doc-only).

---

## Snapshot table

| Surface | State |
|---|---|
| `git status` | clean; **21 commits ahead of `origin/master`** awaiting push |
| Last verified | 2026-05-05 evening; tests + dry-run + syntax-check all green |
| Tier-1 services | 16/16 healthy via Traefik (200/302 → Authentik) |
| Plugin loader | 43 plugins; aggregator harvests 34 → inputs.clients with feature_flag filter + Jinja pre-render |
| Authentik blueprints | rendered by `authentik-base` plugin (D1.2 cutover); role-side templates retired |
| Pulse | idle-tolerant, 404 on missing endpoints (Pulse Wing endpoints punch-item #5) |
| Test gates | anatomy 68/68, callback 135/135, aggregator-dry-run exit 0 |
| Decision log | O1-O18 in `roadmap-2026q2.md` (append-only) |

---

## How to update this file

After every meaningful work session:

1. Update **Last verified state** + snapshot table.
2. Cross-strike completed punch-list items + add follow-ups.
3. If a phase landed, append entry to **What just landed** + log the
   decision in `roadmap-2026q2.md` if it changed direction.
4. Commit `docs(roadmap): refresh active-work pointer`.
