# v0.7 — ansible-core 2.24 jump (Darwin 27 forward horizon)

Status: PLAN (not implemented). Target branch: `feat/v0.7-overnight`.
Owner: overnight agent batch. Scope: repo edits + offline gates only — **no live
mutation, no blank, no playbook apply.** The actual 2.24 cutover wet-test is an
explicit *supervised* lane (see §8); tonight ships the repo-side scaffolding +
gates that make that cutover a ~half-day flip instead of a multi-cycle saga.

---

## 1. Problem / why

CLAUDE.md "Known Tech Debt" pins the operator + CI baseline at **ansible-core
2.20.5** (CI integration mirror at **2.21.0**, frozen in `tools/ci-freeze.env`).
The same entry frames the **2.24 jump** as "a single `requirements.yml` floor bump
+ collection version review + 1 blank — ~4 hours, not a Track" — **except** for one
structural blocker it lists separately: `{{ vars }}` is **removed in ansible-core
2.24**, and nOS hands the whole `vars` dict to custom modules in 7 live call sites.

So the 2.24 jump is really **two coupled pieces**:

- **Piece A — the `{{ vars }}` cutover.** Already owned by a sibling plan
  (`docs/plans/v07-vars-retirement-d1-jinja-legacy.md`, roadmap O25). **Out of
  scope here** — this plan treats it as a hard *dependency* and does not touch the
  7 call sites.
- **Piece B — everything else the floor bump touches** (this plan): the
  version-pin surface, collection ceilings, the custom-module / plugin import
  audit against 2.24's removed-symbol list, the frozen-toolchain re-pin, and the
  CI matrix story. Today this is scattered across `requirements.yml`,
  `requirements.lock.yml`, `tools/ci-freeze.env`, **72 `roles/*/meta/main.yml`
  floors**, `.python-version`, and the CI workflow comments — with **no gate that
  asserts these stay coherent** and **no breadcrumb of which symbols 2.24 removes
  that nOS actually imports**.

Why it is debt, not a feature:

1. **The jump will be attempted under time pressure** (when upstream ships 2.24
   stable, or when a CVE forces it). The v0.5-beta saga (CI red, ~21 cycles, memory
   `ci-diagnose-by-comparison`) is the cost of an ansible-core transition with **no
   pre-staged audit and no comparison harness**. The 2.21 mirror exists *because*
   of that saga; 2.24 deserves the same scaffolding **before** it is urgent.
2. **The floor surface is internally inconsistent and ungated.** 72 role
   `meta/main.yml` files pin `min_ansible_version: "2.20"`; `requirements.yml`
   carries human floors+ceilings aligned to "2.20.x / 2.21"; `requirements.lock.yml`
   freezes exact collection versions; `tools/ci-freeze.env` pins ansible-core
   `2.21.0` + Python `3.13.13`; `.python-version` pins `3.13.13`. Nothing checks
   that these five surfaces agree, so a bump that edits one and forgets another
   ships green and breaks a blank.
3. **No removed-symbol inventory.** The whole v0.5 saga was a *removed/added symbol*
   problem (`VaultDecryptionContext` added in 2.21). 2.24 removes a known set
   (`{{ vars }}` magic var, `with_*` bare loops in some contexts, several
   `ansible.utils`-era deprecations, `paramiko_ssh` defaults, etc.). nOS has **no
   committed list** of which of those it actually imports/uses, so the audit gets
   redone from scratch under pressure every time.
4. **Darwin 27 horizon couples in.** The 2.24 jump and the Darwin-27 / macOS-28
   forward horizon land in the same v0.7 window (see the `v07-darwin27-*` plan
   series). The CI integration matrix currently tests `macos-14`/`macos-15`; a 2.24
   bump needs the matrix + the frozen Python (`3.13.13`, chosen because 3.14 broke
   2.20.x filter imports) reconsidered together, because **2.24 may require / unlock
   a newer Python**, and a newer macOS runner image may ship a newer framework
   Python. This plan keeps that coupling explicit so the two epics don't silently
   regress each other.

This plan ships **the audit + the coherence gate + the staged re-pin scaffolding**
tonight (repo-only, fully reversible), so that when 2.24 is pulled the operator
edits *one documented set of pins*, runs the comparison harness, and the gate
proves coherence — no archaeology.

---

## 2. Scope — what this plan does and does NOT do

**In scope (ship tonight, repo-only):**

- A **version-pin coherence gate** (`tests/anatomy/test_ansible_core_pin_coherence.py`)
  that asserts the five pin surfaces agree on a single declared baseline +
  ceiling, and that no role floor exceeds the declared baseline.
- A committed **2.24 removed/changed-symbol audit** at
  `docs/ansible-core-2.24-audit.md` — a table of every 2.24 removal/behaviour-change
  cross-referenced against an automated grep of the nOS tree (custom modules,
  module_utils, callback/filter plugins, tasks, templates), with a verdict
  (used / not-used / handled-by-sibling-plan) per row.
- A **single source-of-truth baseline var** so the gate has something to compare
  against — `state/ansible-baseline.yml` (committed): `ansible_core_baseline`,
  `ansible_core_ceiling`, `python_baseline`, plus a `darwin_kernel_validated`
  breadcrumb tying into the Darwin-27 plan series.
- The **staged 2.24 pin diff, written but commented/guarded** — i.e. the exact
  edits the operator will make, captured in the audit doc as a copy-paste block,
  NOT applied. Pins stay at 2.20.5 / 2.21.0 tonight.
- Doc updates: CLAUDE.md "Known Tech Debt" entry refined to point at this plan +
  the audit + the gate; `RELEASE.md` / `docs/active-work.md` breadcrumb.

**Explicitly OUT of scope (do NOT do tonight):**

- **Bumping any pin to 2.24.** The floor stays 2.20.5; the CI mirror stays 2.21.0.
  Tonight is scaffolding, not the jump.
- **The `{{ vars }}` cutover** — owned by `v07-vars-retirement-d1-jinja-legacy.md`.
  This plan *references* it as the gating blocker and must not edit the 7 call
  sites or the comment sites (`tasks/tofu-authentik.yml:67`,
  `roles/pazny.traefik/tasks/main.yml:44`).
- **Any blank / playbook apply / live mutation.** The 2.24 wet-test is the
  supervised cutover lane in §8.
- **Editing `.python-version` to a Python that 2.20.5 can't load** — the Python
  3.14 trap (filter-plugin import break under 2.20.x) is a hard rule until the
  baseline itself moves.

---

## 3. Exact files / roles to touch

| # | File | Change | Risk |
|---|------|--------|------|
| 1 | `state/ansible-baseline.yml` (**new**) | Single SoT for `ansible_core_baseline: "2.20.5"`, `ansible_core_ceiling: "<2.24"` (the 2.21 mirror noted), `python_baseline: "3.13.13"`, `darwin_kernel_validated: "25.3.0"`. Pure data, NOT loaded by the playbook (avoid the `{{ vars }}` eager-resolve namespace — see §6). | LOW |
| 2 | `tests/anatomy/test_ansible_core_pin_coherence.py` (**new**) | The coherence gate (§5). Parses the five surfaces, asserts agreement. Offline, no ansible import required. | LOW |
| 3 | `docs/ansible-core-2.24-audit.md` (**new**) | The removed-symbol audit table + the staged (un-applied) 2.24 pin diff block + the comparison-harness recipe. | LOW |
| 4 | `tools/ci-freeze.env` | **Comment-only** addition: a `# 2.24 staging:` block documenting the next-baseline pins (commented, not active). No active value changes. | LOW |
| 5 | `requirements.yml` | **Comment-only** refinement of the existing "When ansible-core 2.24 ships…" note to point at the audit doc + this plan. No range changes. | LOW |
| 6 | `CLAUDE.md` | Refine the "ansible-core 2.24 jump (future)" tech-debt bullet to cite the audit doc + the gate + the sibling `{{ vars }}` plan as the structural blocker. | LOW |
| 7 | `docs/active-work.md` / `RELEASE.md` | One-line breadcrumb: "2.24 jump pre-staged (audit + coherence gate), cutover is a supervised lane." | LOW |

**Roles touched:** none functionally. The gate *reads* all 72 `roles/*/meta/main.yml`
floors but does not edit them tonight (the floor bump to a 2.24-aware value is a
mechanical sed in the supervised cutover — §8 — and is what the gate will then
enforce). No compose template, no task file, no plugin manifest changes.

---

## 4. Approach

### 4.1 Establish the single source of truth (file 1)

`state/ansible-baseline.yml` declares the baseline/ceiling/python triple **once**.
Every other surface (CI workflow, freeze env, requirements, role floors) is then
checked *against* it by the gate. This inverts today's "five places, no referee"
into "one referee, five followers." It is plain data — deliberately NOT consumed by
`main.yml` or any role, because anything that lands in the play-var namespace gets
eager-resolved by the `{{ vars }}` loader (CLAUDE.md stock-Jinja trap). It is read
only by the pytest gate and humans.

### 4.2 The 2.24 removed-symbol audit (file 3)

Build `docs/ansible-core-2.24-audit.md` as a table. Source the 2.24 removal list
from upstream porting guides (the audit doc records the exact changelog refs).
For each removal, run a committed grep recipe against the nOS tree and record the
verdict. Known rows to cover (the audit doc finalizes them):

- **`{{ vars }}` magic var (removed 2.24)** → USED in 7 sites → **handled by
  `v07-vars-retirement-d1-jinja-legacy.md`** (this is the gating blocker; the audit
  row links to it and does NOT re-solve it).
- **`ansible_env` → `ansible_facts['env']`** → already migrated (Track J Phase 4);
  audit confirms zero residual `ansible_env` refs (grep already clean — verified:
  all hits are `ansible_facts['env']`).
- **Custom-module / plugin imports against removed private symbols** — audit each
  of `files/anatomy/library/nos_{state,migrate,authentik,coexistence,plugin_loader,apps_render}.py`,
  `files/anatomy/module_utils/*`, `callback_plugins/wing_telemetry.py`,
  `filter_plugins/nos_tofu_guard.py` for imports from `ansible._internal`,
  `ansible.utils.*` deprecated paths, `ansible.module_utils._text`,
  `ansible.parsing.yaml` private classes, etc. Record file:line + verdict.
- **`with_*` bare-loop / `lookup` plugin signature changes**, **`paramiko`/connection
  default shifts**, **jinja2 native-type defaults** — verdict each.

The audit doc is the artifact that turns the next jump from "rediscover the blast
radius" into "execute the table." It pairs with the comparison-harness recipe (§7)
so a CI-red is diagnosed by *comparing the two ansible versions' symbol surface*,
not by hypothesizing (memory `ci-diagnose-by-comparison`).

### 4.3 Stage (don't apply) the 2.24 pin diff (file 3 + commented files 4/5)

The audit doc carries a fenced, copy-paste **"Cutover diff"** block: the precise
edits to `tools/ci-freeze.env` (`NOS_ANSIBLE_CORE`, maybe `NOS_PYTHON_VERSION`),
`requirements.yml` ceilings, `requirements.lock.yml` (re-resolved via
`tools/ci-local.sh --refresh-lock`), `.python-version`, the 72 role floors (one
sed), `state/ansible-baseline.yml`, and the CI workflow's `<2.20.6` /
`ansible-core==2.21.0` pins. Files 4/5 get **commented** stub lines pointing at it.
Nothing is activated — the diff is documentation until the supervised cutover.

### 4.4 Darwin-27 coupling

`state/ansible-baseline.yml` carries `darwin_kernel_validated` so the 2.24 jump and
the Darwin-27 horizon (`v07-darwin27-version-gate-coverage.md`) share one validated
marker. The audit doc's §"Platform coupling" notes: if the 2.24 jump lands on a
newer macOS runner image (which may ship a newer framework Python), re-verify the
custom-module interpreter path — that path is *already* `continue-on-error` on
macOS integration (CLAUDE.md), so the **Linux integration job remains the gating
wet-test** for the 2.24 cutover too.

---

## 5. Gates it needs (the must-gate rule)

Every artifact tonight is offline-testable. The binding gate:

**`tests/anatomy/test_ansible_core_pin_coherence.py`** (new). Pure-Python, no
ansible import, runs in the existing pytest CI job. Assertions:

1. `state/ansible-baseline.yml` parses and carries the four required keys with
   non-empty string values matching expected shapes
   (`^\d+\.\d+\.\d+$` for the cores/python, `^<?\d+\.\d+` for the ceiling).
2. `tools/ci-freeze.env` `NOS_ANSIBLE_CORE` == `ansible-core==<baseline-mirror>`
   and `NOS_PYTHON_VERSION` == `python_baseline`. (Today: mirror is 2.21.0,
   baseline is 2.20.5 — the gate encodes that the mirror is the *ceiling-side*
   pin and must satisfy `< ceiling`.)
3. `.python-version` == `python_baseline`.
4. `requirements.yml` collection ranges all carry an explicit upper bound (no
   unbounded `>=`), and the human-facing floor note references the baseline.
5. **No `roles/*/meta/main.yml` `min_ansible_version` exceeds the baseline.** (All
   72 read `"2.20"` today → passes; this is the assertion that will *enforce* the
   floor bump is applied uniformly during the cutover — a half-swept sed fails it.)
6. `requirements.lock.yml` exact pins are all `==`-shaped (no ranges leaked into
   the lock) and every collection in `requirements.yml` has a lock entry.

The gate **fails loud** if any surface drifts — that is the whole point: it makes
the cutover diff atomic.

Supporting / unchanged gates that must stay green:

- `tests/anatomy/test_config_stock_jinja_only.py` — the `{{ vars }}` stock-filter
  trap (this plan adds a *data* file, not a play-var; confirm it doesn't register).
- `tests/anatomy/test_version_pin_no_shadow.py` — version-pin shadow gate.
- Full suite: `python3 -m pytest tests/ --ignore=tests/wing-api
  --ignore=tests/wing-frontend --ignore=tests/e2e -q`.
- `ansible-playbook main.yml --syntax-check` clean (no functional change → must
  stay clean; the new YAML data file is not in the playbook load path).

---

## 6. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| New `state/ansible-baseline.yml` accidentally enters the play-var namespace → eager-resolved by `{{ vars }}` loader → could re-trigger the stock-Jinja trap | LOW | It is NOT in `vars_files`, NOT loaded by any role; it carries only literal strings (no Jinja, no filters). Gate + a grep assertion that it is referenced by zero `vars_files:`/`include_vars:`. |
| Gate encodes the *current* (2.20.5/2.21.0) pins as constants → goes red the moment the real cutover edits them | This is **intended** — the gate reads the baseline FROM `state/ansible-baseline.yml`, not from hardcoded constants, so a coherent cutover (bump baseline + all followers together) stays green; an incoherent one fails. | Gate derives expected values from the baseline file, never hardcodes 2.20/2.21. |
| Audit doc goes stale vs upstream 2.24 changelog | MED | Doc records the exact changelog refs it was built from + a "last-reviewed" date; the cutover lane re-checks before applying. Not a code gate (doc-only), flagged as such. |
| Scope creep into the `{{ vars }}` cutover | MED | Hard rule: this plan does not touch the 7 call sites or the 2 comment sites. Audit row for `{{ vars }}` only *links* to the sibling plan. |
| 72-file role-floor assertion is slow / flaky | LOW | One `glob` + cheap YAML parse per file (~72 small files), runs in <1s like the existing meta-reading gates. |
| Darwin-27 / 2.24 double-bump conflates two epics in one cutover | MED | The two stay separate branches/lanes; `darwin_kernel_validated` is a shared *read-only marker*, not a coupling that forces simultaneity. |

---

## 7. Comparison harness (the anti-saga tool)

The audit doc ships a recipe (NOT run tonight — documented for the cutover lane)
that, given two ansible-core versions, diffs their importable-symbol surface so a
CI-red is diagnosed by comparison, per memory `ci-diagnose-by-comparison`:

```bash
# Run in the supervised cutover lane only. Builds two throwaway venvs and diffs
# the private-symbol surface the nOS tree imports, BEFORE running any playbook.
tools/ci-local.sh --refresh-lock        # re-resolve collections for the new core
# then: for each import the audit lists, probe it under both cores:
#   python -c 'import ansible._internal._yaml._dumper as m; print(dir(m))'
# diff the two → any symbol nOS imports that vanished in 2.24 is the blast radius.
```

This is the tool that would have collapsed the v0.5 21-cycle saga to ~1. It is
documented now so it exists *before* it is needed.

---

## 8. Verification recipe

**Tonight (offline, what the overnight run must prove):**

```bash
# 1. The new coherence gate passes against the current (un-bumped) pins.
python3 -m pytest tests/anatomy/test_ansible_core_pin_coherence.py -v

# 2. Full anatomy suite stays green.
python3 -m pytest tests/ --ignore=tests/wing-api \
  --ignore=tests/wing-frontend --ignore=tests/e2e -q

# 3. Syntax-check unaffected (new data file is not in the load path).
ansible-playbook main.yml --syntax-check

# 4. The new baseline file is referenced by ZERO playbook load sites.
grep -rn "ansible-baseline" main.yml tasks/ roles/*/tasks/ roles/*/vars/ \
  roles/*/defaults/ && echo "FAIL: in load path" || echo "OK: data-only"

# 5. No 2.24 pin was actually applied (floor still 2.20.5, mirror still 2.21.0).
grep -E '2\.20\.5|2\.21\.0' tools/ci-freeze.env requirements.lock.yml
grep -c '"2.20"' <(grep -rh min_ansible_version roles/*/meta/main.yml)  # == 72
```

**The supervised 2.24 cutover lane (NOT tonight — for the operator, later):**

1. Apply the audit doc's "Cutover diff" block (bump baseline + all five follower
   surfaces + the 72 role floors via one sed, together).
2. `tools/ci-local.sh --refresh-lock` → re-pin `requirements.lock.yml`.
3. `tools/ci-local.sh` → frozen-venv filter-load probe + syntax-check on 2.24.
4. Run the comparison harness (§7); resolve any removed-symbol hit per the audit.
5. Confirm the sibling `{{ vars }}` cutover has landed (hard dependency).
6. `tools/ci-local.sh ansible-playbook main.yml` → full frozen-env wet-test.
7. One real blank on the reference host (operator-supervised) → `failed=0`,
   idempotence re-run `changed=0`.
8. The coherence gate must be green post-cutover (proves the bump was atomic).

---

## 9. Commit shape

Conventional Commits, surgeon-tone, ≤6 bullets, no Co-Authored-By, no `--author`,
land on `feat/v0.7-overnight` only (never push). Suggested:

```
docs(plan): stage the ansible-core 2.24 jump

- audit + coherence gate so the floor bump is atomic, not a saga
- single baseline SoT (state/ansible-baseline.yml) refs 5 pin surfaces
- {{ vars }} removal is the gating blocker → sibling D1 plan owns it
- cutover stays a supervised wet-test lane; tonight is repo-only
```

(The plan doc itself is committed under `docs(plan):`; the *implementation* —
the gate + baseline file + audit doc — is a separate follow-up commit when this
plan is executed, not tonight.)
