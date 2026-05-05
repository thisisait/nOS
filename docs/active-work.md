# Active work — what to do right now

> **Always-current pointer for the next session.** Read this BEFORE
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md) (long-form historical
> record) and [`docs/bones-and-wings-bulk-plan.md`](bones-and-wings-bulk-plan.md)
> (multi-lane coordination plan).
>
> Last updated: 2026-05-06 • A5+A7 batch complete (contracts sync + gitleaks
> plugin: schema, Wing presenter, Pulse job-reg endpoint, skill script,
> daemon env fix).

---

## Current track: **A8-A10 ramp-up** (D2 ✅ A5 ✅ A7 ✅ complete)

A5+A7 batch (7 commits `436db7d..d558e1b`) established the first end-to-end
scheduled-job write path: gitleaks plugin → Pulse subprocess runner (env fix) →
Wing gitleaks_findings table + presenter. Contracts synced from live sources
(bone /api/health split + events.source column). Pulse job-registration endpoint
live (`POST /api/v1/pulse_jobs`). OpenAPI now 70 paths, 87/87 real summaries.

**Next arc: A8 conductor → A10 audit → Phase 5 ceremony** (first non-operator
end-to-end write to wing.db). Note: OpenClaw must be a first-class Wing API
consumer before A8 ships (see punch-item note on #7).

### Last verified state (2026-05-06)

- **19 commits ahead of origin** (master @ `d558e1b`); operator push pending.
- 529/529 tests pass (68 anatomy + rest of suite), 5 skipped.
- `python3 tools/aggregator-dry-run.py` exit 0: 0 field-diffs.
- `ansible-playbook main.yml --syntax-check` clean.
- Wing OpenAPI: 70 paths, 87/87 real summaries, `--check-summaries` exit 0.
- `gitleaks_findings` table + Wing presenter + Pulse job-reg endpoint live.
- gitleaks plugin manifest + nightly-scan skill at `files/anatomy/plugins/gitleaks/`.
- Pulse daemon now passes `env_json` to subprocess runner (was silently dropped).

### What just landed (A5+A7 batch, 7 commits `436db7d..d558e1b`)

| Tag | Commit | Title |
|---|---|---|
| A5.1 | `436db7d` | fix(anatomy): A5 — sync contracts from live sources |
| A7.1 | `bfe7629` | feat(wing): A7.1 — gitleaks_findings table + indexes |
| A7.2+3 | `01feed5` | feat(wing): A7.2+A7.3 — GitleaksRepository + GitleaksPresenter + routes |
| A7.4 | `0647796` | feat(wing): A7.4 — pulse_jobs upsert endpoint + job catalog methods |
| A7.5 | `30f5d9f` | fix(pulse): A7.5 — pass job env_json to subprocess runner |
| A7.6 | `775369e` | feat(gitleaks): A7.6 — plugin manifest + run-gitleaks.sh skill |
| A7.7 | `d558e1b` | fix(anatomy): A7.7 — regenerate wing.openapi.yml (70 paths, 87/87) |

**A7 notable finding:** `daemon._dispatch` was extracting `command + args` from
the Wing job dict but silently dropping `env`. A skill that needs `WING_API_TOKEN`
or `NOS_SCAN_DIR` from `env_json` would have run with an empty env — all skill
scripts would have broken silently. Fixed in A7.5 before first consumer landed.

### What just landed (D2 batch, 12 commits `cddb7e0..7ceb18c`)

| Tag | Commit | Title |
|---|---|---|
| D2.1 | `cddb7e0` | bookstack — drop role-side OIDC env |
| D2.2 | `2015507` | freescout — drop role-side OIDC env |
| D2.3 | `aade539` | hedgedoc — drop role-side OIDC env |
| D2.4 | `04efcf6` | infisical — drop role-side OIDC env |
| D2.5 | `43b8db2` | miniflux — drop role-side OIDC env |
| D2.6 | `819be5a` | n8n — drop role-side OIDC env |
| D2.7 | `c0481f4` | open-webui — drop role-side OIDC env |
| D2.8 | `13e31b7` | wordpress — drop role-side OIDC env |
| D2.9 | `e5dd556` | gitlab — move mkcert CA + extra_hosts; retire dead OMNIBUS_CONFIG copy |
| D2.10 | `5ae7f93` | vaultwarden — create plugin template + drop role-side SSO env |
| D2.11 | `7ceb18c` | retire all authentik_oidc_* helpers from default.config.yml |

**D2 doctrine finding:** gitlab's `GITLAB_OMNIBUS_CONFIG` is a monolithic Ruby-string
env var; Compose file-merge replaces the whole key (last-writer wins, role alphabetically
after plugin). Cannot split infra config from OIDC config across override files. Role
keeps the full OMNIBUS_CONFIG; plugin handles only mkcert CA + extra_hosts + `_NOS_PLUGIN`.

### Previous: D-series + β1 (11 commits `fc43941..2324b6d`)

### Doctrine docs (born D-series + β1)

- `docs/native-sso-survey.md` — β1 audit of every proxy-auth service
- `docs/upstream-pr-opportunities.md` — FOSS contributions roadmap
- `docs/aggregator-parity-report.md` — D3 dry-run baseline
- `docs/multi-agent-batch.md` — coordinator pattern from Phase 1 retro
- `docs/track-q-residue-analysis.md` — 7 plugin-less roles + verdict
- Tools: `tools/aggregator-dry-run.py` (gating), `tools/d12-annotate-plugins.py`

---

## Punch list

Numbered for the loop prompt; each line ≤ 2 sentences.

~~1. **D2 batch 1** (8 clean-parity rolí) — done `cddb7e0..13e31b7`.~~
~~2. **D2 special-syntax** — grafana (skip, A6.5 done), gitlab (mkcert+extra_hosts moved, OMNIBUS_CONFIG kept per doctrine), vaultwarden (plugin template created + role cleaned). Done `e5dd556`, `5ae7f93`.~~
~~3. **D2 follow-up** — `authentik_oidc_*` helpers retired from `default.config.yml`; all plugin templates updated to inline values. Done `7ceb18c`.~~
~~4. **A5 — Wing OpenAPI/DDL exports** — done `436db7d`. bone + schema synced; --check-summaries 87/87 OK.~~
~~5. **Pulse Wing endpoints** — done P0.2 (pre-batch); routes + PulsePresenter live. Pulse 404 warn resolved.~~
~~6. **A7 — gitleaks plugin** — done `bfe7629..d558e1b`. schema + presenter + Pulse job-reg + plugin manifest + skill.~~
7. **A8.a — pulse-run-agent.sh** — `files/anatomy/scripts/pulse-run-agent.sh` (Authentik client_credentials → exec claude → POST /events s `actor_id=conductor`). **Pre-req: audit OpenClaw's Wing API access — it is not fully onboarded; A8 must treat it as a first-class consumer (see next-batch note).**
8. **A8.b — conductor agent profile** — `files/anatomy/agents/conductor.yml` (system prompt + capability scopes + schedule).
9. **A8.c — Wing /inbox + /approvals views** — Latte presenters pro pending-approvals + drift reports + gitleaks findings.
10. **A10 — actor audit migration** — `actor_id` (FK authentik_clients) + `actor_action_id` (UUID) + `acted_at` na všech wing.db write tables + presenter updates v 2-3 batch.
11. **Phase 5 ceremony** — `conductor-self-test-001` Pulse one-shot job (8-step e2e: health → trigger gitleaks → verify findings → events → contracts diff → wing tests → markdown report); pass = první non-operator end-to-end write do wing.db.
12. **Tier-2 aggregator path** — extend `run_aggregators` o `from: app_manifest` source, retire `authentik_oidc_apps: []` Tier-2 stub.

**D2 residual** (nice-to-have, not blocking): freescout/erpnext/homeassistant/superset/nodered/
paperclip role tasks still use `| default(...)` pattern on vars not in `default.config.yml` — inline when those roles get their own D2 pass.

---

## Snapshot table

| Surface | State |
|---|---|
| `git status` | clean; **19 commits ahead of `origin/master`** awaiting push |
| Last verified | 2026-05-06; 529/529 tests + dry-run + syntax-check all green |
| Tier-1 services | 16/16 healthy via Traefik (200/302 → Authentik) |
| Plugin loader | 43 plugins + gitleaks (skill/scheduled-job); aggregator 36 plugin-only, 0 field-diffs |
| Authentik blueprints | rendered by `authentik-base` plugin (D1.2); role-side OIDC env fully retired (D2) |
| Pulse | live — 4 endpoints; job-registration POST live; env pass-through fixed (A7.5) |
| Wing OpenAPI | 70 paths, 87/87 real summaries, `--check-summaries` exit 0 |
| Test gates | 529/529 tests pass, aggregator-dry-run exit 0 |
| Decision log | O1-O20 in `roadmap-2026q2.md` (append-only) |

---

## How to update this file

After every meaningful work session:

1. Update **Last verified state** + snapshot table.
2. Cross-strike completed punch-list items + add follow-ups.
3. If a phase landed, append entry to **What just landed** + log the
   decision in `roadmap-2026q2.md` if it changed direction.
4. Commit `docs(roadmap): refresh active-work pointer`.
