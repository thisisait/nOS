# Active work — what to do right now

> **Always-current pointer for the next session.** Read this BEFORE
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md) (long-form historical
> record) and [`docs/bones-and-wings-bulk-plan.md`](bones-and-wings-bulk-plan.md)
> (multi-lane coordination plan).
>
> Last updated: 2026-05-06 • D2 batch complete (11 roles + grafana skip +
> follow-up inline values + default.config.yml helpers retired).

---

## Current track: **A5/A7-A10 ramp-up** (D2 ✅ complete)

D-series + β1 closed Track Q's structural arc. D2 batch (12 items) closed
the role-side OIDC duplication — all 11 target roles cleaned, grafana skipped
(already thinned A6.5), vaultwarden plugin template created, gitlab OMNIBUS_CONFIG
decision documented, `authentik_oidc_*` helpers retired from `default.config.yml`.
Next arc is **A5 contracts → A7 gitleaks → A8 conductor → A10 audit →
Phase 5 ceremony** (first non-operator-identity end-to-end write).

### Last verified state (2026-05-06)

- **11 commits ahead of origin** (master @ `7ceb18c`); operator push pending.
- 68/68 anatomy tests + 135/135 callback tests green.
- `python3 tools/aggregator-dry-run.py` exit 0: 0 aligned, 0 central-only,
  36 plugin-only (D1.3 emptied central list), 0 field-diffs.
- `ansible-playbook main.yml --syntax-check` clean.
- 43 plugins live; vaultwarden-base now has a real compose-extension template.
- All `authentik_oidc_<svc>_client_id/_secret` helpers retired from
  `default.config.yml`; plugin templates use inline values from plugin.yml.
- SSO source-of-truth fully in per-plugin `authentik:` blocks (blueprint) +
  plugin compose-extensions (container env). Role compose templates are clean.

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
4. **A5 — Wing OpenAPI/DDL exports** — regenerate `files/anatomy/skills/contracts/{wing,bone}.openapi.yml` + `wing.db-schema.sql`, ověř `--check-summaries` v export-openapi.php (P0.4 advisory → error).
5. **Pulse Wing endpoints** — `PulsePresenter.php` (`pulse_jobs/due` GET + `pulse_runs` POST start/finish); odblokuje A7 + ukončí Pulse 404 warn.
6. **A7 — gitleaks plugin (skill+scheduled-job shape)** — `files/anatomy/plugins/gitleaks/{plugin.yml,skills/run-gitleaks.sh}` + Wing presenter pro `gitleaks_findings` table + Pulse trigger.
7. **A8.a — pulse-run-agent.sh** — `files/anatomy/scripts/pulse-run-agent.sh` (Authentik client_credentials → exec claude → POST /events s `actor_id=conductor`).
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
| `git status` | clean; **11 commits ahead of `origin/master`** awaiting push |
| Last verified | 2026-05-06; tests + dry-run + syntax-check all green |
| Tier-1 services | 16/16 healthy via Traefik (200/302 → Authentik) |
| Plugin loader | 43 plugins (vaultwarden-base now has compose-extension); aggregator 36 plugin-only, 0 field-diffs |
| Authentik blueprints | rendered by `authentik-base` plugin (D1.2); role-side OIDC env fully retired (D2) |
| Pulse | idle-tolerant, 404 on missing endpoints (punch-item #5) |
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
