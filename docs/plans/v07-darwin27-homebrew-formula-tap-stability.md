# v0.7 — Darwin 27 Homebrew formula / tap stability

Status: PLAN (not implemented). Target branch: `feat/v0.7-overnight`.
Owner: overnight agent batch. Scope: repo edits only, no live mutation.

## Problem / why

nOS's host layer leans on **third-party Homebrew taps and version-sensitive
formulae** for its most load-bearing host daemons — and that surface is the
quietest, most fragile thing in the whole provision. `default.config.yml:577`
configures four out-of-core taps:

```yaml
homebrew_taps:
  - dunglas/frankenphp        # Wing host runtime (FrankenPHP single binary)
  - shivammathur/php          # php-zts dependency of frankenphp (worker mode)
  - infisical/get-cli         # required by the `- infisical` formula
```

…plus an **operator-side local tap `pazny/local`** carrying a HEAD-patched
`ollama` formula (memory `ollama-brew-mlx-only-bottle`: core's `ollama` bottle
ships *no* `llama-server`, so every GGUF text generate dies HTTP 500 until a
`brew reinstall --build-from-source pazny/local/ollama` with `-DGGML_CCACHE=OFF`).

Three structural gaps make this a Darwin-27 forcing-function item — distinct from
the two sibling Darwin plans (`…-version-gate-coverage.md` guards the OS *floor*
+ arch; `…-softwareupdate-script.md` manages OS *patches*; this one guards the
*Homebrew package supply chain* that rides on top of whatever macOS is present):

1. **The bottle cliff at every macOS major.** Homebrew ships pre-built bottles
   keyed to the OS codename — today `arm64_sequoia` (default.config.yml:570
   names it explicitly for the frankenphp pin). When the host jumps to the next
   macOS (macOS 27 / 28, Darwin 26 / 27), **third-party taps lag homebrew-core
   by days-to-weeks in publishing a bottle for the new codename**. Until they do,
   `brew install frankenphp` / `brew install php` **silently falls back to a
   source build** — minutes-to-tens-of-minutes of clang per formula on the
   converge critical path, and for `php-zts` a build that frequently fails
   outright on a brand-new SDK. The frankenphp version-pin gate
   (`test_wing_frankenphp_version_pin.py`) catches a *wrong-version* binary, but
   **nothing in the repo records which bottle/codename the taps were validated
   against, nor warns when the host codename is ahead of that** — the operator
   only discovers the source-build cliff when a blank run hangs for 25 min in
   "Perform brew installation."

2. **No tap-trust / supply-chain posture.** Homebrew's `HOMEBREW_NO_INSTALL_FROM_API`
   + `HOMEBREW_REQUIRE_TAP_TRUST` knobs are *unset*; the four taps are tapped via
   the `homebrew_tap` module with **no `clone_target`, no commit/sha pin, no
   trust assertion**. A compromised or force-pushed third-party tap rewrites the
   formula nOS executes as the user who owns `/opt/homebrew` — and the `brew
   upgrade` task (`homebrew_upgrade_all_packages: true`, default ON) re-pulls
   every tap HEAD on **every run**, unattended, overnight. The brace-comment at
   `roles/pazny.mac.homebrew/tasks/main.yml:456` already shows the symptom
   surfacing (`HOMEBREW_REQUIRE_TAP_TRUST` named as a cause of upgrade aborts)
   but the repo neither sets the trust knob deliberately nor records *which* tap
   commit it trusts.

3. **The `pazny/local` ollama tap is an undocumented out-of-band hack.** It lives
   **only on the operator's machine** — there is no role, no `homebrew_taps`
   entry, no formula file, and no gate in the repo. A blank run on a fresh host
   re-installs the **broken core bottle** (HTTP 500 on every text generate);
   the fix exists solely in the operator's head + a memory note. This violates
   the machinery doctrine (`machinery-purpose-and-no-hacks`): the live fix must
   propagate via a committed mechanism, not survive only as tribal knowledge.
   Darwin 27 makes it worse — a new macOS will re-bottle core ollama, and whether
   that bottle finally carries `llama-server` is unknown until tested, so the
   repo needs a **declared, gated detection + remediation seam**, not a silent
   re-break.

This is a **supply-chain / posture** item: it makes the Homebrew tap+bottle
contract *executable and self-documenting* (which taps, validated against which
macOS codename, with what trust posture, and what to do when a core bottle is
defective) instead of living in prose + memory + one operator's shell history.

### Explicitly out of scope (so this doesn't over-reach)

- **Re-pinning `frankenphp_version` / the frankenphp `--version` preflight.**
  That is already owned by `test_wing_frankenphp_version_pin.py` +
  `pazny.wing/tasks/main.yml`. This plan adds the **bottle-codename + tap-trust**
  layer *underneath* it, and must not duplicate or weaken the existing pin.
- **The OS floor / Apple-Silicon arch gate** — owned by
  `…-version-gate-coverage.md` (`tasks/preflight-platform.yml`). This plan
  *consumes* the host codename but does not assert an OS floor.
- **Managing macOS security updates** — owned by `…-softwareupdate-script.md`.
- **Auto-bumping any pin.** Bottle-codename + trusted-commit values are bumped by
  a human after a wet-test; the gate enforces *coherence*, never auto-advances.
- **Linux.** Every new task is `when: nos_pkg_manager == 'homebrew'` /
  `ansible_os_family == 'Darwin'`. The Ubuntu wet-test must be byte-inert (it
  installs frankenphp as a GitHub static binary and ollama via its own path,
  never through brew taps) — mirrors the existing `_platform.yml` gating.
- **Vendoring the actual ollama HEAD formula into the repo.** Carrying a full
  Ruby formula is brittle (it tracks upstream HEAD). The plan ships a **detection
  probe + a documented, operator-gated remediation path + the `pazny/local` tap
  *declared* as a conditional `homebrew_taps` entry**, not a copy of upstream's
  formula. (Vendoring is a Follow-up if the core bottle stays broken long-term.)

## Approach

Three cooperating pieces, all mirroring proven nOS patterns (the
`tasks/preflight-*.yml` read-only probe, the `homebrew_taps` list, and the
`frankenphp --version` post-install assertion), pinned by one offline gate.

### 1. Record the validated bottle codename + warn on a newer host

Add a small **central var** + a **read-only Darwin preflight** that records the
host's Homebrew bottle codename and warns (never fails) when it is *newer* than
the codename the taps were validated against — the exact "untested-newer = warn"
shape the version-gate plan uses for macOS majors, applied to the **bottle**
layer.

- **`default.config.yml`** — new block beside the `homebrew_taps`/`frankenphp`
  cluster (so the three host-supply vars live together):
  ```yaml
  # ── Homebrew bottle / tap stability (v0.7 Darwin 27 supply-chain) ───────────
  # The macOS codename Homebrew keys its arm64 bottles to. Third-party taps
  # (frankenphp, php-zts) publish a new-codename bottle days-to-weeks AFTER a
  # macOS major; until then `brew install` source-builds (slow / can fail).
  # Bump after wet-testing the taps on the new macOS. macOS N == Darwin (N-1).
  homebrew_bottle_codename: "sequoia"          # arm64_<codename> bottle target
  homebrew_validated_macos_major: "26"         # last macOS validated for these taps
  # Supply-chain: require explicit trust before brew executes a tap's formula.
  homebrew_require_tap_trust: false            # opt-in; gov profile flips true
  ```
  All four are **quoted-string / bare-bool scalars, no filters, defined in
  `default.config.yml`** (loads before core-up) → both variants of
  `test_config_stock_jinja_only.py` satisfied.

- **`tasks/preflight-homebrew.yml`** (new, modeled on `preflight-at-rest.yml` —
  Darwin-gated, **read-only**, `failed_when: false`), imported from `main.yml`
  `pre_tasks` after `tasks/_platform.yml`. It:
  1. reads the host bottle codename — `brew --prefix` is constant, so resolve
     the codename from `ansible_facts.distribution_version` major via a small
     **committed mapping** (`homebrew_codename_by_macos_major` in
     `default.config.yml`: `{"14":"sonoma","15":"sequoia","26":"sequoia",...}`)
     OR, more robustly, shell `brew config 2>/dev/null | awk -F': ' '/^macOS/...'`
     **with `failed_when: false`** and fall back to the mapping. (The mapping is
     the source of truth; the `brew config` read is a cross-check only.)
  2. **warn (debug, never fail)** when the host major is newer than
     `homebrew_validated_macos_major`: "running on macOS {{ host }}, Homebrew
     taps last validated on macOS {{ validated }} — the frankenphp/php-zts taps
     may source-build until a `arm64_<new-codename>` bottle is published; this is
     slow but non-fatal." This is the **bottle-cliff breadcrumb** gap (1) closes.
  3. emit the resolved codename + validated-major into the run recap (and, when
     Bone is up, an A9 `on_info` notification — reuse the existing notification
     vein, no new infra).

  Every task gated `ansible_os_family == 'Darwin'` → Linux byte-inert.

### 2. Tap-trust posture (opt-in, gov-default-on)

- In `roles/pazny.mac.homebrew/tasks/main.yml`, inside the existing
  `Perform brew installation` block (which already sets a per-task
  `environment:`), thread `HOMEBREW_REQUIRE_TAP_TRUST` /
  `HOMEBREW_NO_INSTALL_FROM_API` from the new var onto the **tap + upgrade**
  tasks' `environment:` (where it is load-bearing), default OFF so current
  behaviour is byte-identical:
  ```yaml
  environment:
    HOMEBREW_NO_AUTO_UPDATE: "1"
    HOMEBREW_NO_INSTALL_CLEANUP: "1"
    HOMEBREW_REQUIRE_TAP_TRUST: "{{ '1' if homebrew_require_tap_trust | bool else '' }}"
  ```
  When a gov tenant flips `homebrew_require_tap_trust: true`
  (`profiles/gov-local.yml`), brew refuses to run an untrusted tap's formula
  until the operator runs `brew tap --force-auto-update` / trusts the commit —
  closing the gap (2) "unattended `brew upgrade` re-pulls untrusted tap HEAD."
  This is the **opt-in, default-OFF** shape the at-rest gate already established,
  so a normal converge is unaffected.

- The existing **non-fatal `brew upgrade`** task (`main.yml:445`, already
  `failed_when: false` with a WARN report) is left as-is — it is the right
  posture; the plan only adds the trust env, it does not change the upgrade's
  best-effort semantics.

### 3. Make the `pazny/local` ollama remediation a committed, gated seam

The structural payoff for the machinery doctrine. Two parts:

- **Declare the tap conditionally.** Add a gated `homebrew_taps` entry +
  `homebrew_installed_packages` override that, **when `ollama_use_local_tap:
  true`** (new var, **default `false`** so a fresh host is unchanged), taps
  `pazny/local` and installs `pazny/local/ollama --build-from-source` with
  `GGML_CCACHE: "OFF"` in `environment:`. Default OFF keeps the current
  fresh-host behaviour byte-identical; the operator flips it on (or
  `profiles/all-on.yml` may set it, TBD in review) to get the working
  `llama-server` build on a host where core is still defective.

- **Detect-and-surface in the openclaw role.** Add a **read-only post-install
  probe** in `roles/pazny.openclaw/tasks/main.yml` (after the `state: latest`
  install, gated `nos_pkg_manager == 'homebrew'`): shell
  `test -x "$(brew --prefix)/bin/llama-server" || ls "$(brew --prefix)"/Cellar/ollama/*/libexec/.../llama-server`
  (`failed_when: false`, `changed_when: false`) and, if `llama-server` is
  **absent**, emit a loud `debug` WARN: *"core ollama bottle ships no
  llama-server — every GGUF text generate will HTTP 500. Remediate with
  `ollama_use_local_tap: true` (build-from-source) or wait for a fixed core
  bottle; revert check: `formulae.brew.sh/api/formula/ollama.json` contains
  'llama-server'."* This converts the memory note into an **in-run, repo-owned
  diagnostic** that fires on exactly the broken-bottle condition.

  This is the doctrine fix for gap (3): the live remediation now propagates via
  a committed var + a committed probe, instead of surviving only in the
  operator's shell history.

## Files to touch

New:

- `tasks/preflight-homebrew.yml` — read-only Darwin bottle-codename probe +
  newer-than-validated warn (A). Modeled on `tasks/preflight-at-rest.yml`.
- `tests/anatomy/test_homebrew_tap_stability.py` — **the gate** (below).

Edited:

- `default.config.yml` — `homebrew_bottle_codename`,
  `homebrew_validated_macos_major`, `homebrew_require_tap_trust`,
  `homebrew_codename_by_macos_major` (mapping), `ollama_use_local_tap` — **all
  stock-Jinja scalars/dict, real defaults, defined before core-up** (satisfies
  `test_config_stock_jinja_only.py` both variants). The mapping is a plain dict
  of string→string (no filters).
- `main.yml` — one `import_tasks: tasks/preflight-homebrew.yml` in `pre_tasks`
  after `_platform.yml`, with `tags: ['always', 'preflight']`.
- `roles/pazny.mac.homebrew/tasks/main.yml` — add `HOMEBREW_REQUIRE_TAP_TRUST`
  to the tap/upgrade `environment:` (default `''` = OFF); add the conditional
  `pazny/local/ollama --build-from-source` install path gated
  `ollama_use_local_tap` (with `GGML_CCACHE: "OFF"`). **No behaviour change on
  the default (all-flags-false) path.**
- `roles/pazny.openclaw/tasks/main.yml` — read-only `llama-server` presence
  probe + WARN debug (after the existing `state: latest` install).
- `profiles/gov-local.yml` — flip `homebrew_require_tap_trust: true` (supply-chain
  posture for gov tenants) — opt-in, mirrors the at-rest gate's gov flip.
- `docs/security-baseline.md` — a paragraph: third-party tap inventory, the
  bottle-codename validation record, the opt-in `HOMEBREW_REQUIRE_TAP_TRUST`
  posture, and the ollama-bottle remediation seam.
- `docs/active-work.md` — one-line pointer.

## Gates it needs

New `tests/anatomy/test_homebrew_tap_stability.py` — **offline, source-level**
(no playbook run, no `brew`, no Docker; pure YAML/text parse), mirroring
`test_wing_frankenphp_version_pin.py` and `test_config_stock_jinja_only.py`:

1. **`test_bottle_vars_declared_and_stock`** — `default.config.yml` declares
   `homebrew_bottle_codename`, `homebrew_validated_macos_major`,
   `homebrew_require_tap_trust`, `ollama_use_local_tap`; the first two parse as
   bare string literals (no `{{` / `|`), the bools as native YAML bools. Pins the
   stock-Jinja contract belt-and-suspenders.
2. **`test_codename_mapping_covers_validated_major`** — the
   `homebrew_codename_by_macos_major` dict contains a key equal to
   `homebrew_validated_macos_major`, and its value equals
   `homebrew_bottle_codename`. So a future bump that advances one and forgets the
   other (the exact half-applied-bump failure mode) fails the gate — the
   bottle-coherence pin, sibling to the macOS↔Darwin +1 invariant in the
   version-gate plan.
3. **`test_preflight_homebrew_is_darwin_scoped_and_nonmutating`** — every task in
   `tasks/preflight-homebrew.yml` carries `ansible_os_family == 'Darwin'` (or is
   a Darwin-conditional fact) in its `when:`, AND no task contains `brew install`
   / `brew upgrade` / `brew tap` (the preflight is read-only — `brew config`/
   `--prefix` only, `failed_when: false`). Pins "Linux byte-inert + probe never
   mutates."
4. **`test_preflight_warns_never_fails_on_newer_host`** — the newer-than-validated
   task in `preflight-homebrew.yml` uses `ansible.builtin.debug`, never
   `ansible.builtin.fail` (a bottle source-build is slow, not fatal — same
   "newer = warn" doctrine as the OS version gate).
5. **`test_tap_trust_env_threaded_and_default_off`** — parse
   `roles/pazny.mac.homebrew/tasks/main.yml`: `HOMEBREW_REQUIRE_TAP_TRUST` is
   present in an `environment:` block AND its value derives from
   `homebrew_require_tap_trust` (so flipping the var actually changes brew's
   behaviour), AND the config default is `false` (a normal run is unaffected).
6. **`test_ollama_local_tap_is_default_off`** — `default.config.yml` declares
   `ollama_use_local_tap: false`; the conditional `pazny/local` install path in
   the homebrew role is gated `when:` on `ollama_use_local_tap` (regex/parse), so
   a fresh host never tries to tap/build it unless explicitly opted in.
7. **`test_ollama_role_probes_for_llama_server`** —
   `roles/pazny.openclaw/tasks/main.yml` contains a `llama-server` presence
   check that is `changed_when: false` + `failed_when: false` (read-only) and a
   `debug` WARN referencing the remediation (`ollama_use_local_tap`). Converts
   the memory hack into a pinned, repo-owned diagnostic.
8. **`test_no_brace_hash_in_new_shell`** — any inline shell added to
   `preflight-homebrew.yml` / the role tasks contains no `${#` (the Jinja
   `{#`-comment-open trap, memory `jinja-rendered-shell-brace-hash-trap`); use
   `${arr[@]+...}`/`${!arr[@]}`.

The suite must stay green and `ansible-playbook main.yml --syntax-check` must
pass. The whole feature is default-OFF (`require_tap_trust: false`,
`ollama_use_local_tap: false`) + read-only-probe-only, so the **macOS
integration wet-test runs only the read-only `brew config` probe** (no
state change, `changed=0` on the idempotence re-run) and the **Linux wet-test
executes zero new lines** (Darwin / homebrew gate).

## Risks

- **`brew config` output format drift across macOS majors.** Parsing it for the
  codename is fragile — *which is exactly the gap being closed*, but the probe
  must degrade gracefully: the **committed `homebrew_codename_by_macos_major`
  mapping is the source of truth**, the `brew config` read is a `failed_when:
  false` cross-check only. Unknown format → fall back to the mapping → warn,
  never crash the converge. Gate #3 pins the read-only / non-fatal shape.
- **Mapping staleness.** The codename mapping needs a new entry each macOS major.
  Mitigated: a host major *missing* from the mapping triggers the newer-than-
  validated **warn** path (not a fail), and the recap names the missing key —
  self-documenting. Gate #2 keeps the validated entry coherent so the *known*
  rows can't silently desync.
- **`HOMEBREW_REQUIRE_TAP_TRUST` over-blocking.** Defaulting it ON would break a
  normal converge the first time a tap force-pushes. So it is **default OFF**,
  gov-opt-in only — same risk profile as the at-rest gate operators already
  accept. Gate #5 asserts the default is `false`.
- **The `pazny/local` build-from-source path is slow + needs `GGML_CCACHE=OFF`.**
  Mitigated by keeping it **default OFF** (gate #6) — a fresh host installs the
  core bottle and the probe (3) merely *warns* if `llama-server` is missing; the
  operator opts into the source build deliberately. The `GGML_CCACHE: "OFF"`
  env is the documented fix for Homebrew superenv stripping ccache
  (`ollama-brew-mlx-only-bottle`). No auto-build on the unattended path.
- **Not actually fixing a broken core bottle on a fresh host.** True — and
  deliberate. Auto-tapping a personal tap + source-building on every fresh blank
  is its own supply-chain + time risk. The honest shape is **detect + surface +
  documented opt-in remediation**; vendoring the formula is a Follow-up the
  operator chooses if core stays broken long-term. The plan converts a silent
  HTTP-500 into a loud, actionable in-run WARN, which is the real defect today.
- **Linux regression.** The largest cross-platform risk. Fully mitigated by gate
  #3 (every preflight task Darwin-scoped) + every role edit gated
  `nos_pkg_manager == 'homebrew'`; the Ubuntu CI wet-test (installs frankenphp /
  ollama off-brew) is the backstop.
- **Interaction with the frankenphp pin.** This plan adds the bottle-codename
  *underneath* the existing `frankenphp_version` `--version` preflight; it must
  not touch that var or task. The frankenphp gate
  (`test_wing_frankenphp_version_pin.py`) staying green is part of acceptance.

## Verification recipe

```bash
# 0. On the right branch
git switch feat/v0.7-overnight

# 1. The new gate + the stock-Jinja gate + the existing frankenphp pin
#    (offline, fast — no brew run)
python3 -m pytest tests/anatomy/test_homebrew_tap_stability.py \
                  tests/anatomy/test_config_stock_jinja_only.py \
                  tests/anatomy/test_wing_frankenphp_version_pin.py -q

# 2. Full anatomy suite stays green
python3 -m pytest tests/anatomy/ -q

# 3. Syntax-check clean (new preflight import + role env edits parse)
ansible-playbook main.yml --syntax-check

# 4. Prove the new feature is byte-inert on the default (all-flags-false) path:
#    no HOMEBREW_REQUIRE_TAP_TRUST="1" and no pazny/local tap unless opted in.
grep -nE 'homebrew_require_tap_trust|ollama_use_local_tap' default.config.yml
#    → both must read `false`

# 5. Prove the preflight is read-only (should print nothing — no install/tap/upgrade)
grep -nE 'brew (install|upgrade|tap)' tasks/preflight-homebrew.yml \
  && echo "FAIL: preflight mutates" || echo "OK: preflight is read-only"

# 6. Confirm no Jinja brace-hash trap in any new shell
grep -rn '\${#' tasks/preflight-homebrew.yml roles/pazny.mac.homebrew/tasks/main.yml \
  roles/pazny.openclaw/tasks/main.yml \
  && echo "FAIL: \${#...} = Jinja {# comment-open" || echo "OK: no brace-hash"

# 7. READ-ONLY live spot-check (no playbook mutation): run the preflight tag
#    against the live Mac — it only runs `brew config`/`--prefix`, no install:
ansible-playbook main.yml --tags preflight --skip-tags stacks --check 2>&1 | \
  grep -iE "bottle|codename|validated|llama-server" || \
  echo "OK: probe ran clean on the validated host (macOS 26 / sequoia bottle)"

# 8. Frozen 1:1 pre-release probe (optional, before any eventual release push)
tools/ci-local.sh
```

Acceptance: gates #1–#2 green (incl. the frankenphp pin unbroken), full suite
green, syntax-check clean; step-4 shows both flags `false` (byte-inert default);
step-5 + #6 print "OK"; step-7 runs the probe with no fail/spurious warn on the
validated host; the macOS idempotence re-run stays `changed=0`.

## Follow-ups (NOT this plan)

- **Vendor the ollama HEAD formula** into `files/anatomy/homebrew/` + a committed
  `pazny/local`-style tap-in-repo, if core's bottle stays `llama-server`-less
  past the next macOS major — turns the opt-in remediation into a self-contained,
  fresh-host-clean install. Separate plan (carries a real upstream-tracking
  maintenance cost).
- **Pin trusted tap commits.** Extend `homebrew_taps` entries to carry a
  `revision:`/`clone_target:` so brew checks out a *known* tap commit, not HEAD —
  full supply-chain pinning, paired with a refresh tool (sibling to
  `tools/ci-local.sh --refresh-lock`). Deferred: needs a per-tap commit-pin
  workflow + a way to re-validate on bump.
- **Export the bottle-codename + tap inventory** into `tasks/export-state.yml` /
  `~/.nos/state.yml` so Wing's /timeline shows "host: sequoia bottle, taps
  validated: yes" — sibling to the version-gate plan's same follow-up.
- **A self-hosted macOS runner** (already a deferred CLAUDE.md item) would let CI
  *prove* the taps bottle-build on a new macOS major before the operator bumps
  `homebrew_validated_macos_major` — closing the loop on the bottle cliff.
