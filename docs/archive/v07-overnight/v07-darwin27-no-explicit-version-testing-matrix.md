# v0.7 — Darwin 27: no explicit-version testing matrix

Status: PLAN (not implemented). Target branch: `feat/v0.7-overnight`.
Owner: overnight agent batch. Scope: **repo edits only, no live mutation** —
CI workflow + an offline anatomy gate. No playbook run, no live system change.

## Problem / why

nOS pins **every layer it controls** — service image tags, the Ansible toolchain
(`tools/ci-freeze.env` pins `ansible-core==2.21.0`, `requirements.lock.yml` pins
collections exactly), the host Python (`.python-version` → 3.13.13). The
**glaring exception is the macOS version the CI matrix actually tests against.**
`.github/workflows/ci.yml` runs its Darwin jobs on **floating runner labels**:

| Job | Runner labels (today) | File |
|---|---|---|
| `syntax` (Syntax Check) | `macos-14` | `.github/workflows/ci.yml:79` |
| `integration` (macOS wet-test) | `macos-15`, `macos-14` | `.github/workflows/ci.yml:268-269` |

These labels are **GitHub-owned aliases that roll forward without a repo change.**
`macos-14` / `macos-15` are major-version aliases that GitHub silently re-points
to a newer **minor/patch** image on its own cadence; when a new macOS major ships,
GitHub adds `macos-26` (and eventually re-points `macos-latest`), and at deprecation
it **removes** an old alias — at which point a job pinned to `macos-14` either jumps
to a substituted image or hard-errors `"no runner matching the labels"`. Either way
the **OS the wet-test ran on is not recorded anywhere in the repo**, and it changes
underneath us.

This is precisely the failure shape the **2026-06-08 frozen-venv saga** taught us
to refuse: *"a patch-level bump flipped CI red with zero repo change"* (CLAUDE.md
tech-debt + memory `ci-diagnose-by-comparison`). That saga was an ansible-core
patch float; the **runner-OS float is the same anti-pattern one layer down** — and
it is *worse* because the OS version isn't even visible in the diff. We froze the
toolchain 1:1; we never froze the **platform under test**.

Three concrete gaps:

1. **No recorded "what OS did the wet-test actually run on."** When `integration`
   goes green, nothing in the repo says whether it ran on macOS 14.5 or 15.2. A
   reviewer can't tell from the diff, and a regression that only reproduces on one
   macOS major is invisible until it's the *only* alias left.

2. **No forward-horizon job for the next macOS major.** The Darwin-27 sibling plans
   (`v07-darwin27-launchd-plist-schema.md`, `v07-darwin27-softwareupdate-script.md`,
   `v07-darwin27-version-gate-coverage.md`) all de-risk the **operator's** OS bump
   to macOS 27 / Darwin 27. But **CI never proves nOS on a newer macOS major before
   the operator gets there.** GitHub already offers `macos-26` runners (the macOS 26
   image — the live reference host's OS, Darwin 25). The matrix doesn't test it, so
   "validated on macOS 26" is an *operator claim*, not a CI fact. When `macos-15`
   is deprecated and removed, the matrix silently narrows to a single alias with no
   newer-major coverage queued.

3. **No gate pins the macOS matrix at all.** `test_ci_integration_timeout.py` pins
   `timeout-minutes`; `test_ci_pipeline.py` pins the Woodpecker step shape;
   `test_pages_workflow_action_versions.py` pins action SHAs. **Nothing pins which
   `runs-on` labels the Darwin jobs use** — so a future edit can drop, float, or
   typo the macOS matrix and no gate complains. The CI surface that proves the whole
   macOS product is itself unpinned.

This is a **CI-posture / forward-horizon** item, sibling to the toolchain freeze
(`tools/ci-freeze.env`) and the Darwin-27 cluster. It makes "which macOS we test"
**explicit, gated, and forward-looking** instead of a silently-floating GitHub alias.

### Explicitly out of scope (so the change doesn't over-reach)

- **The playbook itself.** This is a CI-workflow + gate change only. The
  operator-facing macOS floor/arch gate lives in the sibling
  `v07-darwin27-version-gate-coverage.md` (the runtime `preflight-platform.yml`);
  this plan is about **what GitHub Actions tests**, not what the playbook asserts on
  the operator's host. Keep the two diffs independent.
- **Linux runners.** `ubuntu-22.04` / `ubuntu-24.04` are already **explicit numeric
  labels** (not `ubuntu-latest` for the gating jobs) and Ubuntu is a first-class
  platform with its own wet-test. The `syntax` job's Ubuntu legs and
  `integration-linux` (`ubuntu-24.04`) stay byte-unchanged. The gate asserts the
  *Darwin* legs are explicit; it must **not** churn the Linux matrix.
- **`macos-latest`.** We deliberately do **not** adopt `macos-latest` — that is the
  *maximally*-floating alias and the exact thing this plan removes. Forward coverage
  comes from an **explicitly-named newer-major job** (`macos-26`), not `latest`.
- **`continue-on-error` on the macOS integration job.** That non-blocking posture
  (CLAUDE.md: the GitHub-macOS-runner custom-module interpreter quirk) is a separate
  concern and stays exactly as-is. Adding a newer-major leg must **inherit the same
  `continue-on-error: true`** so a brand-new macOS image's flakiness can never gate
  a release (mirrors the existing macOS non-blocking doctrine).
- **Self-hosted runner.** A truly version-frozen macOS environment needs a
  self-hosted runner (already a deferred CLAUDE.md item). This plan does the
  *achievable* freeze on hosted runners — explicit numeric aliases + a documented
  bump ritual — and leaves the self-hosted pin as the noted follow-up.

## Approach

Three coordinated edits, all in `.github/workflows/ci.yml`, plus one offline gate
and a doc breadcrumb. The throughline: **name the macOS major explicitly, add a
forward-horizon leg, and pin the whole thing with a gate** — exactly the
`ci-freeze.env` philosophy applied to the runner OS.

### 1. Make the macOS matrix legs explicit + add the forward-horizon leg

**`syntax` job** (`.github/workflows/ci.yml:76-79`) — keep `macos-14` but make the
intent explicit via a comment, OR (preferred) bump to the validated reference-OS
alias so the static syntax-check runs on the same major the operator runs
(`macos-15` is the current Sequoia alias; the live host is macOS 26 → `macos-26`).
The syntax job is cheap and blocking, so it should run on the **last-validated**
major, not the oldest-supported. Recommended matrix:

```yaml
os:
  - ubuntu-22.04
  - ubuntu-24.04
  - macos-15          # was macos-14 — last-validated Sequoia; explicit, not floating
```

**`integration` job** (`.github/workflows/ci.yml:264-269`) — this is the wet-test
matrix. Today `[macos-15, macos-14]` (newest + one-back). Reshape to **anchor +
forward horizon**:

```yaml
strategy:
  fail-fast: false
  matrix:
    os:
      - macos-15      # anchor: last fully-validated major (Sequoia)
      - macos-26      # FORWARD HORIZON: next major GitHub offers (macOS 26 / Darwin 25,
                      #                  the live reference host's OS). Proves nOS on the
                      #                  newer macOS BEFORE the operator's bump. Inherits
                      #                  continue-on-error: true (non-blocking, like all
                      #                  macOS legs) so a new-image quirk can't gate a release.
```

Rationale for dropping `macos-14` from the *wet-test* matrix and adding `macos-26`:
the value of a third macOS leg is **forward** coverage (catch the next-major
regression early — the whole Darwin-27 theme), not **backward** coverage of an
older major that is already `continue-on-error` and that the floor gate
(`v07-darwin27-version-gate-coverage.md`, floor = macOS 14) keeps *supported* but
not *primary-tested*. Two legs (anchor + horizon) keep the matrix cost flat while
shifting coverage to where the risk is. **If review prefers to keep `macos-14`**,
the alternative is a 3-leg `[macos-15, macos-14, macos-26]` — the gate (below) is
written to accept either shape as long as (a) every leg is an explicit numeric
alias and (b) at least one leg is ≥ the recorded "newest tested" horizon.

**Single source of truth for "what we validate against":** introduce one workflow
comment block (top of the `integration` job) that names the **anchor** and
**horizon** macOS majors in prose, so the diff records the decision:

```yaml
  # macOS validation matrix (v0.7 Darwin-27 horizon):
  #   anchor  = macos-15 (Sequoia, last fully-validated major)
  #   horizon = macos-26 (next major GitHub offers; the live reference host's OS)
  # Bump BOTH when a newer macOS major is wet-tested green; never use macos-latest
  # (floats silently — the exact anti-pattern tools/ci-freeze.env exists to kill).
  # Pinned by tests/anatomy/test_ci_macos_matrix_explicit.py.
```

### 2. (Optional, recommended) Tie the matrix to `ci-freeze.env`

`tools/ci-freeze.env` is already the toolchain SoT. Add **two documentation-only**
variables there so the macOS validation horizon lives beside the ansible-core pin:

```sh
# Darwin/macOS validation horizon (v0.7) — the macOS majors the CI wet-test
# matrix runs on. Documentation/SoT for tests/anatomy/test_ci_macos_matrix_explicit.py;
# the actual runner labels live in .github/workflows/ci.yml (GitHub needs literal
# labels in the matrix). Bump together with the ci.yml matrix + the operator-side
# nos_macos_validated_version (default.config.yml). macOS N == Darwin (N-1).
NOS_MACOS_ANCHOR="15"     # Sequoia — last fully-validated major
NOS_MACOS_HORIZON="26"    # next major GitHub offers; live reference host OS (Darwin 25)
```

These are **shell vars in a `.env`, not Ansible vars** — they never enter the
`{{ vars }}` core-up namespace, so the stock-Jinja trap does **not** apply (that
trap is specific to `default.config.yml` / `default.credentials.yml`). The gate
cross-checks these against the literal labels in `ci.yml` so the two can't drift.
**If review judges this over-engineered**, drop the `ci-freeze.env` additions and
let the gate read the horizon directly from the `ci.yml` comment block — the gate
section below notes both options.

### 3. Doc breadcrumb

- **`docs/linux-port.md`** (or a one-paragraph note where the CI matrix is
  discussed) — one paragraph: *"The macOS CI legs use explicit numeric runner
  aliases (anchor + forward-horizon major), never `macos-latest`. Bump the
  `integration`/`syntax` matrix + `NOS_MACOS_ANCHOR`/`NOS_MACOS_HORIZON` together
  when a newer macOS major is wet-tested green, and keep them in step with
  `nos_macos_validated_version` (`default.config.yml`)."*
- **CLAUDE.md** — extend the existing frozen-toolchain caveat with one sentence: the
  macOS matrix is now explicit-major + forward-horizon, pinned by
  `test_ci_macos_matrix_explicit.py` (so the platform-under-test joins the frozen
  toolchain instead of floating).

## Files to touch

- `.github/workflows/ci.yml` — **edit** the `syntax` matrix `os:` Darwin leg
  (`L79`) and the `integration` matrix `os:` (`L268-269`) to explicit numeric
  aliases + forward-horizon leg + the SoT comment block. **Ubuntu legs +
  `integration-linux` untouched.**
- `tools/ci-freeze.env` — **(optional)** add `NOS_MACOS_ANCHOR` /
  `NOS_MACOS_HORIZON` doc-vars (shell, not Ansible).
- `tests/anatomy/test_ci_macos_matrix_explicit.py` — **new gate** (below).
- `docs/linux-port.md` — **1 paragraph** on the explicit-major CI policy.
- `CLAUDE.md` — **1 sentence** extending the frozen-toolchain note.

## Gates it needs

New `tests/anatomy/test_ci_macos_matrix_explicit.py` — **offline, source-level**
(parse `ci.yml` as YAML, no Actions run, no live runner), mirroring
`test_ci_integration_timeout.py` exactly (load `data["jobs"]`, assert on the matrix
maps). Assertions:

1. **`test_ci_workflow_present_and_parses`** — `ci.yml` loads as a dict with a
   `jobs` map containing `syntax` and `integration` (precedent: the timeout gate's
   first test).

2. **`test_macos_legs_are_explicit_numeric_aliases`** — for every `runs-on` /
   `matrix.os` entry in `syntax` and `integration` that starts with `macos-`, assert
   the suffix is **numeric** (`macos-15`, `macos-26`), i.e. **reject `macos-latest`**
   and any non-numeric alias. This is the load-bearing pin: the floating alias can
   never reappear. (Regex: `^macos-\d+$`.)

3. **`test_no_macos_latest_anywhere`** — belt-and-suspenders: the literal string
   `macos-latest` appears **nowhere** in `ci.yml` (full-text scan). Cheap, blunt,
   catches a `runs-on: macos-latest` snuck into a future job outside the two matrices.

4. **`test_integration_has_forward_horizon_leg`** — the `integration` matrix `os:`
   list contains **at least two** distinct `macos-N` legs, and the **highest** macOS
   major present is **≥ the recorded horizon** (`NOS_MACOS_HORIZON` from
   `ci-freeze.env` if adopted, else a constant in the test parsed from the SoT comment
   / a module constant). Pins the "forward coverage exists and doesn't regress below
   the horizon" contract — the core Darwin-27 value.

5. **`test_ubuntu_matrix_untouched`** — assert the `syntax` matrix still contains
   `ubuntu-22.04` **and** `ubuntu-24.04`, and `integration-linux` still
   `runs-on: ubuntu-24.04`. The Linux-safety pin (this Darwin change must not churn
   the supported-Linux matrix), symmetric to the sibling plans' "Linux byte-inert"
   gate test.

6. **`test_horizon_leg_inherits_non_blocking`** *(only if the horizon leg is added to
   the existing `integration` job — which it is)* — assert the `integration` job
   carries `continue-on-error: true`, so the newer-major leg is non-blocking by
   construction (it shares the job's setting). Pins the "a new macOS image's
   flakiness can't gate a release" doctrine. (If a *separate* horizon job were ever
   used instead of a matrix leg, this test asserts that job is non-blocking.)

7. **`test_freeze_env_horizon_matches_ci`** *(only if §2 adopted)* — parse
   `NOS_MACOS_ANCHOR` / `NOS_MACOS_HORIZON` out of `tools/ci-freeze.env` and assert
   both majors appear as legs in the `integration` matrix. The anti-drift pin so the
   `.env` SoT and the literal `ci.yml` labels can't diverge. (Drop this test if §2
   is not adopted.)

The suite must stay green and `ansible-playbook main.yml --syntax-check` must pass
(this change touches **no** playbook YAML — the syntax-check is unaffected, asserted
green as a no-regression check, not because the change could break it).

## Risks

- **`macos-26` runner availability / image churn.** GitHub may label the macOS 26
  image differently, mark it beta, or not have GA capacity in all regions. Mitigated
  by: the horizon leg **inherits `continue-on-error: true`** (it can't gate a
  release), and if the label doesn't exist the job errors *non-blockingly* — a loud,
  visible "horizon image not yet available" signal, which is itself useful data, not
  a red release. **Mitigation if the label is wrong at authoring time:** verify the
  exact current GitHub-hosted macOS labels (`actions/runner-images` README) before
  committing the literal — the plan names `macos-26` as the *live reference host's
  major*, but the implementer MUST confirm the runner alias exists and substitute the
  correct one (e.g. `macos-15` stays the anchor if `macos-26` isn't yet offered, and
  the horizon becomes whatever the newest offered alias is). The gate's
  "highest-major ≥ horizon" shape tolerates the implementer picking the
  newest-actually-available alias.

- **Dropping `macos-14` from the wet-test matrix reduces backward coverage.** Real
  but acceptable: macOS 14 stays *supported* (floor = 14 in the sibling version-gate
  plan) and the matrix's older leg was already `continue-on-error` (non-gating). The
  coverage shifts from "old major we no longer primarily ship on" to "new major we're
  about to ship on" — strictly better risk allocation. **If review disagrees**, the
  3-leg shape (`macos-15, macos-14, macos-26`) preserves backward coverage at one
  extra runner's cost; the gate accepts it.

- **Matrix-leg removal could trip branch-protection required-status-checks.** If
  `Integration (macos-14)` is a *named required check* in branch protection, removing
  that leg leaves the rule waiting on a check that never reports → a stuck merge.
  **Mitigation:** this is a GitHub-settings concern, not a repo edit; flag it in the
  PR description so the operator updates required-checks (or, safer, keep the 3-leg
  shape so no existing check name disappears). The macOS integration job is
  `continue-on-error` and the **Linux** job is the gating wet-test (CLAUDE.md), so it
  is unlikely a macOS leg is a *required* check — but verify before merge.

- **`ci-freeze.env` shell-var additions breaking the sourcing.** The `.env` is
  `source`d by `tools/ci-local.sh` and the integration jobs. New `NOS_MACOS_*`
  vars are inert plain-string assignments (no command substitution, no use in those
  scripts) → zero behavioural effect. Asserted by the existing `ci-local.sh` smoke
  path staying green; the new vars are documentation-only.

- **Gate reading a constant that drifts from reality.** The horizon constant
  (whether in `ci-freeze.env` or the test) is itself a thing that can go stale. This
  is inherent to *any* "validated version" pin (same as
  `nos_macos_validated_version`). Mitigated by gate #7 cross-checking `.env` ↔
  `ci.yml`, and by the bump being a documented 3-file ritual (ci.yml + ci-freeze.env
  + default.config.yml) in the doc breadcrumb. The gate makes a *half*-applied bump
  fail loudly, which is the achievable guarantee.

- **No Linux regression.** The gate's `test_ubuntu_matrix_untouched` + the fact the
  change touches only Darwin matrix legs means the standing `integration-linux`
  wet-test is byte-unaffected. This is the single largest risk for a cross-platform
  repo and it is structurally avoided (no Linux line edited).

## Verification recipe

```bash
# 0. On the right branch
git switch feat/v0.7-overnight

# 1. The new gate (offline, fast — pure YAML parse of ci.yml)
python3 -m pytest tests/anatomy/test_ci_macos_matrix_explicit.py -q

# 2. The sibling CI gates still pass (no cross-regression on the workflow)
python3 -m pytest tests/anatomy/test_ci_integration_timeout.py \
                  tests/anatomy/test_ci_pipeline.py \
                  tests/anatomy/test_pages_workflow_action_versions.py -q

# 3. Full anatomy suite stays green
python3 -m pytest tests/anatomy/ -q

# 4. Playbook syntax-check unaffected (no playbook YAML touched)
ansible-playbook main.yml --syntax-check

# 5. Prove macos-latest appears nowhere + every macOS leg is numeric
grep -n 'macos-latest' .github/workflows/ci.yml && echo "FAIL: floating alias present" \
  || echo "OK: no macos-latest"
grep -nE 'macos-[a-z]' .github/workflows/ci.yml && echo "FAIL: non-numeric macOS alias" \
  || echo "OK: all macOS legs numeric"

# 6. Confirm the forward-horizon leg is present in the integration matrix
python3 - <<'PY'
import yaml, pathlib
jobs = yaml.safe_load(pathlib.Path(".github/workflows/ci.yml").read_text())["jobs"]
legs = [o for o in jobs["integration"]["strategy"]["matrix"]["os"] if str(o).startswith("macos-")]
majors = sorted(int(o.split("-")[1]) for o in legs)
print("macOS integration legs:", legs, "→ majors:", majors)
assert len(majors) >= 2 and max(majors) >= 26, "no forward-horizon (>= macOS 26) leg"
print("OK: forward-horizon leg present")
PY

# 7. (If §2 adopted) ci-freeze.env still sources cleanly + vars match ci.yml
sh -c '. tools/ci-freeze.env; echo "anchor=$NOS_MACOS_ANCHOR horizon=$NOS_MACOS_HORIZON"'

# 8. Frozen 1:1 pre-release probe (optional, before any eventual release push)
tools/ci-local.sh
```

Acceptance: gate #1 green, sibling CI gates #2 green, full suite green, syntax-check
clean, step-5 prints both "OK" lines (no `macos-latest`, all macOS legs numeric),
step-6 prints "OK: forward-horizon leg present". **Note:** the *actual* `macos-26`
runner only proves nOS on the new major when the `integration` job runs in GitHub
Actions (push/PR/cron) — the offline gates pin the *matrix shape*; the wet-test
result lands on the next CI trigger and is non-blocking (`continue-on-error`).

## Follow-ups (NOT this plan)

- **Self-hosted macOS runner** (deferred CLAUDE.md item) — the only way to *freeze*
  the macOS environment (not just the matrix label). Once it exists, pin its exact
  `sw_vers` and feed it into the same horizon SoT, closing the "hosted runner is not
  the operator's Mac" gap noted in CLAUDE.md.
- **Auto-bump PR on new GitHub macOS image** — a scheduled job that diffs
  `actions/runner-images` for a new `macos-N` label and opens a PR bumping the
  horizon leg + `NOS_MACOS_HORIZON` + `nos_macos_validated_version`, turning the
  manual 3-file ritual into a reviewed automated nudge.
- **Unify the validation triple** — `nos_macos_validated_version`
  (`default.config.yml`, from `v07-darwin27-version-gate-coverage.md`),
  `NOS_MACOS_HORIZON` (`ci-freeze.env`, this plan), and the `ci.yml` matrix should
  share **one** number. A meta-gate asserting all three agree would make "the OS we
  test = the OS we validate = the OS the playbook trusts" a single enforced fact.
  Deferred so each Darwin-27 plan lands reviewable on its own first.
