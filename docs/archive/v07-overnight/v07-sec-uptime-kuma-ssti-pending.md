# Plan — REM-073 Uptime Kuma SSTI (CVE-2026-33130) pending

- **Item:** `REM-073` — `finding_ref: CVE-2026-33130` / `GHSA-v832-4r73-wx5j`
- **Component:** `uptime_kuma` · **Severity:** HIGH · **Status:** pending · **auto_fixable:** false
- **Branch:** `feat/v0.7-overnight`
- **Type:** PLAN ONLY — no live mutation, no playbook run. Repo edits + a pytest gate.

---

## 1. Problem / why

Uptime Kuma's Liquid notification-template engine has an SSTI that allows
**arbitrary file read** (read `/etc/shadow`, Docker secrets, etc.) by an
authenticated user who can edit a notification channel. CVE-2026-33130 is the
*incomplete-fix* follow-up to GHSA-vffh-c9pq-4crh: unquoted absolute paths
bypass the earlier Liquid mitigation. The advisory range is **1.23.0 → 2.2.0
vulnerable, fixed in 2.2.1**.

nOS pins (config-wins source of truth) `uptime_kuma_version: "1.23.13"` in
`default.config.yml:1526` — squarely inside the vulnerable range. The pin is
deliberate: 1.x is the last line that does **not** require a breaking
SQLite-schema migration. The complete fix (2.2.1) is a **1.x → 2.x major bump**
(one-way data migration, no downgrade path), already authored as an upgrade
recipe at `upgrades/uptime_kuma.yml` but **never applied** — so the live image
is vulnerable.

Mitigating context (does not close the finding, only lowers exploitability):

- The service sits behind the Authentik **forward_auth** outpost — an attacker
  needs a valid SSO session before they can reach the Kuma UI at all.
- Editing notification templates is an **admin-tier** action inside Kuma
  (Tier-3 service; admin user is playbook-provisioned, single shared admin).

Net: real-world risk is gated, but the file-read primitive is genuine and the
finding is correctly HIGH. It must end this task in **one of two auditable
states**, never the current silent-vulnerable-pin state:

1. **Remediated** — operator triggers the existing `1.x → 2.2.1` upgrade recipe
   (a supervised, destructive-adjacent action — OUT OF SCOPE for the unsupervised
   overnight run), then bumps the pin. OR
2. **Deferred-with-teeth** — the pending status, the partial-mitigation rationale,
   and the citation truth are pinned by a gate so the deferral is a *documented,
   non-drifting* decision rather than an orphaned vulnerable pin.

This plan delivers **state 2** (the only state achievable without a live,
supervised, schema-migrating bump) plus the operator runbook + trigger to reach
state 1 on demand. It also fixes a **citation bug** discovered while scoping
(see §2).

### Secondary defect found while scoping (fold into this fix)

`default.config.yml:1526` and `upgrades/uptime_kuma.yml:11` cite the SSTI pin as
**"REM-067"**. REM-067 in the authoritative queue is a *different* finding —
**MariaDB CVE-2026-35549** (`component: mariadb`). The real Kuma SSTI items are
**REM-037** (original SSTI, MEDIUM) and **REM-073** (CVE-2026-33130, HIGH). The
"067" citation is a copy-paste error that will mislead an auditor cross-checking
the queue. Correct the citation to `REM-037` + `REM-073` at both sites. (This is
the exact orphaned/wrong-citation class the MariaDB gate
`test_mariadb_cve_citation_sync.py` was built to prevent.)

---

## 2. Exact files / roles to touch

| File | Change |
|------|--------|
| `default.config.yml` (~line 1526) | Fix the wrong `REM-067` citation on the `uptime_kuma_version` line → `REM-037/REM-073`; ensure `CVE-2026-33130` is named so the gate can anchor on it. **Do NOT change the value `1.23.13`** — the bump is the supervised path, not this task. |
| `upgrades/uptime_kuma.yml` (notes, ~line 11) | Same citation fix (`REM-037/067` → `REM-037/073`); the recipe `id: uptime-kuma-1-to-2 → to: "2.2.1"` is already correct, leave it. |
| `roles/pazny.uptime_kuma/README.md` (~line 37 + variables table) | Add a security note row: the `1.23.13` pin is partial-mitigation for CVE-2026-33130; full fix = 2.2.1 via `upgrades/uptime_kuma.yml`, deferred breaking major. Keep the existing migration-path note (line 79). |
| `roles/pazny.uptime_kuma/defaults/main.yml` (~line 14) | Extend the existing `# NOTE (C1 …)` block to name `CVE-2026-33130 / REM-073` and the 2.2.1 fix target, so the role-default surface carries the same citation as config (mirrors the MariaDB 3-site sync doctrine). Value stays the major-track `"1"` — it's on the `INTENTIONAL_SHADOW` allowlist. |
| `docs/llm/security/remediation-queue.json` | Update **REM-073** `remediation_detail` to record the decision: *pinned to 1.23.13 (in-range, partially mitigated by forward_auth gate); full fix deferred to a supervised `upgrades/uptime_kuma.yml` apply — see `docs/plans/v07-sec-uptime-kuma-ssti-pending.md`.* Keep `status: pending` (it is genuinely unremediated). Optionally add a `deferral_ref` field pointing at this plan + the upgrade recipe. Do **not** flip to `resolved`. |
| `tests/anatomy/test_uptime_kuma_ssti_pin.py` | **NEW** gate (see §4). |
| `docs/llm/security/scan-state.json` | Optional: leave as-is (the gate, not scan-state, becomes the durable pin). Only touch if the drift hook complains about `last_full_scan` — out of scope here. |

**Not touched:** `roles/pazny.uptime_kuma/templates/compose.yml.j2` (it already
reads `{{ uptime_kuma_version }}`; no value change), the live system (read-only),
the `INTENTIONAL_SHADOW` entry in `test_version_pin_no_shadow.py` (the
config-pins-patch / role-pins-major split is intentional and stays).

---

## 3. Approach

This is a **documentation + gate** change that converts an undocumented
vulnerable pin into a *consciously deferred, citation-correct, gate-pinned*
state, and hands the operator a one-command path to the real fix.

1. **Fix the citation drift** (REM-067 → REM-037/REM-073, name CVE-2026-33130)
   at all four surfaces (config, recipe notes, role default, README) so every
   place that mentions the Kuma SSTI agrees and points at the *correct* queue IDs.

2. **Record the deferral decision** in the remediation queue's REM-073 entry —
   status stays `pending`, but the detail now explains *why* it's deferred (breaking
   1.x→2.x schema migration, supervised-only) and *where* the trigger lives
   (`upgrades/uptime_kuma.yml`), referencing this plan.

3. **Add a gate** (`test_uptime_kuma_ssti_pin.py`) that pins the *truth* of the
   deferral so it can't silently rot:
   - the live pin in `default.config.yml` is a **known-vulnerable-but-intentional**
     value — assert it is exactly one of an explicit allowlist (`{"1.23.13"}` for
     the deferral, or `>= 2.2.1` once the operator applies the bump). Any *other*
     value (e.g. a careless bump to `1.23.14` or `2.1.0`, both still in-range) FAILS
     with a pointer to the recipe.
   - the upgrade recipe `upgrades/uptime_kuma.yml` still targets `to: "2.2.1"` (the
     CVE-2026-33130 closer) — so the remediation path can't be deleted/weakened
     without tripping the gate.
   - the citation (`CVE-2026-33130` + `REM-073`) is present and consistent across
     `default.config.yml`, the role default, and the README — and the **wrong**
     `REM-067` citation is absent from the Kuma surfaces (anti-regression on the
     copy-paste bug).
   - REM-073 in the queue is `status: pending` AND its detail references the
     deferral/recipe (so flipping it to `resolved` without an actual bump, or
     deleting the deferral note, fails — the queue can't lie about being fixed).

4. **Operator runbook** (in the README security note + this plan §6) — the exact
   supervised command sequence to execute the real fix when the operator chooses
   to accept the breaking migration. This is the *only* path that flips REM-073 to
   resolved, and it is explicitly NOT run by the unsupervised agent.

### Why not just bump the pin to 2.2.1 now?

- `upgrades/uptime_kuma.yml` is explicit: **one-way SQLite schema migration on
  first 2.x boot, no downgrade path**, rollback only via pre-upgrade data-dir
  restore. That is a destructive-adjacent, supervised action — forbidden under the
  overnight no-live-mutation / trivially-reversible rule.
- Even as a *repo-only* pin bump (no live run), shipping `2.2.1` in
  `default.config.yml` would mean the **next** plain `ansible-playbook main.yml`
  re-render recreates the container on 2.x and silently triggers the irreversible
  migration with **no backup** (the plain render path does not run the recipe's
  `pre: backup_data_dir` step). That converts a documented supervised upgrade into
  an unguarded surprise. The recipe exists precisely so the backup + verify wrap
  the bump — the pin must move *via the recipe*, not ahead of it.
- Doctrine (`version-pins-default-config-shadow`, `upgrade-engine-apply-path`):
  applied upgrades bump the pin **after** a verified apply, not before.

---

## 4. Gate (pytest anatomy) — `tests/anatomy/test_uptime_kuma_ssti_pin.py`

Offline, no network, no Docker — pure file reads (same shape as
`test_mariadb_cve_citation_sync.py` / `test_postgresql_version_pin.py`).

```
ROOT/default.config.yml                       -> uptime_kuma_version pin + citation
ROOT/roles/pazny.uptime_kuma/defaults/main.yml-> role-default citation mirror
ROOT/roles/pazny.uptime_kuma/README.md        -> README security note + citation
ROOT/upgrades/uptime_kuma.yml                  -> recipe targets 2.2.1
ROOT/docs/llm/security/remediation-queue.json -> REM-073 pending + deferral ref
```

Test functions:

1. `test_config_pin_is_an_approved_value` — parse `uptime_kuma_version` from
   `default.config.yml`; assert it is EITHER the deferral pin `"1.23.13"` OR a
   version `>= 2.2.1` (the CVE-2026-33130 fix floor). Failure message names the
   recipe + this plan. This is the core anti-drift: a careless in-range bump fails.

2. `test_upgrade_recipe_targets_the_cve_fix` — load `upgrades/uptime_kuma.yml`
   (yaml), assert a recipe with `from_regex` matching `^1\.` has `to: "2.2.1"`
   (or higher) and `severity: breaking`. Pins the remediation path against
   deletion/weakening.

3. `test_cve_and_rem_citation_present_and_consistent` — `CVE-2026-33130` AND
   `REM-073` appear in all three text surfaces (config line, role default block,
   README). Mirrors the MariaDB 3-site sync gate.

4. `test_wrong_rem067_citation_absent_from_kuma_surfaces` — the string `REM-067`
   does NOT appear on any Kuma surface (config kuma line, role default, README,
   recipe notes). Anti-regression on the copy-paste bug; REM-067 is MariaDB's.

5. `test_queue_marks_rem073_pending_with_deferral_ref` — load the queue JSON,
   find `id == "REM-073"`; assert `status == "pending"` AND its
   `remediation_detail` (or a `deferral_ref` field) references either
   `uptime_kuma.yml` or this plan filename. Prevents a false `resolved` flip and
   prevents the deferral note from being silently dropped.

If the operator later runs the real upgrade and bumps the pin to `2.2.1`, tests
1–3 stay green (the `>= 2.2.1` branch), test 5's expectation flips to
`status == "resolved"` — at that point the gate's queue assertion is updated in
the same commit that records the resolution (one-line edit). The gate is written
so the *resolved* state is also expressible, not just the deferral.

### Suite must stay green

- Run the **full** `tests/anatomy/` suite, not just the new file — confirm the
  new citations don't trip `test_version_pin_no_shadow.py` (the `uptime_kuma`
  `INTENTIONAL_SHADOW` entry already covers config-patch / role-major).
- New var? **No.** This plan adds no new `default.config.yml` /
  `default.credentials.yml` variable, so `test_config_stock_jinja_only.py` is
  unaffected. (If a `deferral_ref` is added it's in the JSON queue, not a Jinja
  var — no stock-Jinja exposure.)

---

## 5. Risks

| Risk | Mitigation |
|------|-----------|
| Someone reads "1.23.13 pinned" as fully patched | The gate + README security note state explicitly it's *partial mitigation*; queue stays `pending`. |
| Future careless bump to another in-range 1.23.x | `test_config_pin_is_an_approved_value` fails on any value that isn't `1.23.13` or `>= 2.2.1`. |
| Plain `main.yml` re-render after an accidental 2.x pin triggers the irreversible migration with no backup | We deliberately do NOT bump the pin; the README/runbook routes the bump through the recipe (which takes the `pre: backup_data_dir`). |
| Citation fix introduces a NEW orphan (e.g. README cites a CVE config doesn't) | Test 3 asserts presence in all three surfaces; test 4 asserts the wrong ID is gone everywhere. |
| Queue summary already internally inconsistent (`by_status` resolved 72/pending 13 vs computed 73/12) | Out of scope — do NOT recompute the summary in this task; only edit the REM-073 item body. Note it for a separate cleanup. |
| Regex pin-parse brittle to quoting/comments | Reuse the proven `^uptime_kuma_version:\s*["\']?...` pattern style from the existing pin gates; anchor `^` + `re.M`. |

---

## 6. Verification recipe

All steps are repo-only / read-only. No playbook apply, no live mutation.

```bash
cd /Users/pazny/projects/nOS

# 1. New gate passes
python3 -m pytest tests/anatomy/test_uptime_kuma_ssti_pin.py -q

# 2. Full anatomy suite stays green (esp. the version-pin + mariadb-citation gates)
python3 -m pytest tests/anatomy/ -q

# 3. Playbook still parses
ansible-playbook main.yml --syntax-check

# 4. Citation drift is gone — wrong REM-067 must NOT appear on any Kuma surface
grep -RIn "REM-067" default.config.yml upgrades/uptime_kuma.yml \
    roles/pazny.uptime_kuma/ ; echo "exit=$? (1 = clean: no matches)"

# 5. The real fix target still lives in the recipe
grep -n 'to: "2.2.1"' upgrades/uptime_kuma.yml

# 6. The live pin is untouched (still the deferral value, NOT bumped by this task)
grep -n 'uptime_kuma_version:' default.config.yml roles/pazny.uptime_kuma/defaults/main.yml
```

### Live read-only spot-check (optional, informational only)

```bash
# What image is actually running right now (confirms the vulnerable 1.x pin)
docker inspect iiab-uptime-kuma-1 --format '{{.Config.Image}}' 2>/dev/null || true
```

### Operator-only supervised remediation (NOT run by the agent)

This is the path that actually closes REM-073. Run it yourself, watching the
output, when you accept the breaking 1.x→2.x migration:

```bash
# Recipe takes a data-dir backup, bumps to 2.2.1, waits for the schema migration,
# verifies the running image. Rollback = restore the pre-upgrade data dir.
ansible-playbook main.yml --tags upgrade -e upgrade_service=uptime_kuma

# After a VERIFIED apply, in a follow-up commit:
#   - bump uptime_kuma_version "1.23.13" -> "2.2.1" in default.config.yml
#   - flip REM-073 status pending -> resolved (resolved_by/resolved_at)
#   - update test 5's expected status to "resolved"
```

---

## 7. Commit (this plan only)

```
docs(plan): REM-073 kuma SSTI deferral + citation fix

- CVE-2026-33130 needs 2.2.1 (breaking 1.x->2.x) — supervised only
- plan pins citation truth (wrong REM-067 -> REM-037/REM-073)
- gate keeps pin in {1.23.13, >=2.2.1}, recipe target, queue=pending
- real fix = upgrades/uptime_kuma.yml, NOT the overnight run
```

Lands on `feat/v0.7-overnight` only. No push.
