# v0.7 — Darwin / macOS version-gate coverage

Status: PLAN (not implemented). Target branch: `feat/v0.7-overnight`.
Owner: overnight agent batch. Scope: repo edits only, no live mutation.

## Problem / why

The README pins the reference platform as **macOS on Apple Silicon (M1+), Intel
not supported** (`README.md:61`), and CLAUDE.md repeats **ARM64 only (M1+)**. But
the playbook has **no preflight gate that asserts the host actually meets a macOS
floor or that the kernel/OS version is one nOS has been validated against**.
There are preflight `fail:` gates for `tenant_domain`, `host_alias`, the
edge-proxy choice, the password prefix, and at-rest encryption (`main.yml`
L249–344) — the OS/arch floor is the conspicuous hole.

Today's reference host is **macOS 26.3.1 / Darwin 25.3.0** (verified:
`sw_vers` → ProductVersion `26.3.1`, `uname -r` → `25.3.0`). macOS and the Darwin
kernel version differ by a constant **+1** in the modern numbering era
(macOS 26 ↔ Darwin 25, macOS 27 ↔ Darwin 26, **macOS 28 ↔ Darwin 27**). nOS will
keep running across the next two annual macOS bumps; **"Darwin 27" is the
forward horizon** (macOS 28) this gate must keep the playbook *honest* about: it
should refuse to silently pretend a brand-new, untested macOS is "validated," and
it must refuse an actually-unsupported host (Intel `x86_64`, or a macOS older than
the floor) **fast and loud**, instead of grinding through ~15 min of a blank
before failing somewhere deep with a cryptic Homebrew/launchd error.

Three concrete gaps:

1. **No arch floor.** A run on an Intel Mac (`ansible_facts.machine == 'x86_64'`)
   does **not** fail at preflight. Worse, `roles/pazny.mac.homebrew/tasks/main.yml`
   still carries **dead Intel + macOS-<10.13 branches** (L16–35, L101) inherited
   from the geerlingguy fork. They can never fire on the M1+ reference platform,
   they imply Intel is supported (it isn't, per README), and they're a
   maintenance/readability tax. A run on Intel limps into Homebrew and dies
   later — exactly the "fail at minute 15, not minute 0" anti-pattern the other
   preflight gates exist to prevent.

2. **No macOS version floor.** There's no `ansible_facts.distribution_version is
   version('<floor>', '>=')` assertion. An operator on an ancient macOS (where
   the brew bottles, Docker Desktop, or launchd semantics diverge) gets no early
   signal.

3. **No "untested-newer" awareness.** When macOS 27 / 28 (Darwin 26 / 27) ships,
   nOS has no breadcrumb that this host is **ahead of the last validated
   version**. We don't want to *block* a newer macOS (that would brick the
   playbook every September), but a one-time **warning** ("running on macOS 28 /
   Darwin 27, last validated: macOS 26 — proceed, report issues") is the
   defensible shape: it documents the validation ceiling without becoming an
   annual hard-fail landmine.

This is a **portability/posture** item, sibling in spirit to the `_platform.yml`
cross-platform seam and the existing preflight `fail:` cluster — it makes the
"supported host" contract executable and self-documenting instead of prose-only.

### Explicitly out of scope (so the gate doesn't over-reach)

- **Linux hosts.** The whole gate is wrapped `when: ansible_os_family ==
  'Darwin'`. Ubuntu 24.04 is a first-class supported platform (its own CI
  wet-test) and must be **byte-unaffected** — no new task may evaluate a macOS
  version on Linux. This mirrors the existing macOS-gating doctrine
  (`tasks/_platform.yml`, `preflight-at-rest.yml`).
- **Hard-blocking a newer-than-validated macOS.** Newer macOS → **warn only**,
  never `fail:`. Blocking would make every annual macOS release brick nOS until a
  human bumps a constant. The hard-fail is reserved for the *floor* (too old) and
  *arch* (Intel) — both of which are genuinely unsupported.
- **The `_darwin.tar.gz` exporter download URLs** (`tasks/observability.yml`) —
  those `darwin` strings are release-asset platform tags, unrelated to the OS
  version. The gate must not touch or match them.
- **Removing the `arm64` *machine* gates** elsewhere (e.g. the legitimate
  `ansible_facts.machine == 'arm64'` Homebrew-ownership task at
  `roles/pazny.mac.homebrew/tasks/main.yml:14`, exporter URL arch-select in
  `tasks/observability.yml`) — those are correct and stay. Only the **dead Intel
  / macOS-<10.13 branches** are removed (§3).

## Approach

Three pieces, mirroring the proven preflight pattern (a `fail:`/`debug:` task in
`pre_tasks`, gated `when: ansible_os_family == 'Darwin'` + a stock-Jinja
`is version()` test) plus a dead-code prune, all pinned by one offline gate.

### 1. New preflight task file `tasks/preflight-platform.yml`

A dedicated, self-contained file (consistent with `tasks/preflight-at-rest.yml`),
imported from `main.yml` `pre_tasks` **immediately after** `tasks/_platform.yml`
(so `nos_platform` is set) and **before** any host role runs. Carries
`tags: ['always', 'preflight']`. Contents:

```yaml
---
# tasks/preflight-platform.yml
# Darwin / macOS host-floor + validation-ceiling gate (v0.7).
# Entirely gated on Darwin — Linux is byte-unaffected (Ubuntu is supported).
# macOS↔Darwin numbering: macOS N == Darwin (N-1). Last validated: macOS 26 /
# Darwin 25 (the v0.7 reference host). Forward horizon: Darwin 27 (macOS 28).

- name: "[Preflight platform] Apple Silicon required (Intel x86_64 unsupported)"
  ansible.builtin.fail:
    msg: |-
      nOS supports Apple Silicon (M1+) only. Detected CPU: {{ ansible_facts.machine }}.
      Intel Macs are not supported (README.md). To override at your own risk:
        -e nos_skip_platform_check=true
  when:
    - ansible_os_family == 'Darwin'
    - ansible_facts.machine != 'arm64'
    - not (nos_skip_platform_check | default(false) | bool)

- name: "[Preflight platform] macOS version floor"
  ansible.builtin.fail:
    msg: |-
      nOS requires macOS {{ nos_macos_min_version }} or newer.
      Detected macOS {{ ansible_facts.distribution_version | default('unknown') }}.
      Override at your own risk:  -e nos_skip_platform_check=true
  when:
    - ansible_os_family == 'Darwin'
    - ansible_facts.distribution_version is defined
    - ansible_facts.distribution_version is version(nos_macos_min_version, '<')
    - not (nos_skip_platform_check | default(false) | bool)

- name: "[Preflight platform] Warn when host is newer than last-validated macOS"
  ansible.builtin.debug:
    msg: |-
      NOTE — running on macOS {{ ansible_facts.distribution_version }}
      (Darwin {{ ansible_facts.kernel | default('?') }}), which is NEWER than the
      last version nOS was validated against (macOS {{ nos_macos_validated_version }}
      / Darwin {{ nos_darwin_validated_version }}). The playbook will proceed.
      Please report any macOS-{{ ansible_facts.distribution_version }}-specific
      issues. Forward horizon tracked in this gate: Darwin 27 (macOS 28).
  when:
    - ansible_os_family == 'Darwin'
    - ansible_facts.distribution_version is defined
    - ansible_facts.distribution_version is version(nos_macos_validated_version, '>')
```

**Stock-Jinja trap compliance (NON-NEGOTIABLE):** `is version(...)`,
`default()`, `| bool`, `is defined` are all stock Ansible/Jinja tests that
resolve in the play context (this is a `pre_tasks` host task, **not** a var that
lands in the `{{ vars }}` core-up eager-resolve namespace — the trap applies to
`default.config.yml`/`default.credentials.yml` values, which these are not). The
three new *vars* (below) DO go in `default.config.yml`, so they must be plain
string literals with no filters — see §2.

### 2. Central vars (`default.config.yml`)

Add a small `Platform floor / validation` block (e.g. near the top, beside
`tenant_domain` and the other host-shape vars):

```yaml
# ── Platform floor / validation (v0.7 Darwin version gate) ────────────────────
# macOS N == Darwin (N-1). Bump these three together when a new macOS is
# wet-tested. nos_skip_platform_check=true bypasses the floor + arch hard-fail.
nos_macos_min_version: "14.0"        # floor: Sonoma. Older = hard fail.
nos_macos_validated_version: "26"    # last macOS validated (v0.7 reference host)
nos_darwin_validated_version: "25"   # matching Darwin kernel major
```

All three are quoted-string scalars, no filters, defined in `default.config.yml`
(loads before core-up) → both variants of `test_config_stock_jinja_only.py` are
satisfied. `nos_skip_platform_check` needs no default in config — it's referenced
only via `| default(false)` in a play task (override-only extra-var), same shape
as `nos_skip_edge_check` (`main.yml:319`) which also has no config default.
**Floor choice = macOS 14 (Sonoma)**: the oldest macOS still receiving Apple
security updates and still carrying current Homebrew bottles + a supported Docker
Desktop — a conservative, defensible floor that won't reject any realistic
operator host.

### 3. Wire it into `main.yml` + prune the dead Homebrew branches

- **`main.yml`** — add one `import_tasks` line in `pre_tasks`, right after the
  `_platform.yml` import (L93–94):
  ```yaml
  - import_tasks: tasks/preflight-platform.yml
    tags: ['always', 'preflight']
  ```
  Placed **before** the Python-deps preflight so an unsupported host fails before
  any pip/brew work.

- **`roles/pazny.mac.homebrew/tasks/main.yml`** — remove the now-dead, never-fired
  Intel + macOS-<10.13 branches:
  - Delete the `Ensure Homebrew parent directory has correct permissions (Intel).`
    block (L16–35) — its `when: ansible_facts.machine == 'x86_64'` can never be
    true on the gated platform.
  - Delete / simplify the `when: ansible_facts.machine != 'arm64'` task at L101
    (the Intel fallback). Keep the **arm64** ownership task (L8–14) verbatim.

  This is the structural payoff: the preflight gate now *guarantees* `arm64`, so
  the role no longer needs (and shouldn't pretend to support) Intel branches. The
  prune is behaviour-preserving on every real M1+ host (those branches were
  already skipped) and removes the "Intel looks supported" contradiction.

## Files to touch

- `tasks/preflight-platform.yml` — **new file** (the gate tasks above).
- `main.yml` — **1 added** `import_tasks` line in `pre_tasks` (after
  `_platform.yml`).
- `default.config.yml` — **3 new** string vars (`nos_macos_min_version`,
  `nos_macos_validated_version`, `nos_darwin_validated_version`).
- `roles/pazny.mac.homebrew/tasks/main.yml` — **prune** the dead Intel /
  macOS-<10.13 branches (L16–35, L101); keep the arm64 ownership task.
- `tests/anatomy/test_platform_version_gate.py` — **new gate** (below).
- `docs/linux-port.md` *(or a one-liner in README near L61)* — one sentence:
  "The macOS floor + Apple-Silicon requirement are enforced at preflight by
  `tasks/preflight-platform.yml`; bump `nos_macos_validated_version` /
  `nos_darwin_validated_version` when a new macOS is wet-tested." (Optional but
  keeps the prose/contract in sync.)

## Gates it needs

New file `tests/anatomy/test_platform_version_gate.py`, an **offline,
source-level** gate (no playbook run, no Docker, no live host facts — pure
YAML/text parse), mirroring the existing config-parse gates:

1. **`test_preflight_platform_file_exists`** — `tasks/preflight-platform.yml`
   exists and is valid YAML (load it).
2. **`test_preflight_platform_imported_in_main`** — `main.yml` `pre_tasks`
   imports `tasks/preflight-platform.yml` with `tags` including `preflight`, and
   the import appears **after** `tasks/_platform.yml` (assert ordering by string
   index in the file). Pins the "platform vars resolved first" requirement.
3. **`test_platform_gate_is_darwin_scoped`** — every task in
   `preflight-platform.yml` carries `ansible_os_family == 'Darwin'` in its
   `when:` (regex/parse), so Linux is provably unaffected. This is the
   Ubuntu-safety pin.
4. **`test_arch_and_floor_are_hard_fail`** — the Intel + floor tasks use
   `ansible.builtin.fail`, both honor `nos_skip_platform_check`, and the
   newer-than-validated task uses `ansible.builtin.debug` (never `fail`). Pins
   the "newer = warn, older/Intel = fail" doctrine.
5. **`test_platform_vars_declared_and_stock`** — `default.config.yml` declares
   `nos_macos_min_version`, `nos_macos_validated_version`,
   `nos_darwin_validated_version` as **quoted-string** scalars (parse YAML, assert
   `isinstance(..., str)`). Belt-and-suspenders alongside
   `test_config_stock_jinja_only.py`.
6. **`test_validated_versions_consistent`** — assert
   `int(nos_macos_validated_version) == int(nos_darwin_validated_version) + 1`
   (the macOS↔Darwin +1 invariant), so a future bump that updates one and forgets
   the other fails the gate. This is the "Darwin 27 ↔ macOS 28" coherence pin.
7. **`test_no_dead_intel_branch_in_homebrew_role`** — assert
   `roles/pazny.mac.homebrew/tasks/main.yml` no longer contains
   `machine == 'x86_64'` / `distribution_version is version('10.13'`. Guards the
   §3 prune from silently reappearing on a future fork-merge.

The suite must stay green and `ansible-playbook main.yml --syntax-check` must
pass (the new `import_tasks` + `is version()` tasks are valid).

## Risks

- **`ansible_facts.distribution_version` shape on macOS.** It returns the
  ProductVersion string (`"26.3.1"` on the reference host). `is version('14.0',
  '<')` does a PEP 440-style compare — `"26.3.1"` vs `"14.0"` compares correctly
  (26 > 14). The `> nos_macos_validated_version` compare uses the bare major
  `"26"`; `"26.3.1" is version("26", ">")` is **True** (26.3.1 > 26), which would
  warn even on the validated host. **Mitigation:** compare on the **major only**
  — either set `nos_macos_validated_version` to the full reference string, OR
  (cleaner) derive the host major in the task via
  `ansible_facts.distribution_version.split('.')[0]` and compare integers. The
  plan's gate #6 + the warn-task wording assume **major-only** comparison; the
  implementation must extract the major (a `set_fact` of
  `_host_macos_major: "{{ ansible_facts.distribution_version.split('.')[0] }}"`
  immediately before the warn task) so the validated host does **not** spuriously
  warn. Add a gate assertion that the warn-task compares majors, not the full
  version. *(This is the one subtle correctness point — call it out in review.)*
- **`is version()` on an undefined fact.** Guarded by `... is defined` in every
  `when:` so a fact-gathering edge case (e.g. `gather_facts: false` partial run)
  skips cleanly rather than throwing.
- **Over-blocking a legit operator.** The floor is `14.0` (Sonoma) — generous;
  any realistic M1+ host is ≥ that. The `nos_skip_platform_check=true` escape
  hatch exists for the genuinely-stuck operator (mirrors `nos_skip_edge_check`).
- **Linux regression.** The single largest risk for a cross-platform repo. Fully
  mitigated by gate #3 (every task Darwin-scoped) + the file being a no-op on
  Linux (all `when:` false). The Ubuntu CI wet-test is the backstop.
- **Dead-branch prune changing behaviour.** The removed Homebrew Intel branches
  have `when:` conditions that are **already false** on every M1+ host, so the
  rendered task list is byte-identical on the reference platform. Gate #7 + the
  `--syntax-check` + the standing macOS idempotence re-run (`changed=0`) confirm
  no churn.
- **Annual-bump ergonomics.** When macOS 27/28 ships and is wet-tested, the
  operator bumps three string literals in `default.config.yml` (and the warn
  disappears). Gate #6 enforces the +1 invariant so the bump can't be
  half-applied. Documented in the commit body + the optional doc line.

## Verification recipe

```bash
# 0. On the right branch
git switch feat/v0.7-overnight

# 1. The new gate + the stock-Jinja gate (offline, fast)
python3 -m pytest tests/anatomy/test_platform_version_gate.py \
                  tests/anatomy/test_config_stock_jinja_only.py -q

# 2. Full anatomy suite stays green
python3 -m pytest tests/anatomy/ -q

# 3. Syntax-check clean (new import + is-version tasks parse)
ansible-playbook main.yml --syntax-check

# 4. Prove the gate runs on THIS host without spurious warn/fail (READ-ONLY,
#    check-mode, preflight tag only — no bring-up, no host mutation):
ansible-playbook main.yml --tags preflight --check 2>&1 | \
  grep -iE "Preflight platform|Apple Silicon|version floor|newer than" || \
  echo "OK: no platform fail/warn on this validated host (macOS 26 / Darwin 25)"

# 5. Prove the dead Intel/10.13 branches are gone (should print nothing)
grep -nE "machine == 'x86_64'|version\('10.13'" \
  roles/pazny.mac.homebrew/tasks/main.yml || echo "OK: dead branches pruned"

# 6. Frozen 1:1 pre-release probe (optional, before any eventual release push)
tools/ci-local.sh
```

Acceptance: gates #1–#2 green, full suite green, syntax-check clean, step-4 prints
the "OK" line (this validated host neither warns nor fails — the major-only
comparison fix in Risks is what makes this true), step-5 confirms the prune.

## Follow-ups (NOT this plan)

- A parallel **Ubuntu floor gate** (`distribution_version is version('24.04',
  '>=')`) in the same file, Linux-scoped — symmetric posture for the supported
  Linux platform. Separate diff so the Darwin gate lands reviewable on its own.
- Surface the validated-version triple in `tasks/export-state.yml` /
  `~/.nos/state.yml` so Wing can display "host: macOS 26, validated: yes" in the
  /timeline or systems view.
- A standing self-hosted macOS runner (already a deferred CLAUDE.md item) would
  let CI *prove* a new macOS major before the operator bumps
  `nos_macos_validated_version`, closing the loop on the "validation ceiling."
