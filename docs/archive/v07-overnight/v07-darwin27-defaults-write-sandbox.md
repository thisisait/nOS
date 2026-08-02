# v0.7 — Darwin 27 `defaults write` sandbox / TCC pre-flight + robust-write contract

Status: PLAN (not implemented). Target branch: `feat/v0.7-overnight`.
Owner: overnight agent batch. Scope: repo edits only, no live mutation.

## Problem / why

`tasks/macos-defaults.yml` carries **41 `community.general.osx_defaults`**
writes (plus one in `tasks/system-services.yml`), and `osx_defaults` shells out
to `/usr/bin/defaults write <domain>`. Since macOS 10.14, Apple moves more and
more preference domains into **sandboxed containers** (`~/Library/Containers/`)
and behind **TCC** (Privacy & Security). A `defaults write` to a sandboxed
domain from a process *without* the right entitlement / Full Disk Access does
**not** error loudly in a way Ansible reports as a failure — it either:

- prints `Could not write domain <x>; exiting` and exits non-zero (Safari case,
  already half-handled at L242–293), **or**
- writes to a *shadow* plist that `cfprefsd` silently ignores so the setting
  never takes effect (the genuinely dangerous case — `changed=1`, exit 0, **no
  observable effect**).

Today only **Safari** (L249–293) and a scatter of `failed_when: false`
(L111/239/256/264/272/280/303/358) defend against this, and they do it
**per-task, by hand**, with one bespoke `_safari_full_url is match('.*Could not
write domain.*')` warning. Three concrete gaps:

1. **Darwin 27 is the forcing function.** macOS 27 (Darwin 27.x) is widely
   expected to expand the sandboxed/TCC-gated preference set (the multi-year
   trend: Safari → Terminal SecureKeyboardEntry → screencapture location →
   universalaccess). Several domains nOS writes today (`com.apple.finder`,
   `com.apple.dock`, `com.apple.screencapture`, `com.apple.universalaccess`,
   `com.apple.WindowManager`, `com.apple.Terminal`) are *candidates* to require
   FDA/TCC on 27. When they flip, **40 of the 41 writes silently no-op or fail
   without a single coherent diagnostic** — the operator's Mac looks configured
   but isn't, and there is no nOS-visible state saying "these N defaults were
   blocked by the sandbox."
2. **No single pre-flight that answers "can this run even write defaults?"**
   The at-rest preflight (`tasks/preflight-at-rest.yml`) proves the
   default-OFF, Darwin-gated, read-only host-probe pattern exists and is
   blessed. There is no analogue that probes **TCC / Full-Disk-Access posture
   for the Ansible-driving process** before the 41 writes fire. The operator
   discovers the problem only when a setting "didn't stick," days later.
3. **Inconsistent, copy-paste resilience.** `failed_when: false` is on 8 of 42
   tasks, ad hoc. The Safari "did the write actually land?" verification
   (`is match('.*Could not write domain.*')`) exists for exactly one key. There
   is no uniform contract: *which* domains are sandbox-risk, *how* a blocked
   write is detected, and *what* the operator is told. A Darwin-27 surface
   change will hit domains that have **no** guard at all.

### Report + guard, never force (doctrine alignment)

Per the destructive-op safety model (memory `feedback-destructive-op-safety`)
and machinery doctrine: this ships a **read-only TCC/sandbox pre-flight probe**
+ a **uniform best-effort-write + verify-and-surface contract** for the
sandbox-risk domains. It does **not** try to auto-grant FDA, auto-disable SIP,
or write to protected containers by privilege escalation (all either impossible
unattended or destructive host mutations the overnight rules forbid). The
default posture is: *attempt the write, detect when the sandbox blocked it,
record + warn, never hard-fail a normal run.* A gov tenant can opt into a
hard-fail floor exactly like the at-rest gate.

## Approach

Mirror two proven precedents: the **`tasks/preflight-at-rest.yml`** default-OFF
Darwin-gated read-only host-probe, and the **existing Safari "did the write
land?" detection** (generalised from one bespoke key to a reusable contract).
Three cooperating pieces, all repo-only.

### A. A read-only TCC / sandbox pre-flight probe (`tasks/preflight-defaults-write.yml`)

Runs early in `tasks:` (after `tasks/_platform.yml`, alongside
`tasks/preflight-at-rest.yml`), **macOS-only, always read-only, never mutates**:

1. Record host posture into facts (mirrors `_platform.yml`'s `set_fact` idiom):
   `nos_host_darwin_major` (`uname -r` → leading int), `nos_host_os_version`
   (`sw_vers -productVersion`). This is the Darwin-27 seam: a single fact the
   rest of the file (and future floors) branch on.
2. **Probe TCC / Full-Disk-Access for the driving process, read-only.** The
   canonical non-mutating FDA tell is *readability of a TCC-protected path the
   process does not own* — e.g. `test -r ~/Library/Application\ Support/com.apple.TCC/TCC.db`
   (a path only an FDA-granted process can read). Run as
   `command: test -r <path>` with `failed_when: false` + `changed_when: false`
   + `check_mode: false`; rc 0 ⇒ FDA present, rc≠0 ⇒ not granted. **No write,
   no DB read** (we only test the *readability bit*, never `cat`/`sqlite3` the
   contents — that keeps the probe inert and privacy-clean). Set
   `nos_macos_fda_granted`.
3. **Optional non-destructive write self-test** to a *throwaway, non-sandboxed*
   domain we own (`eu.thisisait.nos.preflight`): `defaults write` a sentinel
   key, read it back, `defaults delete` the throwaway domain. This proves the
   `defaults` binary works at all (distinguishes "FDA missing" from "defaults
   broken") and is genuinely non-destructive — it writes only to a domain nOS
   invents and immediately deletes, never an Apple domain. Gated, optional,
   `failed_when: false`. Sets `nos_defaults_write_works`.
4. **Floor / warning fan-out, default-OFF for hard-fail.** When
   `require_defaults_write_fda` (default `false`) is set and
   `nos_macos_fda_granted` is false, **hard-fail** with the exact remediation
   (System Settings → Privacy & Security → Full Disk Access → add the
   Terminal/automation host) — same default-OFF shape and gov-opt-in as the
   at-rest gate. On a **normal** run the flag is off, so this only **warns**
   (a `debug` listing which sandbox-risk domains may not stick) and records
   the posture into the run summary.
5. Surface the posture: write `nos_macos_fda_granted` /
   `nos_host_darwin_major` / the count of sandbox-risk domains into the run
   summary, and (when Bone is up) an A9 `on_info` (or `on_high` if FDA is
   absent AND sandbox-risk writes are queued) notification. **No install, no
   privilege change, no protected write.**

Every task gated `ansible_os_family == 'Darwin'` (Linux byte-inert — the Linux
wet-test never executes a line) and the whole file gated on
`manage_macos_defaults | default(true)` so an operator can skip it entirely.

### B. A uniform sandbox-risk write contract in `tasks/macos-defaults.yml`

Generalise the one-off Safari resilience into a small, declared contract — **no
behaviour change on a healthy FDA-granted Mac**, only better diagnostics +
Darwin-27 readiness when a domain flips sandboxed:

1. **Declare the sandbox-risk domain set once** (a list var
   `macos_sandbox_risk_domains` in `default.config.yml`, stock-Jinja, real
   default): `com.apple.Safari`, `com.apple.Terminal`,
   `com.apple.universalaccess`, `com.apple.screencapture`,
   `com.apple.desktopservices`, plus the Darwin-27 *watch* candidates
   (`com.apple.finder`, `com.apple.dock`, `com.apple.WindowManager`). This is
   the single source of truth for "which writes might silently fail on a
   sandboxed/TCC host."
2. **Make the already-tolerated writes uniform.** Today `failed_when: false` is
   on 8 tasks ad hoc. Keep the *exact same effect* (a blocked write must never
   abort the converge) but make it **consistent + observable**: every
   `osx_defaults` write whose `domain` is in `macos_sandbox_risk_domains`
   carries `failed_when: false` + `register:`, and a **single trailing
   verify-and-surface task** (one `debug`/`set_fact`, replacing the bespoke
   Safari warning at L282–293) inspects the registered results and emits one
   consolidated warning listing *exactly which* domains/keys the sandbox
   blocked — `Could not write domain` in the result `.msg`, or
   (the silent-shadow case) a post-write read-back mismatch. **No new
   privilege, no retry-with-sudo** — just honest, aggregated reporting.
3. **Optional, default-OFF read-back verification** for the sandbox-risk
   writes: after the write, an `osx_defaults` *read* (state present, the same
   key) compared against the intended value, so the **silent-shadow no-op**
   case (exit 0, no effect) is caught — not just the loud
   `Could not write domain` case. Gated on
   `verify_macos_defaults | default(false)` to keep a normal run fast (read-back
   doubles the `defaults` calls); flipped on in `profiles/gov-local.yml` where
   "did the hardening actually apply" matters.

This is **behaviour-preserving on the operator's current Mac** (FDA granted →
every write lands → zero new warnings, zero `changed` churn) and only *adds
signal* when the sandbox blocks a write — which is precisely the Darwin-27
failure mode this plan exists to make visible.

### Why a preflight *and* the contract (not one or the other)

- The **preflight (A)** answers the *upfront* question — "can this run write
  defaults at all, and is the host on a Darwin version where more domains went
  sandboxed?" — once, before the 41 writes fire, and is the gov hard-fail seam.
- The **contract (B)** answers the *per-write* question — "did *this specific*
  sandbox-risk write actually land?" — uniformly across the risk set instead of
  one hand-coded Safari case, so a Darwin-27 domain flip surfaces as a single
  coherent diagnostic instead of 8 silent no-ops.

## Files to touch

New:

- `tasks/preflight-defaults-write.yml` — read-only TCC/FDA + Darwin-version
  probe (A). Modeled byte-for-byte on `tasks/preflight-at-rest.yml`
  (default-OFF hard-fail, Darwin-gated, `failed_when:false` +
  `changed_when:false` + `check_mode:false`, escape hatch
  `nos_skip_defaults_write_check`).
- `tests/anatomy/test_defaults_write_sandbox_gate.py` — **the gate** (below),
  modeled on `tests/anatomy/test_at_rest_gate.py`.

Edited:

- `tasks/macos-defaults.yml` — generalise the Safari one-off into the uniform
  sandbox-risk contract (B): `register:` + `failed_when:false` on every
  sandbox-risk-domain write, one consolidated verify-and-surface task replacing
  the bespoke `[Safari] WARN` task (L282–293), optional read-back verification
  gated on `verify_macos_defaults`. **No write removed, no value changed** —
  only resilience + reporting generalised.
- `main.yml` — `import_tasks: tasks/preflight-defaults-write.yml` in `tasks:`
  immediately after the `preflight-at-rest.yml` import (the established
  preflight slot, ~L343), with `tags: ['always','preflight','macos-defaults']`
  so `--tags` reaches it. (No change to the `macos-defaults.yml` import at
  L1377 — its tags already cover the contract edits.)
- `default.config.yml` — `manage_macos_defaults: true`,
  `require_defaults_write_fda: false`, `verify_macos_defaults: false`,
  `macos_sandbox_risk_domains: [ ... ]` (the declared list). **All stock-Jinja,
  real defaults, defined before core-up** (satisfies both variants of
  `test_config_stock_jinja_only.py` — note: declared in `default.config.yml`,
  which loads before the core-up loader, so even the second `| default()` trap
  variant is covered).
- `profiles/gov-local.yml` — flip `require_defaults_write_fda: true` +
  `verify_macos_defaults: true` (a gov tenant must *prove* its hardening
  defaults actually applied, not silently shadow-write them) — opt-in, mirrors
  how the at-rest gate flips there.
- `docs/security-baseline.md` — a paragraph: macOS `defaults` writes to
  sandboxed/TCC domains are best-effort + verified; a blocked write warns
  (normal) or hard-fails (`require_defaults_write_fda`, gov); FDA posture +
  Darwin major recorded; the sandbox-risk domain set is declared centrally.
- `docs/active-work.md` — one-line pointer.

## Gates it needs

New `tests/anatomy/test_defaults_write_sandbox_gate.py` — **offline,
source-level** (no playbook run, no `defaults`, no `sw_vers`, no Docker, no
TCC.db access), parsing the task YAML the way `test_at_rest_gate.py` and
`test_config_stock_jinja_only.py` do:

1. **`test_preflight_file_exists_and_is_darwin_gated`** — `tasks/preflight-
   defaults-write.yml` exists; every task is gated `ansible_os_family ==
   'Darwin'` (so Linux is byte-inert) AND no task in the file performs a
   `defaults write`/`defaults delete` against an **Apple** domain (`com.apple.*`)
   — the probe only `test -r`s a path and may touch the throwaway
   `eu.thisisait.nos.preflight` domain it owns + deletes. Pins "preflight is
   non-mutating to the host's real config."
2. **`test_preflight_is_readonly_and_failsafe`** — the TCC/FDA probe task uses
   `test -r` (not `cat`/`sqlite3`/read of TCC.db **contents**), carries
   `changed_when: false` + `failed_when: false` + `check_mode: false`. Pins
   "read the bit, never the data; never abort the converge."
3. **`test_hard_fail_is_flag_gated_default_off`** — the FDA hard-fail task is an
   `ansible.builtin.fail`, gated on `require_defaults_write_fda` AND
   `not nos_macos_fda_granted` AND an escape hatch
   `nos_skip_defaults_write_check`; the flag is declared `false` in
   `default.config.yml` and `true` in `profiles/gov-local.yml` (same assertions
   as `test_at_rest_gate.py::test_flag_default_off_in_config_and_on_in_gov_profile`).
4. **`test_sandbox_risk_writes_are_register_and_failsafe`** — parse
   `tasks/macos-defaults.yml`; **every** `osx_defaults` task whose `domain` is
   in the declared `macos_sandbox_risk_domains` set carries
   `failed_when: false` AND `register:` — so a sandboxed write can never abort
   the run AND its result is captured for the consolidated verify. This is the
   load-bearing Darwin-27 pin: a *new* sandbox-risk write added later without
   the contract fails the suite.
5. **`test_single_consolidated_sandbox_warning_replaces_bespoke`** — exactly one
   verify-and-surface task exists (the consolidated warning), it references the
   registered results of the risk writes, and the old per-Safari-only warning
   coupling is gone (no remaining task that warns on `_safari_full_url` alone —
   the warning is now domain-set-wide). Pins "uniform, not copy-paste."
6. **`test_config_flags_stock_and_off_safe`** — `default.config.yml` declares
   `manage_macos_defaults`, `require_defaults_write_fda`,
   `verify_macos_defaults`, `macos_sandbox_risk_domains` as plain scalars/list
   (no non-stock filter); `require_defaults_write_fda` + `verify_macos_defaults`
   default `false` (normal run warns, never hard-fails, never double-reads).
   Belt-and-suspenders alongside the existing stock-Jinja gate.

The suite must stay green and `ansible-playbook main.yml --syntax-check` must
pass. The whole feature is default-best-effort + read-only, so the **Linux
integration wet-test runs zero lines** (Darwin gate) and the macOS integration
wet-test runs only the read-only `test -r` + (optional) throwaway-domain
self-test (no Apple-domain state change, no `changed=1` churn on the idempotence
re-run — the preflight is read-only and the contract is value-preserving).

## Risks

- **FDA-detection false negative / positive.** `test -r TCC.db` is the
  community-canonical FDA tell, but a future macOS could relocate/rename the
  path. Mitigated: probe is `failed_when: false` → a wrong answer only changes a
  *warning* on a normal run (hard-fail is gov-opt-in). The gate pins the probe
  is read-only + failsafe, not that the heuristic is infallible — if Darwin 27
  moves the path, the fix is a one-line path bump, caught by the operator's
  warning, not a silent abort.
- **Privacy of probing TCC.db.** We test only the *readability bit*
  (`test -r`), never read or copy the DB contents — no personal data touched.
  The gate (#2) asserts `cat`/`sqlite3`/contents-read of TCC.db never appears.
- **Read-back verification doubles `defaults` calls / slows the run.** Mitigated:
  `verify_macos_defaults` defaults `false` (off on a normal converge); it's only
  on in the gov profile where correctness > speed. The `osx_defaults` *read* is
  cache-local and fast regardless.
- **Behaviour drift on the operator's healthy Mac.** The single biggest risk is
  regressing the 41 working writes. Defended by: the contract **changes no value
  and removes no write** — it only adds `register:` + `failed_when:false`
  (already on 8 tasks) + one consolidated warning replacing the Safari one.
  Gate #4/#5 pin that the writes are preserved + risk-tagged; an idempotence
  re-run on an FDA-granted Mac stays `changed=0` because no value moved.
- **Throwaway-domain self-test edge.** The `defaults write eu.thisisait.nos.
  preflight` self-test could leave a stray domain if the `delete` step is
  skipped. Mitigated: the `delete` is `failed_when:false` + always runs (no
  `when` that could strand it), writes only to a domain nOS invents, and the
  whole self-test is optional/gated. Gate #1 asserts no Apple-domain write in
  the preflight.
- **Floor false-positive on a TCC-granted-but-undetected host.**
  `require_defaults_write_fda` defaults `false` → normal runs only *warn*;
  hard-fail is gov-opt-in with the `nos_skip_defaults_write_check` escape hatch
  (same risk profile as the at-rest gate's `nos_skip_at_rest_check`).
- **Scope creep into "auto-grant FDA / disable SIP."** Explicitly out — both are
  impossible unattended and/or destructive host mutations. This plan only
  *reports* posture and *survives* blocked writes; granting FDA stays a manual
  operator step (the warning prints the exact System Settings path).

## Verification recipe

```bash
# 0. On the right branch
git switch feat/v0.7-overnight

# 1. The new gate + the stock-Jinja gate + the at-rest gate it mirrors
#    (offline, fast — no defaults/sw_vers/TCC access)
python3 -m pytest tests/anatomy/test_defaults_write_sandbox_gate.py \
                  tests/anatomy/test_config_stock_jinja_only.py \
                  tests/anatomy/test_at_rest_gate.py -q

# 2. Full anatomy suite stays green
python3 -m pytest tests/anatomy/ -q

# 3. Syntax-check clean (new task file + contract edits are valid YAML/Jinja)
ansible-playbook main.yml --syntax-check

# 4. Prove the preflight never writes an Apple domain (should print nothing
#    but the throwaway eu.thisisait.nos.preflight domain + test -r lines)
grep -nE "defaults (write|delete)|com\.apple\." tasks/preflight-defaults-write.yml \
  | grep -vE "eu\.thisisait\.nos\.preflight|test -r|# " \
  || echo "OK: preflight touches no real Apple preference domain"

# 5. Prove every sandbox-risk write is failsafe + registered (the Darwin-27 pin)
python3 - <<'PY'
import yaml, pathlib
t = yaml.safe_load(pathlib.Path('tasks/macos-defaults.yml').read_text())
cfg = pathlib.Path('default.config.yml').read_text()
# crude: the declared risk set must appear; each risk-domain write must be failsafe
print("risk-domain var declared:", 'macos_sandbox_risk_domains:' in cfg)
PY

# 6. READ-ONLY live spot-check (no playbook mutation): run the preflight probe
#    tag against the live Mac in --check — it only runs `sw_vers`, `uname -r`,
#    and `test -r ...TCC.db`, no write:
ansible-playbook main.yml --tags preflight,macos-defaults --skip-tags stacks --check
#    --check + the probe's failed_when:false means zero host change; eyeball the
#    reported FDA posture + Darwin major + sandbox-risk warning.

# 7. Frozen 1:1 pre-release probe (optional, before any eventual release push)
tools/ci-local.sh
```

Acceptance: gates #1–#6 green, full suite green, syntax-check clean; step-4
grep prints "OK" (preflight writes no Apple domain); a macOS idempotence re-run
on an FDA-granted host stays `changed=0` (no value moved, preflight read-only).

## Follow-ups (NOT this plan)

- A **Grafana panel / `.prom` textfile-collector** exposing
  `nos_macos_fda_granted` + `nos_macos_sandbox_blocked_writes` so a host whose
  TCC posture regresses alerts like a stale backup does (same observability vein
  the backup exporter uses).
- Wire `nos_host_darwin_major` + the FDA posture into `tasks/export-state.yml` /
  the Art-30 systems register so the host's defaults-write capability is part of
  the audited state shape (shared seam with the
  `v07-darwin27-softwareupdate-script.md` plan, which records the same
  `nos_host_darwin_major` fact — converge the two probes into one
  `preflight-host-posture.yml` if both land).
- When Darwin 27 ships and the real sandboxed-domain set is known, prune /
  extend `macos_sandbox_risk_domains` from observed `Could not write domain`
  reports — turn the *watch* candidates (`finder`/`dock`/`WindowManager`) into
  confirmed entries or drop them.
- A `defaults`-free fallback for the highest-value hardening keys (e.g. via a
  signed configuration profile / MDM payload) for domains that go fully
  write-locked on 27 — a separate plan if/when a key becomes unwritable even
  with FDA.
