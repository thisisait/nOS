# Plan — Darwin 27 / Homebrew Python 3.14 controller-interpreter incompatibility

- **Item:** Darwin 27 + Homebrew `python@3.14` is now the host default; the
  playbook expects a pyenv-managed 3.13 and Ansible auto-discovery picks 3.14 for
  controller-side imports + custom modules. ~7 scattered per-role workarounds each
  re-fight the same battle with no single anchor.
- **Branch:** `feat/v0.7-overnight`
- **Type:** PLAN ONLY — no live mutation, no playbook run, no brew/pyenv change.
  Repo edits (consolidation + docs) + a pytest anatomy gate.

---

## 1. Problem / why

### The divergence

nOS pins its Python in three coupled places, all expecting **3.13**:

- `default.config.yml:804` — `python_version: "3.13"` (pyenv install target)
- `tasks/python.yml:34,46` — `pyenv install/global {{ python_version | default('3.13') }}`
- `tools/ci-freeze.env:16` — `NOS_PYTHON_VERSION="3.13.13"` and
  `.python-version` (operator pyenv shim) — the **frozen** wet-test interpreter.

On a current macOS (the operator's box now reports as **Darwin 27.x**, Homebrew
default), `brew install <anything-that-depends-on-python>` pulls **`python@3.14`**
as the keg-only default, and `/opt/homebrew/bin/python3` → 3.14. `ansible.cfg` sets
`interpreter_python = auto`, so Ansible's auto-discovery resolves the **controller +
target interpreter to Homebrew 3.14**, NOT the pyenv 3.13 the playbook intends. The
custom modules under `library = ./files/anatomy/library` (`nos_state`, `nos_migrate`,
`nos_authentik`, `nos_apps_render`) and every `ansible.builtin.pip` task inherit that
3.14 interpreter.

### The symptom surface (already in the tree as scattered scar tissue)

The 3.14 reality has *already* drawn blood — there are at least **seven** independent,
undated, copy-pasted workarounds, each solving a local instance of the same root cause
with no shared anchor:

| Site | Workaround | Root cause it's patching |
|------|-----------|--------------------------|
| `main.yml:96-194` (4 preflight tasks) | pip `--break-system-packages` jinja2/pyyaml onto BOTH Homebrew 3.14 AND Apple `/usr/bin/python3` (3.9); uninstall jsonschema/rpds-py tree; heal broken `brew link` | custom modules land on a 3.14/3.9 interpreter with empty site-packages; `rpds-py` C-ext collides with the `semgrep` brew formula at `/opt/homebrew/lib/python3.14/site-packages/rpds/` |
| `roles/pazny.mac.homebrew/tasks/main.yml:438-444` | shelled out of `community.general.homebrew` because `ansible-core 2.20.5 + Python 3.14 + community.general 12.6.0` trips `Unknown profile name 'module_legacy_m2c'` on deserialize | the brew module's result-profile is unknown to 2.20.x under 3.14 |
| `roles/pazny.bone/tasks/main.yml:88-94` | shell `venv/bin/pip` instead of `ansible.builtin.pip` — its `packaging` import fails controller-side on PEP-668 Homebrew 3.14 | controller `pip` module import fails on 3.14 |
| `roles/pazny.pulse/tasks/main.yml:39-44` | same `venv/bin/pip` shell-out, same reason | same |
| `roles/pazny.apps_runner/tasks/main.yml:70-79` | shell `python -m pip … --user --break-system-packages PyYAML` to feed `nos_apps_render`'s `import yaml` | custom-module interpreter (3.14) has no pyyaml |
| `roles/pazny.uptime_kuma/tasks/monitors.yml:17-27` | same `--user --break-system-packages` for `uptime-kuma-api`+PyYAML | same |
| `tools/ci-freeze.env:9-10` + `.github/workflows/ci.yml:46-55,84-89` | pin `python-version: '3.13'` everywhere; comment explicitly: *"Python 3.14 broke ansible-core filter-plugin imports"* (the `VaultDecryptionContext` skip → "No filter named") | 3.14 on the runner skips `ansible.builtin.core` filters under 2.20.x |

**The deeper structural problem:** there is **no single test or task that asserts the
controller interpreter the playbook actually runs on is the pinned 3.13**, nor any
documentation that ties these seven scars to one root cause. Each was added reactively;
a future contributor who hits an eighth instance has nothing to grep for, will re-invent
an eighth `--break-system-packages` patch, and the `python_version: "3.13"` pin will keep
silently disagreeing with the live 3.14 interpreter. On a fresh Darwin 27 blank the
playbook *mostly* works only because every load-bearing step was individually hardened —
that is fragile by construction.

### Why this is a v0.7 item and not "already fixed"

The scars prove the *acute* failures are patched. What is **unaddressed**:

1. **No anchor / no gate.** Nothing pins the relationship "playbook intends 3.13,
   Homebrew default is 3.14, here is the seam." A drift (e.g. someone bumps
   `python_version` to `"3.14"` to 'match the host', or CI's `'3.13'` floats) has no
   tripwire. The CI comment at `ci.yml:46-55` is load-bearing *prose* with no test
   behind it.
2. **Interpreter pin is documentation, not enforcement.** `ansible.cfg` says
   `interpreter_python = auto` — i.e. the playbook does NOT actually pin its
   controller/target interpreter to the pyenv 3.13; it *relies on auto-discovery* and
   then mops up the consequences in seven places. The doctrine memory
   [`feedback_ansible_python_interpreter`] already records that `auto` "caches the wrong
   Python and overrides inventory + play-vars pins for custom modules" — that is exactly
   this bug, unfixed at the source.
3. **`python_version` is stale relative to `NOS_PYTHON_VERSION`.** `default.config.yml`
   carries `"3.13"` (minor only); `ci-freeze.env` carries `"3.13.13"` (exact). They are
   two truths for one fact, with no sync gate — the same shadow-pin failure mode that
   `version-pins-default-config-shadow` warns about.

This plan delivers the **anchor + gate + interpreter-pin hardening + a single
documented seam**, WITHOUT changing any pinned version value and WITHOUT touching the
live host (no brew, no pyenv, no playbook run). It converts seven orphaned scars into
one referenced, gate-pinned, grep-able contract.

---

## 2. Exact files / roles to touch

| File | Change |
|------|--------|
| `docs/python-interpreter-doctrine.md` | **NEW.** The single seam doc: states the contract (playbook intends pyenv 3.13; Homebrew default on Darwin 27 is 3.14; custom modules + `ansible.builtin.pip` must not depend on Homebrew 3.14 site-packages), enumerates the seven scar sites with back-references, and gives the operator the "why `--break-system-packages` is everywhere" answer in one place. Authoritative target for every future contributor + every scar comment's `see:` pointer. |
| `default.config.yml` (~line 804) | **No value change.** Add a comment block above `python_version: "3.13"`: this is the pyenv *target*; `ansible.cfg interpreter_python` + the preflight tasks ensure custom modules don't bind to Homebrew's `python@3.14`; exact patch version lives in `tools/ci-freeze.env` (`NOS_PYTHON_VERSION`); the two MUST share the same `major.minor` (gated). Point at the new doctrine doc. |
| `tools/ci-freeze.env` (~line 9-16) | **No value change.** Tighten the existing comment to name **Darwin 27** explicitly and cross-link `default.config.yml python_version` + the doctrine doc, so the `3.13.13` ↔ `3.13` relationship is documented at both ends. |
| `ansible.cfg` (~`interpreter_python = auto`) | **Option A (preferred, see §3):** leave `auto` but add a load-bearing comment + a play-vars pin reference. **Do NOT** silently flip to a hard path in an unsupervised run — that is behaviour-changing on every host (Linux, CI macOS, operator). The pin decision is documented in the doctrine doc as a *supervised* follow-up; this task only gates the *current* `auto` contract + the scar inventory. |
| `roles/pazny.bone/tasks/main.yml` (~line 88) | Comment-only: replace the bare "Homebrew Python 3.14 here" with a `see: docs/python-interpreter-doctrine.md` back-reference. No task logic change. |
| `roles/pazny.pulse/tasks/main.yml` (~line 40) | Same comment back-reference. No logic change. |
| `roles/pazny.apps_runner/tasks/main.yml` (~line 70) | Same comment back-reference. No logic change. |
| `roles/pazny.uptime_kuma/tasks/monitors.yml` (~line 18) | Same comment back-reference. No logic change. |
| `roles/pazny.mac.homebrew/tasks/main.yml` (~line 438) | Same comment back-reference. No logic change. |
| `main.yml` (~line 96 preflight block) | Add ONE comment line at the top of the preflight Python block pointing at the doctrine doc as the canonical explanation. No task logic change. |
| `.github/workflows/ci.yml` (~line 46) | Comment-only: cross-link the doctrine doc so the load-bearing `'3.13'` pin prose has a home. No workflow logic change. |
| `tests/anatomy/test_python_interpreter_pin.py` | **NEW** gate (see §4). |

**Not touched (deliberately):** the *value* `3.13` / `3.13.13` anywhere (no bump — a
real 3.14 migration is a supervised Track, not an overnight edit); any task's actual
shell/pip logic (the workarounds are correct — they just get an anchor); the live host
(read-only); `ansible.cfg interpreter_python` value (flip is supervised, §3 / §5).

---

## 3. Approach

This is a **consolidation + gate + doctrine** change. It makes the existing (correct)
behaviour *legible and non-drifting*; it does NOT alter what the playbook does on any
host. The byte-for-byte runtime behaviour on a Darwin 27 box, a Linux box, and CI is
identical before and after — only comments, a new doc, and a new offline test change.

### Step 1 — Write the seam doc (`docs/python-interpreter-doctrine.md`)

One authoritative page answering: *"Why is `--break-system-packages` everywhere? Why
does the playbook pin 3.13 when my host runs 3.14? Which interpreter do custom modules
use?"* Contents:

- **The contract:** pyenv 3.13 is the *intended* runtime for nOS tooling; Homebrew on
  Darwin 27 makes `python3` → 3.14; Ansible `interpreter_python = auto` resolves to the
  Homebrew 3.14 for the controller + custom modules; therefore every controller-side
  `import` (custom modules, `ansible.builtin.pip`'s `packaging`) must either (a) ship its
  deps onto whatever interpreter auto-discovery lands on, or (b) shell out to an explicit
  venv/pip. The seven scars are the two strategies applied per site.
- **The scar inventory** (the §1 table, with file:line back-refs) — so a future
  contributor hitting an eighth instance finds the pattern in one grep.
- **The CI angle:** 3.14 + ansible-core 2.20.x skips `ansible.builtin.core` filters
  (`VaultDecryptionContext` import); CI pins `'3.13'`; the frozen wet-test venv pins
  `3.13.13` + `ansible-core==2.21.0`. Link `2026-06-08-ci-filter-saga.md`.
- **The deferred real fix** (supervised): either (i) pin `interpreter_python` to the
  pyenv 3.13 shim path so custom modules stop landing on 3.14 (removes the *need* for
  most scars), or (ii) bump the whole stack to 3.14 once ansible-core ≥2.21 is the
  operator baseline (the `VaultDecryptionContext` symbol exists there). Both are Tracks,
  explicitly OUT OF SCOPE for the overnight run. Record *why* each is supervised
  (interpreter flip changes behaviour on every host incl. Linux/CI; 3.14 bump needs the
  2.21 baseline jump that Known-Tech-Debt already tracks).

### Step 2 — Annotate the scars with a shared back-reference

Each of the ~7 sites gets ONE comment line: `# see: docs/python-interpreter-doctrine.md
(Homebrew python@3.14 on Darwin 27)`. This is the grep anchor. **Zero logic changes** —
the workarounds are correct and stay byte-identical.

### Step 3 — Sync-document the two version truths

`default.config.yml python_version: "3.13"` and `tools/ci-freeze.env
NOS_PYTHON_VERSION="3.13.13"` get reciprocal comments naming each other + the doctrine
doc, so the `major.minor` relationship is explicit at both ends (the gate enforces it).

### Step 4 — Gate it (§4)

The gate pins: (a) the two version truths share `major.minor`; (b) the doctrine doc
exists and lists every scar site; (c) the CI pin is `'3.13'` (not floated to `'3.x'`/
`'3.14'`); (d) `python_version` is NOT carelessly bumped to `3.14` without the supervised
Track (anti-drift). It is pure offline file reading — no Docker, no network, no host.

### Why NOT flip `interpreter_python` to a hard 3.13 path in this task

- It is **behaviour-changing on every host**: Linux (no Homebrew, no pyenv shim at that
  path), CI macOS (`setup-python` 3.13, different path), the operator's box. A wrong
  hard-coded path breaks the run for everyone; auto-discovery's whole point is per-host
  resolution. Per the overnight rule ("no live mutation that isn't trivially
  reversible" + "every code fix ships a gate AND keeps the playbook green"), a change
  that I cannot wet-test (no playbook run allowed) and that alters behaviour on three
  platforms is a **PLAN, not a fix**.
- The memory [`feedback_ansible_python_interpreter`] records that pinning
  `interpreter_python` is the *eventual* right move — but it also records the custom-
  module dispatch *ignoring* the cfg pin on the CI macOS runner. That unresolved
  fragility means the flip needs a supervised wet-test across all three platforms, which
  is exactly what an overnight run cannot provide. So: document the flip as the
  supervised follow-up, gate the *current* contract.

### Why NOT bump `python_version` to `3.14` now

- The CI comment + ci-freeze.env are explicit: 3.14 + the operator's baseline
  ansible-core 2.20.5 **skips `ansible.builtin.core` filters** (the
  `VaultDecryptionContext` import that only exists in 2.21). A 3.14 bump is gated behind
  the **ansible-core 2.24/2.21-baseline jump already in Known Tech Debt** — a separate
  Track with its own blank. Bumping the pin ahead of that re-opens the exact 21-cycle
  filter saga the team just closed.

---

## 4. Gate (pytest anatomy) — `tests/anatomy/test_python_interpreter_pin.py`

Offline, no network, no Docker, no host — pure file reads (same shape as
`test_config_stock_jinja_only.py` / the version-pin gates).

```
ROOT/default.config.yml                 -> python_version pin (minor)
ROOT/tools/ci-freeze.env                -> NOS_PYTHON_VERSION pin (exact)
ROOT/.github/workflows/ci.yml           -> setup-python python-version
ROOT/docs/python-interpreter-doctrine.md-> seam doc + scar inventory
ROOT/<the 7 scar files>                 -> back-reference present
```

Test functions:

1. `test_config_and_freeze_python_share_major_minor` — parse `python_version` from
   `default.config.yml` (e.g. `3.13`) and `NOS_PYTHON_VERSION` from `ci-freeze.env`
   (e.g. `3.13.13`); assert `freeze.startswith(config + ".")` (same `major.minor`).
   This is the core shadow-pin anti-drift: bumping one without the other fails.

2. `test_config_python_is_an_approved_value` — assert `python_version` is exactly
   `"3.13"` (the intended baseline) OR `>= 3.14` *only if* the doctrine doc records the
   supervised 2.21-baseline Track as done (a sentinel string the gate looks for). Any
   careless float to `"3.14"` ahead of the Track FAILS with a pointer to the doctrine
   doc + Known-Tech-Debt 2.24 jump. (Same teeth as the Kuma SSTI pin gate's allowlist.)

3. `test_ci_setup_python_is_pinned_not_floated` — grep `.github/workflows/ci.yml` for
   every `python-version:` under a `setup-python` step; assert each is the literal
   `'3.13'` — NOT `'3.x'` and NOT `'3.14'`. Pins the load-bearing CI prose (`ci.yml:46-55`)
   with a test, so the filter-saga regression can't sneak back via a floated matrix.
   (Scope: the nOS `ci.yml` + `pages.yml`; the vendored `roles/pazny.dotfiles/.github/**`
   uses `'3.x'` legitimately and is excluded by path.)

4. `test_interpreter_doctrine_doc_exists_and_lists_scars` — assert
   `docs/python-interpreter-doctrine.md` exists and mentions each scar file path
   (`pazny.bone`, `pazny.pulse`, `pazny.apps_runner`, `pazny.uptime_kuma`,
   `pazny.mac.homebrew`, `main.yml` preflight). If a scar doc-link is dropped, the doc
   stops being the single seam → fail.

5. `test_scar_sites_back_reference_the_doctrine` — for each of the ~7 workaround files,
   assert the file contains the string `python-interpreter-doctrine.md` (the shared
   grep anchor). Guarantees a future contributor who lands on any scar finds the seam.
   Also asserts the `python@3.14` / `Python 3.14` rationale string is present (so the
   *reason* isn't silently stripped).

6. `test_no_orphan_3_14_pin_in_pyenv_targets` — assert `tasks/python.yml` and
   `default.config.yml` do NOT install/pin pyenv `3.14` (anti-drift twin of #2 at the
   pyenv-target layer; the host *has* 3.14 via Homebrew, but nOS must not *pyenv-install*
   it as the global until the supervised Track).

If the operator later runs the supervised interpreter-pin flip or the 3.14 baseline
Track, tests 1/2/6 are written so the *post-Track* state (3.14 everywhere + doctrine
sentinel) is also expressible — the gate is updated in the same commit that lands the
Track, one allowlist edit.

### Suite must stay green

- Run the **full** `tests/anatomy/` suite — confirm the comment-only edits to the seven
  scar files and the two version-pin comments don't trip
  `test_config_stock_jinja_only.py` (no new Jinja in vars-files), `test_version_pin_no_shadow.py`,
  or any syntax gate.
- **New var? NO.** This plan adds NO new `default.config.yml` / `default.credentials.yml`
  variable — only comments + a doc + a test. So `test_config_stock_jinja_only.py` is
  unaffected (the stock-Jinja trap doesn't apply to comments/docs).

---

## 5. Risks

| Risk | Mitigation |
|------|-----------|
| Annotating scars accidentally changes task logic (e.g. breaks a `changed_when`) | Comment-only edits; every edit is a `# …` line inside an existing block. Verify with `git diff` shows only comment additions; `--syntax-check` stays clean. |
| Gate test 3 (CI pin) is brittle to YAML quoting (`'3.13'` vs `"3.13"` vs `3.13`) | Parse with a tolerant regex matching `python-version:\s*['"]?3\.13['"]?` anchored under a `setup-python` block; assert no sibling resolves to `3.x`/`3.14`. |
| Someone reads "3.13 pinned" as "host runs 3.13" | The doctrine doc states plainly: host (Darwin 27 Homebrew) runs 3.14; nOS *intends* pyenv 3.13; the seam is auto-discovery + the scars. The whole point of the doc is to kill that misreading. |
| Flipping `interpreter_python` later breaks Linux/CI | Out of scope here; the doc records it as a supervised, all-three-platform wet-tested Track. This task does not touch the cfg value. |
| `python_version` ↔ `NOS_PYTHON_VERSION` drift on a future minor bump | Test 1 fails the moment `major.minor` diverges — forces both to move together (the documented sync). |
| Gate over-fits the exact scar file list (a refactor removes one site → false fail) | Test 4/5 assert presence in the *current* set; if a scar is genuinely removed (root cause fixed), the same commit updates the gate's expected list — that's the intended coupling, not a flaw. |
| Doc drifts from the real scar inventory over time | Test 5 binds each listed scar to a live back-reference; a stale doc entry whose file no longer references back fails the gate. |

---

## 6. Verification recipe

All steps are repo-only / read-only. No playbook apply, no brew, no pyenv, no live
mutation.

```bash
cd /Users/pazny/projects/nOS

# 1. New gate passes
python3 -m pytest tests/anatomy/test_python_interpreter_pin.py -q

# 2. Full anatomy suite stays green (esp. stock-Jinja + version-pin gates)
python3 -m pytest tests/anatomy/ -q

# 3. Playbook still parses (comment-only edits must not break syntax)
ansible-playbook main.yml --syntax-check

# 4. Edits are comment-only — diff shows no task-logic change in the 7 scar files
git diff --stat
git diff roles/pazny.bone/tasks/main.yml roles/pazny.pulse/tasks/main.yml \
         roles/pazny.apps_runner/tasks/main.yml roles/pazny.uptime_kuma/tasks/monitors.yml \
         roles/pazny.mac.homebrew/tasks/main.yml main.yml   # expect only `# …` additions

# 5. The grep anchor exists everywhere it should
grep -RIl "python-interpreter-doctrine.md" \
     roles/pazny.bone roles/pazny.pulse roles/pazny.apps_runner \
     roles/pazny.uptime_kuma roles/pazny.mac.homebrew main.yml \
     default.config.yml tools/ci-freeze.env .github/workflows/ci.yml

# 6. The two version truths agree on major.minor (what the gate enforces)
grep -n 'python_version:' default.config.yml
grep -n 'NOS_PYTHON_VERSION' tools/ci-freeze.env

# 7. No pyenv 3.14 install/global crept in
grep -n '3\.14' tasks/python.yml default.config.yml || echo "clean: no 3.14 pyenv target"
```

### Live read-only spot-check (optional, informational only)

```bash
# Confirm the host reality the doctrine doc describes (Darwin 27 + Homebrew 3.14).
sw_vers -productVersion ; uname -r            # Darwin kernel 27.x
/opt/homebrew/bin/python3 --version 2>/dev/null || true   # expect Python 3.14.x
pyenv version 2>/dev/null || true             # expect the pinned 3.13.x global
```

### Operator-only supervised follow-up (NOT run by the agent)

The two real fixes the doctrine doc records — each needs a full blank + all-three-
platform wet-test, forbidden under the overnight rule:

```bash
# OPTION (i): pin the controller/custom-module interpreter to the pyenv 3.13 shim so
#   custom modules stop binding to Homebrew 3.14 (removes the NEED for most scars).
#   Requires a supervised blank on macOS + the Linux/CI integration jobs green first.
#   ansible.cfg: interpreter_python = ~/.pyenv/shims/python3   (path resolved per-host)

# OPTION (ii): bump the whole stack to 3.14, gated behind the ansible-core 2.21/2.24
#   baseline jump already in Known Tech Debt (the VaultDecryptionContext symbol exists
#   at >=2.21, so 3.14's filter-skip disappears). One blank, then bump python_version
#   + NOS_PYTHON_VERSION together and update gate tests 1/2/6 to the 3.14 allowlist.
```

---

## 7. Commit (this plan only)

```
docs(plan): Darwin 27 / Homebrew python@3.14 seam

- 7 scattered 3.14 workarounds, no anchor or gate
- plan = one doctrine doc + back-refs + version-sync gate
- interpreter_python flip + 3.14 bump = supervised Tracks, deferred
- gate pins config<->freeze major.minor + CI '3.13' + scar back-refs
```

Lands on `feat/v0.7-overnight` only. No push.
