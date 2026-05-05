# Active work — what to do right now

> **Always-current pointer for the next session.** Read this BEFORE
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md) (long-form historical
> record) and [`docs/bones-and-wings-bulk-plan.md`](bones-and-wings-bulk-plan.md)
> (multi-lane coordination plan).
>
> Last updated: 2026-05-07 • B3 — stack_filter eliminates 33-min post_compose freeze;
> ansible.cfg formatter (yaml callback + display_skipped_hosts=false).

---

## Current track: **A10 + Phase 5** (D2 ✅ A5 ✅ A7 ✅ A8 ✅ complete)

A8 batch (7 commits `d1552dc..4974c53`) delivered the full conductor pipeline:
OpenClaw first-class Wing consumer (dedicated api_token + env injection), nos-conductor
Authentik client + Wing token, pulse-run-agent.sh (Authentik→claude→Wing events),
conductor.yml agent profile (system prompt + Phase 5 self-test-001 Pulse job),
Wing /inbox (unresolved gitleaks + conductor runs) + /approvals stub.
Also fixes: GitleaksRepository missing from common.neon DI config (A7 omission).

**Next arc: A10 actor audit + Phase 5 ceremony** (first non-operator
end-to-end write to wing.db). A10 must land before Phase 5 — actor_id column
enables cryptographic attribution of conductor's writes.

### Last verified state (2026-05-07)

- **32 commits ahead of origin** (master @ `7e2026c`); operator push pending.
- 135/135 tests pass (callback suite; anatomy 68/68 included), 5 skipped.
- `python3 tools/aggregator-dry-run.py` exit 0: 0 field-diffs.
- `ansible-playbook main.yml --syntax-check` clean.
- **B1 fixed:** OpenClaw Wing api_tokens row now provisioned in `pazny.wing/post.yml`
  (was in openclaw/tasks/post.yml which was never called — openclaw runs before stack-up).
- **B2 fixed:** conductor + gitleaks Pulse jobs now registered via `ansible.builtin.uri`
  in `pazny.wing/post.yml` (plugin loader does not process `pulse:` blocks).
- Wing OpenAPI: 70 paths, 87/87 real summaries (no new API routes).
- OpenClaw Wing API token wired in launchd + .zshrc; provisioned via wing/post.yml.
- nos-conductor Authentik client + Wing `conductor` api_tokens row provisioned.
- `pulse-run-agent.sh` at `files/anatomy/scripts/` — Authentik→claude→Wing events.
- `conductor.yml` at `files/anatomy/agents/` — system prompt + self-test-001 Pulse job.
- Wing `/inbox` live (unresolved gitleaks + conductor event history).
- Wing `/approvals` stub live (wired, empty pending A10).
- **Playbook --blank run in progress** on operator machine (2026-05-07).

### What just landed (A8 batch, 7 commits `d1552dc..4974c53`)

| Tag | Commit | Title |
|---|---|---|
| Pre.1 | `d1552dc` | feat(openclaw): Pre.1 — Wing API onboarding for OpenClaw agent |
| A8.a.0 | `009b734` | feat(anatomy): A8.a.0 — conductor identity (Wing token + Authentik client) |
| A8.a | `872dbda` | feat(anatomy): A8.a — pulse-run-agent.sh + agent_run_start/end event types |
| A8.b | `fc3671c` | feat(anatomy): A8.b — conductor agent profile (system prompt + Pulse job) |
| A8.c.1 | `cbf3d7c` | feat(wing): A8.c.1 — /inbox presenter + Latte template |
| A8.c.1s | `23d70a1` | feat(wing): A8.c.1 supplement — Inbox template + layout nav tabs |
| A8.c.2 | `4974c53` | feat(wing): A8.c.2 — /approvals stub presenter + template |

**A8 notable finding:** `GitleaksRepository` was not registered in Wing's DI
config (`common.neon`) — first live call to `/api/v1/gitleaks_findings` would have
thrown a Nette DI resolution error. Fixed in A8.c.1. Pattern: every new repository
class must be explicitly listed in `common.neon` under `services:`.

**New doctrine (agent event types):** Wing's `VALID_TYPES` and `event.schema.json`
now include `agent_run_start` / `agent_run_end` — emitted by agents, not the callback
plugin. The type enum expansion makes them first-class alongside Ansible lifecycle types.

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
~~7. **Pre.1 — OpenClaw Wing onboarding** — `openclaw_wing_api_token` + `post.yml` + env injection. Done `d1552dc`.~~
~~8. **A8.a.0 — conductor identity** — `conductor_wing_api_token` + `nos-conductor` Authentik client + Wing provisioning. Done `009b734`.~~
~~9. **A8.a — pulse-run-agent.sh** — Authentik client_credentials → claude → Wing agent_run_start/end events. Done `872dbda`.~~
~~10. **A8.b — conductor agent profile** — `files/anatomy/agents/conductor.yml` (system prompt + Phase 5 Pulse job). Done `fc3671c`.~~
~~11. **A8.c — Wing /inbox + /approvals** — InboxPresenter (gitleaks open findings + conductor events) + ApprovalsPresenter stub. Done `cbf3d7c..4974c53`.~~
~~11b. **B1+B2 blind-spot fixes** — OpenClaw Wing token moved to wing/post.yml; conductor+gitleaks Pulse jobs registered via Wing API in wing/post.yml. Done `433ac01`.~~
~~11c. **B3 — stack_filter post_compose freeze** — `_plugin_stack()` resolver + `stack_filter` param in `run_hook()`; core-up.yml scoped to [infra, observability]; stack-up.yml adds second call after async join. `ansible.cfg`: yaml callback + display_skipped_hosts=false. Done `7e2026c`.~~
12. **A10 — actor audit migration** — `actor_id` (FK authentik_clients) + `actor_action_id` (UUID) + `acted_at` na všech wing.db write tables + presenter updates v 2-3 batch.
13. **Phase 5 ceremony** — `conductor-self-test-001` Pulse one-shot job (8-step e2e: health → trigger gitleaks → verify findings → events → contracts diff → wing tests → markdown report); pass = první non-operator end-to-end write do wing.db. **Pre-req: A10 must land first for actor attribution.**
14. **Tier-2 aggregator path** — extend `run_aggregators` o `from: app_manifest` source, retire `authentik_oidc_apps: []` Tier-2 stub.

**D2 residual** (nice-to-have, not blocking): freescout/erpnext/homeassistant/superset/nodered/
paperclip role tasks still use `| default(...)` pattern on vars not in `default.config.yml` — inline when those roles get their own D2 pass.

---

## Snapshot table

| Surface | State |
|---|---|
| `git status` | clean; **30 commits ahead of `origin/master`** awaiting push |
| Last verified | 2026-05-07; 135/135 tests + dry-run + syntax-check all green |
| Tier-1 services | --blank run in progress (2026-05-07) |
| Plugin loader | 43 plugins + gitleaks (skill/scheduled-job); aggregator 36 plugin-only, 0 field-diffs |
| Authentik blueprints | rendered by `authentik-base` plugin (D1.2); nos-conductor added to agent_clients (A8.a.0) |
| Pulse | live — 4 endpoints; conductor + gitleaks jobs registered via wing/post.yml (B2) |
| Wing OpenAPI | 70 paths, 87/87 real summaries |
| Wing UI | /inbox (gitleaks + conductor events) + /approvals stub live (A8.c) |
| OpenClaw | Wing API token wired; provisioned in wing/post.yml (B1 fix) |
| Conductor | pulse-run-agent.sh + conductor.yml at `files/anatomy/`; Wing pulse job registered |
| Test gates | 135/135 tests pass, aggregator-dry-run exit 0 |
| Decision log | O1-O23 in `roadmap-2026q2.md` (append-only) |

---

## How to update this file

After every meaningful work session:

1. Update **Last verified state** + snapshot table.
2. Cross-strike completed punch-list items + add follow-ups.
3. If a phase landed, append entry to **What just landed** + log the
   decision in `roadmap-2026q2.md` if it changed direction.
4. Commit `docs(roadmap): refresh active-work pointer`.
