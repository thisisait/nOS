# v0.7 GDPR — Retention enforcement is metadata, not action

Status: PLAN (not implemented). Target branch: `feat/v0.7-overnight`.
Owner: overnight agent batch. Scope: repo edits only, no live mutation.

## Problem / why

This is the **P0-5 storage-limitation gap** named in the gov-readiness audit
(`docs/compliance/gov-readiness-audit-2026q2.md` §45/§57/§163):

> *"Retention enforcement is metadata, not action. `retention_days` in every
> Art-30 record is descriptive; only `wing.db` events are actually purged, and
> even that is `never`-tagged manual-only. Application stores, Qdrant, Redis,
> `agent_*`, RustFS accumulate indefinitely. This is the single largest
> *enforced*-control gap and keeps Art-5 below passing."*

Concretely, today:

- **Every plugin declares `gdpr.retention_days`** (`open-webui` 365, `mailpit`
  7, `freepbx` 90, `prometheus` 30, `wing` -1, …). `nos_gdpr.py` maps it into the
  Art-30 register and `tools/gdpr-dpa-register.py` renders it as prose
  (`_retention_human`). The metadata is **CI-pinned** by
  `tests/anatomy/test_gdpr_register_coverage.py`.
- **Nothing acts on it.** The only enforcement primitive that exists is
  `tasks/audit-retention.yml` → `files/anatomy/wing/bin/purge-events.php`, which
  purges **only the `wing.db` `events` table**, is dry-run by default, and is
  `['audit-retention','never']`-tagged in `main.yml:972-974` (manual-only, not
  scheduled). Application DBs, Qdrant, Redis, the `agent_*` tables, Loki/Tempo,
  and RustFS backups accumulate forever.
- The audit's headline recommendation (§163, [high]) is: *"Add scheduled Pulse
  retention-purge jobs for application DBs, Qdrant, Redis, `agent_*` tables, and
  RustFS keyed to each record's `retention_days`; schedule
  `tasks/audit-retention.yml`."*

Why a *plan* and not a one-shot fix: "purge every application store on its
`retention_days`" is **not one mechanism** — it is ~50 heterogeneous stores
(Postgres, MariaDB, SQLite, Redis, Qdrant, object buckets, encrypted backups,
append-only WORM audit chains) each with a different, often **destructive and
irreversible** delete path, several of which have *no* safe automatable
per-record purge at all (a backup archive must NOT be surgically edited;
`retention_days: -1` means "never auto-purge"; the WORM-chained `events` rows
are integrity-protected). A blind "DELETE older than N days" sweep across all of
them overnight is exactly the catastrophic-mistake class the operator's
destructive-op safety model forbids. So this plan **builds the enforcement
spine + a real, gated, dry-run-first reach for the stores where an
email-/time-keyed purge is genuinely safe**, and is **honest** about the stores
that stay metadata-only-by-design (with the reason recorded, mirroring the
`state/gdpr-erasure-map.yml` `method: manual` doctrine).

The honest target for v0.7: **move from "1 store enforced, manual-only" to "a
declarative, per-service retention contract + a dry-run-first purge engine that
covers the safely-automatable stores + a scheduled (gov-opt-in) drift/plan
job"** — and pin every claim with a gate. This is the same shape as the
existing Art-17 erasure machinery (`state/gdpr-erasure-map.yml` +
`tasks/gdpr-forget.yml`): one centralized, audited, reviewable list; dry-run
default; explicit `-e confirm`; auto-run only the verified-safe methods, REPORT
the rest.

## Design doctrine (load-bearing — read before touching anything)

1. **Destructive-op safety model is NON-NEGOTIABLE** (operator memory
   `feedback-destructive-op-safety`): dry-run **default**, explicit
   `-e retention_confirm=true` gate, **manual over auto-scheduled** for the
   destructive sweep, **centralized + audited** destructive-command list. The
   per-store purge commands live in ONE reviewable file, never scattered.
2. **Mirror the Art-17 erasure pattern exactly.** `tasks/gdpr-forget.yml`
   already proved the shape: a central `state/gdpr-erasure-map.yml` with
   `method: {authentik_api | container_exec | manual}`, dry-run-first, audited
   Bone event, DSAR row. Retention is the *time-keyed* sibling of that
   *subject-keyed* deletion — reuse the structure, do not invent a second one.
3. **Auto-run ONLY verified-safe methods.** A store is `auto`-eligible only if
   its purge is (a) time-keyed (`DELETE WHERE ts < now-N`), (b) idempotent, (c)
   non-catastrophic if the horizon is mildly wrong (drops old rows, not the
   schema), and (d) live-verifiable. Everything else is `manual` (the dry-run
   prints the exact documented command; a confirmed run still only REPORTS it).
4. **`retention_days` semantics are already defined** (`_retention_human` in
   `nos_gdpr.py`): `-1` = indefinite/lifecycle-managed (**never** auto-purge —
   deletion only via DSAR), `0` = transient/not-persisted (**nothing to
   purge**), `N>0` = purge older than N days. The engine MUST honor these three
   cases — a `-1` or `0` store is *correctly* skipped, not a coverage gap.
5. **Backups are carved out (Art-17(3) / recital 65 precedent already in
   `gdpr-erasure-map.yml` `svc_rustfs`).** Encrypted backup archives age out via
   `roles/pazny.backup` rotation (7 daily + 4 weekly + 12 monthly) — they are
   **never** surgically purged. The retention engine does not touch RustFS; the
   backup-rotation policy IS the retention control for that store, and the plan
   only *documents* that linkage.
6. **Scheduling is gov-opt-in and PLAN-ONLY by default.** Following the
   `authentik-tofu-drift-base` precedent (a daily *read-only plan* Pulse job that
   never applies), the scheduled job runs the retention engine in **dry-run /
   report mode** and notifies the operator of what *would* be purged. Actual
   deletion stays operator-initiated (`-e retention_confirm=true`), or is enabled
   for the gov track via an explicit `profiles/gov-local.yml` opt-in flag. This
   honors "manual over auto-scheduled" while still closing the *visibility* gap
   (an operator can no longer be unaware that a store is over-retaining).

## The deliverables (what "enforced, not metadata" concretely means here)

### A. Central retention contract — `state/gdpr-retention-map.yml` (NEW)

The single audited source of truth, sibling of `state/gdpr-erasure-map.yml`.
One entry per store that holds time-bounded data, each declaring **how** its
retention is enforced. Shape (mirrors the erasure-map keys + adds horizon
source):

```yaml
# state/gdpr-retention-map.yml
# Time-keyed storage-limitation purge (Art. 5(1)(e)). Sibling of the
# subject-keyed gdpr-erasure-map.yml. dry-run default; -e retention_confirm=true.
# horizon: where retention_days comes from (plugin gdpr block / config var).
# method: auto (verified-safe time-keyed purge) | manual (documented, reported).
stores:
  - id: svc_wing_events
    flag: install_wing
    method: auto                       # already implemented + verified
    horizon_var: wing_audit_retention_days   # 365 default
    command_ref: purge-events.php      # the EXISTING primitive
    note: "Wing audit events; WORM-chain-aware DELETE (purge-events.php)."

  - id: svc_loki
    flag: always
    method: auto                       # Loki has a native compactor/retention API
    horizon_var: loki_retention_days
    note: "Loki retention is config-driven (compactor + limits_config).
            Enforce via the loki config horizon, not a row DELETE."

  - id: svc_tempo
    flag: always
    method: auto
    horizon_var: tempo_retention_days
    note: "Tempo block retention via compactor.block_retention in tempo.yaml."

  - id: svc_prometheus
    flag: always
    method: auto
    horizon_var: prometheus_retention   # already a real flag
    note: "--storage.tsdb.retention.time; already enforced by the flag.
            This entry DOCUMENTS the existing native enforcement."

  - id: svc_redis
    flag: install_redis
    method: manual
    note: "Sessions are TTL-keyed (opaque session ids, not time-range rows).
            No bulk time DELETE; rely on per-key TTL. FLUSHDB over-deletes."

  - id: svc_qdrant
    flag: install_qdrant
    method: manual
    note: "Embeddings carry no ts to range-delete on; purge keyed on source-doc
            / agent-session id via Bone QdrantClient (same seam as erasure)."

  - id: svc_rustfs
    flag: install_rustfs
    method: manual
    note: "BACKUP CARVE-OUT (Art-17(3)/recital 65): encrypted dumps age out via
            roles/pazny.backup rotation (7d+4w+12m). NEVER surgically purged."

  - id: svc_wing_agent_tables
    flag: install_wing
    method: manual
    note: "agent_sessions/threads/iterations/memory_stores may carry subject
            content in prompts. Time-purge once a verified agent-table reaper
            exists (follow-up); today operator-reviewed."

  # Application DBs (Postgres/MariaDB/SQLite app stores): default `manual` —
  # most app stores have NO generic time-keyed audit table; their `retention_days`
  # describes the LIFECYCLE horizon (deletion via DSAR / user delete), not a
  # nightly row-reaper. Promote an app to `auto` only with a verified, service-
  # specific purge command (e.g. an app that ships an audit-log prune CLI).
```

This makes the gap **auditable and honest**: every store is either
`auto`-enforced (with the mechanism named) or `manual` (with the reason), and a
DPO/operator can read one file to see the complete retention posture. The
register-vs-enforcement delta stops being invisible.

### B. Retention engine — `tasks/gdpr-retention.yml` (NEW) + a render of the map

A dry-run-first task file mirroring `tasks/gdpr-forget.yml` / the existing
`tasks/audit-retention.yml`:

- Resolve `_retention_confirm: "{{ retention_confirm | default(false) | bool }}"`.
- Load `state/gdpr-retention-map.yml`; filter to enabled stores (`flag`
  resolved against `install_*`, `always` always-on) — **same enabled-filtering
  doctrine as the tofu registry** (a disabled service is skipped, not purged).
- For each `method: auto` store: run its purge command with `--dry-run` unless
  `_retention_confirm`. The `svc_wing_events` entry delegates to the EXISTING
  `purge-events.php` (do not duplicate logic — `tasks/audit-retention.yml`
  becomes the implementation for that one store, called from here OR kept as the
  per-store handler). Loki/Tempo/Prometheus are **config-driven** retention:
  the engine VERIFIES the rendered config horizon matches the declared
  `retention_days` (a *drift check*, read-only) rather than issuing a delete —
  those stores self-purge once the config is right.
- For each `method: manual` store: print the documented `note` (dry-run) /
  REPORT it on a confirmed run. Never auto-delete.
- Emit a Bone `gdpr_retention_sweep` audit event (same audited-action discipline
  as `gdpr_forget_user`) and a summary debug line.

Wire into `main.yml` next to the existing GDPR block (around L969-974), tagged
`['gdpr-retention','never']` (opt-in, manual-only — matches `gdpr-forget` /
`audit-retention`):

```yaml
# On-demand storage-limitation enforcement; dry-run unless
# -e retention_confirm=true. Not auto-scheduled. See docs/security-baseline.md §4.
#   ansible-playbook main.yml --tags gdpr-retention [-e retention_confirm=true]
- name: "[GDPR] Storage-limitation retention sweep (opt-in)"
  ansible.builtin.import_tasks: tasks/gdpr-retention.yml
  tags: ['gdpr-retention', 'never']
```

### C. Per-store horizon → config wiring (the genuinely *enforced* wins)

The stores where a single config knob ACTUALLY enforces retention today get
their horizon tied to a config var so the declared `retention_days` and the
running enforcement cannot drift:

- **Loki** — add `loki_retention_days` (default 30) in `default.config.yml`;
  render `compactor` + `limits_config.retention_period` in
  `roles/pazny.loki/templates/` (verify whether the role already templates the
  Loki config; if config is currently static, this is the change that makes
  Loki actually delete). Today the erasure-map note says *"rely on the Loki
  retention horizon"* — but **verify the compactor is actually enabled** (an
  unconfigured Loki keeps logs forever). This is the most likely *real* fix in
  the batch.
- **Tempo** — add `tempo_retention_days` (default 14); render
  `compactor.compaction.block_retention` in `roles/pazny.tempo/templates/`.
- **Prometheus** — already enforced via `prometheus_retention`
  (`--storage.tsdb.retention.time`); just DOCUMENT the linkage in the map +
  baseline (no code change; the gate asserts it stays wired).

These three are the concrete "metadata → action" deltas; the rest of the map is
honest documentation of why a store is `manual`.

### D. gov-opt-in scheduled DRY-RUN drift job (visibility, not deletion)

A new composition plugin `files/anatomy/plugins/gdpr-retention-base/plugin.yml`
following the `authentik-tofu-drift-base` precedent EXACTLY:

- `type: [composition, scheduled-job]`, no compose extension, `requires: role:
  pazny.wing`.
- A daily Pulse job (`schedule: "45 5 * * *"`, offset from the tofu-drift 05:30
  and gitleaks 03:00 slots) running a **read-only** retention REPORT script
  (`files/anatomy/plugins/gdpr-retention-base/skills/run-retention-report.sh`)
  that runs the engine in dry-run mode and emits ONE notification listing stores
  over their horizon. **Never deletes.** Provably inert until Wing is installed
  (script exits 0 with a skip line if the map / wing.db is absent — gitleaks /
  tofu-drift precedent).
- A complete `gdpr:` + canonical A9 `notification:` block (required by the
  loader + `test_plugin_wiring_contract.py` + `test_gdpr_register_coverage.py`).
  `gdpr.data_subjects: [operators]`, `legal_basis: legitimate_interests`,
  retention metadata for the report itself.
- Actual scheduled DELETION is **not** shipped on; it's a documented
  `profiles/gov-local.yml` opt-in (`gdpr_retention_enforce: false` default) that
  a gov operator flips after reviewing the dry-run. This is the "manual over
  auto-scheduled" line held while still closing the visibility gap.

## Files to touch

NEW:
- `state/gdpr-retention-map.yml` — central audited retention contract (§A).
- `tasks/gdpr-retention.yml` — dry-run-first engine (§B).
- `files/anatomy/plugins/gdpr-retention-base/plugin.yml` — scheduled dry-run
  drift/report plugin (§D).
- `files/anatomy/plugins/gdpr-retention-base/skills/run-retention-report.sh` —
  read-only report runner (inert-until-installed guard).
- `files/anatomy/plugins/gdpr-retention-base/README.md` — one-pager (matches the
  per-plugin README convention).
- `tests/anatomy/test_gdpr_retention_map.py` — **new gate** (below).

EDIT:
- `main.yml` — add the `gdpr-retention` import_tasks block (`['gdpr-retention',
  'never']`), next to the existing `audit-retention` / `gdpr-forget` blocks
  (~L969-974). Mechanical, mirrors the neighbors.
- `default.config.yml` — add `loki_retention_days: 30`, `tempo_retention_days:
  14`, and `gdpr_retention_enforce: false` (stock-string/int scalars, real
  defaults — stock-Jinja trap §below). Reuse the existing `prometheus_retention`
  + `wing_audit_retention_days`.
- `roles/pazny.loki/templates/...` + `roles/pazny.loki/defaults/main.yml` —
  wire `loki_retention_days` into the compactor/limits config (VERIFY the role
  templates the config first; if static, templating it is part of this change).
- `roles/pazny.tempo/templates/...` + `roles/pazny.tempo/defaults/main.yml` —
  wire `tempo_retention_days` into `block_retention`.
- `profiles/gov-local.yml` — add the commented `gdpr_retention_enforce: true`
  opt-in line + a one-paragraph note (matches the existing breach-scan note).
- `docs/security-baseline.md` §4 — rewrite the "Enforcement" bullet: replace
  *"covers the Wing events store only; … tracked in roadmap"* with the
  retention-map + engine + per-store reality (auto vs manual, the Loki/Tempo
  config-driven horizons, the backup carve-out).
- `docs/compliance/gov-readiness-audit-2026q2.md` — update the P0-5 line + §57
  to reflect the new posture (engine + map + 3 config-enforced stores +
  gov-opt-in scheduled dry-run), keeping it HONEST (still not "fully automated
  per-store deletion across all app DBs" — that's a documented follow-up).

## Approach (build order)

1. **Author `state/gdpr-retention-map.yml`** — the contract first. Cover every
   store the erasure-map's "Backend stores & residual reach" section already
   enumerates + the observability stores + the app-DB default. Each `auto` entry
   names a verified mechanism; each `manual` entry carries the reason.
2. **Verify Loki/Tempo config reality (READ-ONLY on the live system).**
   `docker exec` into the running loki/tempo and read the live config; confirm
   whether the compactor/retention is actually on. This determines whether §C is
   "wire a missing knob" (likely) or "document an existing one". **No writes.**
3. **Write `tasks/gdpr-retention.yml`** — reuse `tasks/audit-retention.yml`'s
   structure for the `svc_wing_events` auto path; add the map-driven loop for the
   rest; emit the Bone audit event. dry-run default, `-e retention_confirm`.
4. **Wire the three config-driven horizons** (Loki, Tempo; Prometheus is
   already wired → just verify + document).
5. **Author the `gdpr-retention-base` plugin + report skill** mirroring
   `authentik-tofu-drift-base` byte-for-byte in structure (pulse + notification +
   gdpr blocks; inert-until-installed script guard).
6. **Write the gate** (`test_gdpr_retention_map.py`).
7. **Docs:** rewrite security-baseline §4 + the audit P0-5 line.
8. **Verify:** full anatomy suite + syntax-check + the DPA-register byte-identity
   gate (a new plugin with a `gdpr:` block means `state/dpa-register.md` must be
   re-rendered + committed — see Risks).

## Gates it needs

New file `tests/anatomy/test_gdpr_retention_map.py` — offline, source-level (no
playbook run, no Docker, no live system), mirroring
`tests/anatomy/test_gdpr_erasure_map.py`:

1. **`test_retention_map_parses`** — `state/gdpr-retention-map.yml` loads, has a
   top-level `stores:` list, each entry has `id` + `flag` + `method` + `note`.
2. **`test_method_enum`** — every `method` ∈ `{auto, manual}`. (Closed set; a
   typo can't silently create an unhandled method.)
3. **`test_ids_use_svc_prefix`** — every `id` starts with `svc_` (matches the
   erasure-map + register convention).
4. **`test_auto_entries_name_a_mechanism`** — every `method: auto` entry
   declares a `horizon_var` **or** a `command_ref` (an auto store must name HOW
   it's enforced — no "auto" with no mechanism, which would be a silent no-op).
5. **`test_flags_are_real_toggles`** — every `flag` is `always` or a real
   `install_*` key present in `default.config.yml` (catches a typo'd flag that
   would make a store silently never-evaluated — same check the erasure-map gate
   does).
6. **`test_retention_minus_one_and_zero_never_auto`** — for any plugin whose
   `gdpr.retention_days` is `-1` (indefinite) or `0` (transient), the matching
   retention-map entry (if present) is NOT `method: auto` (you cannot
   auto-time-purge a store with no finite/positive horizon). Pins doctrine point
   #4 — a `-1` store correctly stays out of the reaper.
7. **`test_backup_store_is_carved_out`** — `svc_rustfs` is `method: manual` and
   its note references the backup-rotation carve-out (Art-17(3)). Pins the
   "never surgically edit encrypted archives" invariant against a future "let's
   automate it" regression.
8. **`test_engine_task_is_dry_run_default`** — parse `tasks/gdpr-retention.yml`;
   assert it resolves `retention_confirm | default(false)` and that the destructive
   branch is gated on it (the destructive-op safety model, source-pinned).
9. **`test_engine_is_never_tagged`** — `main.yml`'s `gdpr-retention` import is
   tagged `never` (opt-in only; cannot fire on a normal `ansible-playbook
   main.yml` run). Mirrors how the suite would pin `audit-retention`/`gdpr-forget`.
10. **`test_new_plugin_register_coverage`** — the new `gdpr-retention-base`
    plugin yields a complete Art-30 record (delegated: this is already enforced
    by the existing `test_gdpr_register_coverage.py` once the plugin lands; the
    new gate just asserts the plugin file exists + carries `pulse` +
    `notification` + `gdpr` blocks so the wiring-contract gate stays green).

Plus the **existing** gates that MUST stay green (run them, don't duplicate):
- `tests/anatomy/test_gdpr_register_coverage.py` — incl. the **byte-identity**
  `test_committed_dpa_register_is_current` (the new plugin's `gdpr:` block adds a
  register row → `state/dpa-register.md` MUST be re-rendered + committed).
- `tests/anatomy/test_plugin_wiring_contract.py` — the new plugin's
  `notification:` block must match the canonical A9 shape.
- `tests/anatomy/test_config_stock_jinja_only.py` — the new config vars.
- `ansible-playbook main.yml --syntax-check` — the new task file + main.yml block.

## Stock-Jinja vars trap compliance (NON-NEGOTIABLE)

New vars in `default.config.yml`:
- `loki_retention_days: 30`, `tempo_retention_days: 14` — plain int literals.
- `gdpr_retention_enforce: false` — plain bool literal.

All three are plain scalars with real defaults, defined in `default.config.yml`
(loads before core-up) — no non-stock filters, no late-resolved refs. Satisfies
both variants of `test_config_stock_jinja_only.py`. The retention-map is loaded
via `include_vars` at task time (a role-default-equivalent late load), so its
contents never enter the `{{ vars }}` core-up eager-resolution namespace — same
as `gdpr-erasure-map.yml` today.

## Risks

- **DESTRUCTIVE if mis-wired — this is the highest-risk plan in the batch.** The
  engine deletes data. Mitigation is structural, not optional: dry-run default,
  `-e retention_confirm=true` gate, `never` tag, auto ONLY for verified-safe
  time-keyed stores, `manual` (report-only) for everything else, backup
  carve-out, `-1`/`0` correctly skipped. Gates #6/#7/#8/#9 pin each of these so a
  later edit can't quietly turn the reaper loose. **No part of this plan runs a
  delete on the live system during implementation — verification is dry-run
  only.**
- **DPA-register byte-identity breakage.** Adding `gdpr-retention-base` with a
  `gdpr:` block changes the rendered `state/dpa-register.md`. `test_committed_
  dpa_register_is_current` will go red until you run `python3
  tools/gdpr-dpa-register.py` and commit the regenerated file. This is expected
  and part of the diff (do not skip it).
- **Loki/Tempo config may be currently static (not templated).** If the roles
  ship a static config without a compactor, "wiring the horizon" is actually
  *adding* retention enforcement that wasn't there — bigger than a knob change.
  §approach step 2 (READ-ONLY live verify) de-risks this BEFORE writing the
  template change; if the config isn't templated, scope the Loki/Tempo wiring to
  a follow-up and ship the map + engine + Prometheus-doc this round (still a real
  win: the contract + dry-run engine + visibility job land regardless).
- **Idempotence churn.** The new plugin adds a Pulse job (one new
  `pulse_jobs` row + one launchd/systemd-timer entry — same churn profile as
  `gdpr-breach-base`/`authentik-tofu-drift-base` landing). The map/engine/tags
  are inert (`never`-tagged) so they add zero churn on a normal converge. Config
  var changes to Loki/Tempo recreate those two containers once (expected).
- **Over-claiming in docs.** The temptation is to write "retention is now
  enforced." It is NOT fully enforced across all app DBs — it's *enforced for
  the safely-automatable stores + visible-everywhere via the dry-run job +
  honestly-mapped for the rest*. The security-baseline + audit edits MUST keep
  that distinction (the audit's whole credibility rests on doc-vs-code honesty;
  three prior falsehoods were the worst finding). Gate the honesty by keeping the
  map's `manual` entries first-class, not hidden.
- **`-1` / `0` semantics.** A `retention_days: -1` store (e.g. `wing` Art-30
  row) must NEVER be auto-purged — `-1` is a deliberate lifecycle-managed
  horizon, deletion only via DSAR. Gate #6 pins this; the engine skips it.
- **Pulse catalog literal-substitution trap** (operator memory
  `pulse-catalog-literal-substitution`): the plugin's `pulse.jobs[].env` tokens
  must be **bare** `{{ token }}` (no `| default`) — `discover-pulse-catalog.py`
  does a LITERAL string replace, not Jinja. Copy the `authentik-tofu-drift-base`
  env block form exactly.

## Verification recipe

```bash
# 0. On the right branch
git switch feat/v0.7-overnight

# 1. The new gate (offline, fast)
python3 -m pytest tests/anatomy/test_gdpr_retention_map.py -q

# 2. The GDPR register + wiring + stock-jinja gates (the new plugin touches all)
python3 -m pytest tests/anatomy/test_gdpr_register_coverage.py \
                  tests/anatomy/test_plugin_wiring_contract.py \
                  tests/anatomy/test_config_stock_jinja_only.py -q

# 3. Regenerate + verify the DPA register byte-identity (the new plugin adds a row)
python3 tools/gdpr-dpa-register.py          # rewrites state/dpa-register.md
git diff --stat state/dpa-register.md       # expect exactly the new svc_gdpr-retention row
python3 -m pytest tests/anatomy/test_gdpr_register_coverage.py::test_committed_dpa_register_is_current -q

# 4. Full anatomy suite stays green
python3 -m pytest tests/anatomy/ -q

# 5. Syntax-check clean (new task file + main.yml block + new plugin)
ansible-playbook main.yml --syntax-check

# 6. Prove the engine is dry-run + never-tagged (DOES NOT delete):
#    a normal run must NOT execute it; an explicit --tags run must default to dry-run.
ansible-playbook main.yml --tags gdpr-retention --syntax-check    # parses, doesn't run
#    (a real dry-run on the live box is operator-supervised, NOT done overnight:
#     ansible-playbook main.yml --tags gdpr-retention   # prints the plan, deletes nothing)

# 7. READ-ONLY live verify of the Loki/Tempo retention reality (no writes):
docker exec <loki>  cat /etc/loki/local-config.yaml | grep -A3 compactor   # is retention on?
docker exec <tempo> cat /etc/tempo.yaml | grep -A3 block_retention

# 8. Frozen 1:1 pre-release probe (optional, before any eventual release push)
tools/ci-local.sh
```

Acceptance: gate #1 green, the register/wiring/stock-jinja gates green, the
DPA-register regenerated + byte-identical, full suite green, syntax-check clean,
the engine provably dry-run-default + `never`-tagged (gates #8/#9), and the
security-baseline + audit docs HONESTLY reflect "auto for safe stores + dry-run
visibility job + honestly-mapped manual stores", not "fully enforced".

## Follow-ups (NOT this plan)

- A verified per-app-DB audit-log reaper for app stores that ship a prune CLI
  (promote those map entries from `manual` to `auto` one at a time, each with
  its own live-verified command + gate row).
- A verified `agent_*`-table time-reaper (promote `svc_wing_agent_tables` to
  `auto`) once a WORM-aware purge for the agent tables exists.
- A Qdrant time-keyed purge seam (today erasure is id-keyed; retention by age
  needs a `created_at` payload field + a Bone reaper).
- Flip `gdpr_retention_enforce: true` in a future gov hardening pass once the
  scheduled dry-run has run clean for an operator-defined soak window.
