# v0.7 — Ollama MLX backend pinned + llama-server preflight (Darwin 27)

Status: PLAN (do not implement from this doc without operator review)
Branch: `feat/v0.7-overnight`
Source item: v0.7 overnight review → Darwin 27 / Apple-Silicon runtime —
"Ollama install is `state: latest`, unpinned, and silently ships a llama-server-less
bottle that 500s every GGUF text generation."
Related: memory `ollama-brew-mlx-only-bottle`, memory `version-pins-default-config-shadow`,
memory `machinery-purpose-and-no-hacks`, `roles/pazny.openclaw/tasks/main.yml`,
`tests/anatomy/test_wing_frankenphp_version_pin.py` (the pin+preflight+gate template),
`docs/plans/v07-sso-doctrine-test-covers-modes-not-wiring.md` (sibling pin pattern).

> **Scope note.** This plan covers the **runtime-correctness** half of the Ollama
> story: the install must (a) be version-pinned (no silent `state: latest` drift)
> and (b) carry a post-install preflight that **fails loud** when the landed keg
> has no `llama-server` runner, so a blank run cannot leave hermes / Open WebUI /
> the AgentKit agents dead with an HTTP 500. It does NOT change the MLX env-var
> tuning (`OLLAMA_FLASH_ATTENTION`, KV-cache, context length) — those are correct
> and stay as-is. It does NOT pull a new model set or touch the launchd wrapper.

---

## 1. Problem / why

`roles/pazny.openclaw/tasks/main.yml` installs Ollama with:

```yaml
- name: "[Ollama] Install/upgrade Ollama via Homebrew (0.19+ = MLX backend ...)"
  community.general.homebrew:
    name: ollama
    state: latest
  when: nos_pkg_manager == 'homebrew'
```

Two structural defects, both proven live:

1. **Unpinned (`state: latest`).** Every run silently floats to whatever
   homebrew-core's `ollama` formula currently resolves to. There is **no
   `ollama_version` var anywhere** (`grep ollama_version` → empty) — so the
   version is undeclared, unauditable, and undefended against a regression in a
   point release. This is exactly the failure mode memory
   `version-pins-default-config-shadow` warns about, except worse: there is not
   even a dead pin to bump — there is no pin at all.

2. **No runner preflight → silent llama-server-less bottle (the 2026-06-11 outage).**
   Per memory `ollama-brew-mlx-only-bottle`: homebrew-core's `ollama 0.30.7`
   bottle built only the Go binary + the *imagegen* MLX wrapper
   (`mlx_metal_v3`); the llama.cpp `llama-server` cmake step was on the GitHub
   HEAD formula but the bottle API had not synced. Result: `/api/version`
   answers 200 (the daemon is healthy) but **every text `ollama generate` →
   HTTP 500 `llama-server binary not found`**. Hermes, Open WebUI, and every
   AgentKit agent went dead. The fix on the live box was a local tap
   `pazny/local` carrying the HEAD formula + `-DGGML_CCACHE=OFF` and a
   `brew reinstall --build-from-source`.

The live host was rescued by hand, but **the repo never learned the lesson** —
machinery doctrine (`machinery-purpose-and-no-hacks`) says the rescue must
propagate through the playbook, not stay a manual keg swap. As it stands:

- the playbook's `[Ollama] Wait for API to respond` checks **only** `/api/version`
  (200), which the broken bottle passes — so the playbook reports green while
  text inference is 100% dead;
- a future blank on a fresh Mac (or any box where `brew` re-resolves to a
  llama-server-less bottle) silently reproduces the outage with no signal;
- there is no committed record of *which* Ollama version / tap is known-good,
  and no way to flip back to core bottles once upstream re-syncs (the revert is
  a memory note, not a config var).

"Darwin 27" framing: the next macOS major (Darwin 27 / macOS 16) will land new
`arm64_*` bottle tags; a not-yet-built bottle on a brand-new OS is precisely the
class of partial/half-built keg this preflight is meant to catch — the same way
`test_wing_frankenphp_version_pin.py` already guards FrankenPHP against the
"no arm64_sequoia bottle on older macOS" half-build.

**Why this is the right item for v0.7:** the FrankenPHP pin+preflight+gate
(shipped earlier) is the proven template for exactly this shape of bug — a
single-binary host runtime whose Homebrew install can land in a broken/partial
state that only surfaces at runtime. Ollama is the one remaining host runtime
binary with no such guard.

---

## 2. Exact files / roles to touch

| File | Change |
|------|--------|
| `default.config.yml` | Add `ollama_version` (pinned literal, stock-Jinja safe) + `ollama_use_local_tap` (bool, default `false`) + a `homebrew_taps` note. Document both in a comment block next to the existing OpenClaw section (~line 876). |
| `roles/pazny.openclaw/defaults/main.yml` | Mirror-default `ollama_version` / `ollama_use_local_tap` so the role is self-contained when invoked standalone (role default does NOT win over `default.config.yml` — see §6 trap). |
| `roles/pazny.openclaw/tasks/main.yml` | (a) Replace the `state: latest` install with a **version-pinned** install that honors `ollama_use_local_tap`; (b) add a **post-install llama-server preflight** that `fail`s loud when the runner is absent. |
| `roles/pazny.openclaw/README.md` | Document the pin var, the preflight, and the operator revert path (core bottle ↔ `pazny/local` tap), mirroring `pazny.wing/README.md`. |
| `tests/anatomy/test_ollama_llama_server_pin.py` | **NEW** anatomy gate (the fix's gate). Models `test_wing_frankenphp_version_pin.py`. |
| `CLAUDE.md` | One-line pointer under "Recently shipped doctrine" once implemented (not in this plan; noted for the impl PR). |

No live-system writes. No new launchd surface. No model changes.

---

## 3. Approach

### 3.1 Pin the version (config)

Add to `default.config.yml`, next to the existing OpenClaw block (~line 876),
as a **bare MAJOR.MINOR.PATCH literal** (no `{{ }}`, no `|` filter — stock-Jinja
safe, so it cannot trip the `{{ vars }}` eager-resolve trap):

```yaml
# Ollama is pinned (not state:latest) so a regressed point release / a
# llama-server-less core bottle (see the 2026-06-11 outage) cannot float in
# silently. The post-install preflight in pazny.openclaw fails loud if the
# landed keg has no `llama-server` runner. Bump this only after verifying
# `ollama --version` + a real `ollama run <model> "hi"` on the host.
ollama_version: "0.30.7"

# When the core bottle is broken (no llama-server runner — see memory
# ollama-brew-mlx-only-bottle), set true to install from the operator's
# pazny/local tap (HEAD formula + -DGGML_CCACHE=OFF source build). Default
# false = track homebrew-core. Flip back to false once
# formulae.brew.sh/api/formula/ollama.json carries "llama-server".
ollama_use_local_tap: false
```

Mirror both in `roles/pazny.openclaw/defaults/main.yml` (self-containment;
`default.config.yml` still wins at play scope).

> **Decision point for operator review:** pin to `0.30.7` (the live keg) vs the
> latest core release that is known to ship `llama-server`. Recommendation: pin
> to whatever `ollama --version` reports on the live host **today** (read-only
> check — see verification recipe), so the committed pin == the proven-good
> binary. Do not guess a version.

### 3.2 Version-pinned install (task)

Replace the `state: latest` task. Homebrew's `community.general.homebrew` cannot
install an arbitrary historic version of a core formula, so the pin is enforced
**by the preflight**, not by an install-time `=version` (which brew-core does not
support cleanly). The install task changes to:

- when `ollama_use_local_tap` is `true`: ensure the `pazny/local` tap is present
  (add `pazny/local` to `homebrew_taps` is the operator's manual step on their
  box; the task should NOT auto-create a tap — that needs `brew tap-new` with a
  Formula dir, which is operator-territory, see §5), and
  `state: present` against `pazny/local/ollama`;
- when `false`: `state: present` (NOT `latest`) against `ollama`, so an existing
  good keg is left alone and only a missing one is installed; upgrades become an
  explicit operator `brew upgrade` decision, not a silent every-run float.

This keeps the install **idempotent** and **non-drifting**.

### 3.3 llama-server preflight (the load-bearing change)

Immediately **after** the `[Ollama] Wait for API to respond` task and **before**
the first `ollama pull`, add (mirrors `pazny.wing` lines 160-183):

```yaml
# Version preflight — the landed Ollama keg must (1) report ollama_version and
# (2) actually contain a `llama-server` runner. A core bottle that built only
# the Go binary + the imagegen MLX wrapper answers /api/version 200 but 500s
# EVERY text generation (the 2026-06-11 outage). /api/version alone is NOT
# proof the runtime works — this is.
- name: "[Ollama] Read ollama version"
  ansible.builtin.command: "ollama --version"
  register: _ollama_ver
  changed_when: false
  failed_when: false
  environment:
    PATH: "{{ homebrew_prefix }}/bin:{{ ansible_facts['env']['PATH'] | default('', true) }}"
  when: nos_pkg_manager == 'homebrew'

- name: "[Ollama] Locate llama-server runner in the keg"
  ansible.builtin.find:
    paths: "{{ homebrew_prefix }}/Cellar/ollama"
    patterns: "llama-server"
    recurse: true
    file_type: any
  register: _ollama_runner
  when: nos_pkg_manager == 'homebrew'

- name: "[Ollama] Refuse on missing llama-server runner / version mismatch"
  ansible.builtin.fail:
    msg: |
      Ollama keg is not runnable for text inference.
        version pinned : {{ ollama_version }}
        reported       : {{ _ollama_ver.stdout | default('(none)') | trim }}
        llama-server   : {{ (_ollama_runner.matched | default(0)) }} match(es)
      A core bottle WITHOUT llama-server answers /api/version 200 but 500s every
      generate (the 2026-06-11 outage). Fix on the host:
        - flip `ollama_use_local_tap: true` (installs the pazny/local HEAD
          formula + -DGGML_CCACHE=OFF source build), OR
        - once formulae.brew.sh/api/formula/ollama.json carries "llama-server",
          `brew upgrade ollama` and re-pin `ollama_version`.
      Then re-run --tags openclaw.
  when:
    - nos_pkg_manager == 'homebrew'
    - (_ollama_runner.matched | default(0)) == 0
      or ollama_version not in (_ollama_ver.stdout | default(''))
```

> **Soft-fail vs hard-fail decision (operator review):** the existing
> `[Ollama] Wait for API to respond` is deliberately `failed_when: false` so a
> down Ollama does not abort the Ollama-*independent* core platform (the comment
> at lines 109-117 is explicit). The preflight above is a **hard `fail`** — which
> contradicts that "Ollama must never abort the core platform" stance. **Resolve
> before impl:** gate the hard-fail behind `openclaw_require_runner | default(true)`
> so an operator who genuinely wants Ollama optional can downgrade it to a
> warning, while the default (true) makes a llama-server-less keg a loud
> provisioning failure on the box where Ollama IS expected to work. Default true
> matches `handler-restart-fails-loud` doctrine; the escape hatch matches the
> existing Ollama-optional stance. Document the chosen default in the gate.

The `find` over `Cellar/ollama` is read-only and works for both the core keg and
the `pazny/local` keg (same Cellar layout). It is the structural proof the
`/api/version` check cannot give.

### 3.4 The runner path detail (verify before impl)

The 2026-06-11 memory says the broken keg contained `libexec/lib/ollama/mlx_metal_v3`
**only**. The good keg's `llama-server` lives under
`{{ homebrew_prefix }}/Cellar/ollama/<ver>/libexec/...` (or
`.../lib/ollama/...`). **Verify the exact relative path on the live host**
(read-only `find`, see §7) before pinning the `find.paths` — if it is not under
`Cellar/ollama`, widen `paths` to `{{ homebrew_prefix }}/Cellar/ollama` +
`{{ homebrew_prefix }}/lib/ollama`. The gate (§4) asserts the task uses a
`find`/`stat` for `llama-server`, not the literal path, so a path correction
does not churn the gate.

---

## 4. The gate it needs

`tests/anatomy/test_ollama_llama_server_pin.py` — offline, fast, no live host,
no brew. Models `test_wing_frankenphp_version_pin.py`. Five assertions:

1. **`test_ollama_version_pinned_as_semver_literal`** — `ollama_version` exists
   in `default.config.yml` and is a `^\d+\.\d+\.\d+$` string.
2. **`test_ollama_version_is_stock_jinja_safe`** — the raw YAML line carries no
   `{{` and no `|` (the `{{ vars }}` trap guard — same as the FrankenPHP gate).
3. **`test_ollama_use_local_tap_var_present_and_bool`** — `ollama_use_local_tap`
   exists and is a real bool default (stock-Jinja safe), so it is defined
   *before* core-up and cannot slip past `default()` (memory
   `version-pins-default-config-shadow` 2nd variant).
4. **`test_openclaw_role_install_is_not_state_latest`** — `roles/pazny.openclaw/
   tasks/main.yml` no longer contains `state: latest` for the ollama install
   (regex: the homebrew task installing `ollama` must use `state: present`, not
   `latest`).
5. **`test_openclaw_role_has_llama_server_preflight`** — the role tasks must
   (a) reference `llama-server` in a `find`/`stat`, (b) `ansible.builtin.fail`
   on the missing-runner condition, and (c) reference `ollama_version` in the
   refuse path — exactly the three things that make a broken keg a provisioning
   failure instead of a silent 500.

This gate fails today (no `ollama_version`, no preflight, `state: latest`
present) and passes only after the fix lands — the definition of a real gate.

Run: `python3 -m pytest tests/anatomy/test_ollama_llama_server_pin.py -q`.

Also re-confirm the whole suite stays green and
`ansible-playbook main.yml --syntax-check` is clean (the new tasks are
straight builtins, so syntax-check is the cheap guard).

---

## 5. Risks

1. **`pazny/local` tap is operator-local, not in-repo.** The HEAD-formula source
   build lives only on the operator's box (memory). This plan does NOT vendor a
   formula into the repo (that is a separate, larger decision — shipping a
   Homebrew formula in nOS). `ollama_use_local_tap: true` therefore *assumes the
   operator has already run* `brew tap-new pazny/local` + dropped the formula.
   The task must **detect a missing tap and fail with the exact `brew tap-new`
   instruction**, not silently fall through to a core install. Flag for review:
   should v0.7 vendor the formula under `files/anatomy/homebrew/`? (Recommend
   deferring — out of scope; the preflight + pin already close the *silent*
   failure, which is the actual bug.)

2. **Hard-fail vs the "Ollama never aborts core" stance.** Covered in §3.3 — the
   `openclaw_require_runner` escape hatch resolves it. If review prefers the
   warning-only default, the gate must assert the *capability to fail* exists,
   not that it is unconditionally on.

3. **`Cellar/ollama` path drift.** `find.paths` is brew-prefix + Cellar-layout
   dependent. Mitigated by the read-only host verification (§7) before pinning,
   and by the gate asserting the *mechanism* (`find` for `llama-server`) not the
   literal path.

4. **`state: present` skips a wanted upgrade.** Switching off `latest` means a
   genuinely-needed Ollama upgrade now requires an operator `brew upgrade` +
   `ollama_version` bump. This is the *intended* trade (no silent drift) and
   matches `version-pins-default-config-shadow` doctrine, but it is a behavior
   change — call it out in the README + the impl PR body.

5. **Linux / `nos_pkg_manager != homebrew`.** Every new task is gated
   `when: nos_pkg_manager == 'homebrew'` so the Linux integration wet-test
   (the gating job) is byte-unaffected. The gate (§4) is pure-Python file
   inspection — Linux-safe.

---

## 6. Stock-Jinja / shadow traps (NON-NEGOTIABLE)

- `ollama_version` and `ollama_use_local_tap` are **bare literals** in
  `default.config.yml` (no filter, no `{{ }}`) → cannot trip the `{{ vars }}`
  eager-resolve trap. Asserted by gate #2 and #3.
- Both vars are defined in `default.config.yml` (loads **before** core-up), so
  even though `roles/pazny.openclaw/defaults/main.yml` mirrors them, the
  config-level definition is the one that satisfies the "every-ref-resolves-
  before-core-up" gate (`test_config_stock_jinja_only.py`). A role default alone
  would NOT — memory `version-pins-default-config-shadow` 2nd variant (the
  `app_secrets` bite). The mirror in role defaults is for standalone-role
  invocation only.
- After implementing, run `python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py -q`
  to confirm the new vars resolve before core-up.

---

## 7. Verification recipe (all READ-ONLY on the live host)

Pre-impl host reconnaissance (to pin the right version + confirm the runner path
— **no writes**):

```bash
# 1. What version is the proven-good live keg? → this is the pin.
ollama --version

# 2. Where does llama-server actually live in the keg? → confirms find.paths.
find "$(brew --prefix)/Cellar/ollama" -name 'llama-server' 2>/dev/null

# 3. Does the live API actually serve text (sanity that current keg is good)?
curl -fsS http://127.0.0.1:11434/api/version
# (do NOT run a generate that loads a 14b model unsupervised; the find above is
#  the structural proof, the curl is just daemon-liveness.)

# 4. Is the core bottle fixed upstream yet? → informs ollama_use_local_tap.
curl -fsS https://formulae.brew.sh/api/formula/ollama.json | grep -c llama-server
```

Post-impl, in-repo (no live system):

```bash
# Gate is red before the fix, green after.
python3 -m pytest tests/anatomy/test_ollama_llama_server_pin.py -q

# Stock-Jinja / before-core-up resolution holds.
python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py -q

# Full anatomy suite stays green.
python3 -m pytest tests/anatomy -q

# Playbook still parses.
ansible-playbook main.yml --syntax-check
```

A future supervised blank (operator-run, NOT overnight) is the true end-to-end
proof: a fresh box with a llama-server-less core bottle must now **fail the
playbook at the preflight with the exact remediation message**, instead of
reporting green while every agent 500s.

---

## 8. Out of scope (explicit)

- Vendoring the `pazny/local` Ollama formula into the repo (separate decision;
  the pin + preflight already close the *silent* failure).
- Changing the model set, the MLX env-var tuning, or the launchd wrapper.
- Any Linux/CUDA Ollama path (OpenClaw on Linux is deferred per v0.4-beta).
- Auto-upgrading Ollama (deliberately replaced by the explicit pin + operator
  `brew upgrade`).
