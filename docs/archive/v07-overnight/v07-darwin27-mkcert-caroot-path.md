# Plan — Darwin 27 mkcert CAROOT path: single source of truth + hard CA-present assert

Status: PLAN (not implemented). Branch: `feat/v0.7-overnight`.
Scope: repo edits only. No live mutation. No blank. Ships with a pytest anatomy gate.

## 1. Problem / why

The local-TLD TLS flow resolves the mkcert CAROOT **twice, in two different
ways**, and nothing forces the two answers to agree:

1. `tasks/tls-certs.yml` (line ~46) **pins** CAROOT to a hard-coded per-OS
   string derived from the operator HOME:
   - macOS → `{{ HOME }}/Library/Application Support/mkcert`
   - Linux → `{{ HOME }}/.local/share/mkcert`

   It exports that string as `CAROOT=` for the `become: true` `mkcert -install`
   so the root-owned `rootCA.pem`/`rootCA-key.pem` land in the operator HOME
   (then reclaims ownership).

2. `tasks/stacks/core-up.yml` (line ~47) **re-discovers** CAROOT by running a
   bare `mkcert -CAROOT` *as the operator, with no `CAROOT` env set*, then
   copies `<stdout>/rootCA.pem` into `{{ stacks_dir }}/shared-certs/rootCA.pem`
   so containers (Authentik, Grafana, etc.) can trust the local CA during OIDC
   discovery.

These two resolutions are independent. They agree **today** only because:
- the operator does not export `$CAROOT` in their interactive shell profile
  (which Ansible's `command:` inherits via the login shell init), AND
- mkcert's Go `os.UserConfigDir()` on this Darwin build returns exactly
  `$HOME/Library/Application Support` — the value the string in (1) hard-codes.

The fragility this item names ("Darwin 27"): the macOS default-config-dir
contract is a Go-runtime / OS detail, not something nOS controls. If a future
macOS (the Darwin 25→27 line, i.e. the macOS 26 "Tahoe" successor track this
box is already on — `sw_vers` here reports 26.3.1 / Darwin 25.3.0) — or a
future mkcert release, or a stray `export CAROOT=...` in the operator's
`~/.zprofile`, shifts *either* resolver, the two diverge:

- `mkcert -install` writes the CA + trusts it under path **A** (the pinned
  string).
- `core-up` reads path **B** (bare `mkcert -CAROOT`) and copies *its*
  `rootCA.pem` — or, if B has no `rootCA.pem` yet, the copy task's
  `when:` guards (`rc == 0` + `stdout length > 0`) make it **silently skip**.

Failure mode is the worst kind: **silent**. `shared-certs/rootCA.pem` is stale
or missing, the playbook stays green (the copy step just skips), and only later
do containers fail OIDC TLS chain validation against `auth.<tld>` — surfacing
as opaque login breakage, far from the cause. This is exactly the
mkcert-CA-gate class of bug CLAUDE.md flags under "Operator gotchas".

The doctrine comment block in `tls-certs.yml` already states the invariant in
prose — *"Both contexts must agree on one directory"* — but only the
`tls-certs.yml` side enforces it (via the explicit `CAROOT=` env). The
`core-up.yml` side trusts an independent re-derivation and has no assertion
that the CA it is about to publish actually exists.

## 2. Goal

Make the two contexts share **one** resolved CAROOT value, and add a **hard,
loud** assertion that the published `rootCA.pem` exists on the local-TLD path —
so a future Darwin/mkcert/shell-env drift fails fast and legibly instead of
shipping a stale shared CA.

Behaviour-preserving on the happy path (today's resolution is unchanged);
strictly more robust on the drift path. macOS-byte-identical intent for the
public-TLD branch (must still skip cleanly when there is no local CA).

## 3. Exact files / roles to touch

| File | Change |
|------|--------|
| `tasks/tls-certs.yml` | Promote the per-OS CAROOT resolution so it is set **unconditionally** (outside the `tenant_domain_is_local` block) into a stable fact, leaving the `become:`/`-install`/reclaim steps inside the block. (See §4.1 for why the resolution must move out of the block.) |
| `tasks/stacks/core-up.yml` | Replace the bare `mkcert -CAROOT` discovery with: reuse the pinned `_mkcert_caroot_dir` fact when set; keep the `mkcert -CAROOT` call only as a **fallback** for plays that reach core-up without having run `tls-certs.yml` (e.g. `--tags stacks` standalone). Add an `assert` that `<caroot>/rootCA.pem` exists on the local-TLD path before the copy. |
| `tests/anatomy/test_mkcert_caroot_single_source.py` | **New** gate. Static-parse both files; pin the single-source-of-truth + assertion invariants (see §6). |
| (no `default.config.yml` change) | The CAROOT value stays a task-scoped `set_fact`, NOT a config var — so the stock-Jinja vars-trap does not apply. Keep it that way. |

No role compose templates, no plugin manifests, no live system writes.

## 4. Approach

### 4.1 `tasks/tls-certs.yml` — unconditional resolution, gated install

Today the `set_fact` for `_mkcert_caroot_dir` lives **inside** the
`tenant_domain_is_local` block. That is correct for the install leg but means
the fact is undefined on a public-TLD run — fine today because core-up
re-derives independently, but it blocks core-up from *reusing* the fact as the
single source of truth.

Change: lift only the **pure, side-effect-free** resolution `set_fact` to run
unconditionally (it just computes a string from `ansible_os_family` +
`HOME`; harmless on any TLD). Keep `mkcert -install`, the ownership reclaim,
SAN check, cert generation, and chmod **inside** the existing
`tenant_domain_is_local` block (no behaviour change there).

```yaml
# Runs on every TLD — pure string derivation, no side effects. core-up.yml
# reuses this exact value so the install context and the CA-publish context
# can never resolve different directories (Darwin/mkcert/shell-env drift-safe).
- name: "[mkcert] Resolve platform-aware CAROOT (operator HOME default)"
  ansible.builtin.set_fact:
    _mkcert_caroot_dir: >-
      {{ ansible_facts['env']['HOME'] ~ '/Library/Application Support/mkcert'
         if ansible_os_family == 'Darwin'
         else ansible_facts['env']['HOME'] ~ '/.local/share/mkcert' }}

- name: "[mkcert] Install dev CA + generate local-dev wildcard cert"
  when: tenant_domain_is_local | default(true) | bool
  block:
    # ... mkcert -install (CAROOT env = _mkcert_caroot_dir), reclaim, SANs,
    #     generate, chmod — UNCHANGED ...
```

Rationale for keeping it a hard-coded string (not `mkcert -CAROOT`): the
install leg *must* pin CAROOT explicitly because it runs under `become: true`
and a bare default would resolve to **root's** HOME. The string is the
authoritative value; `mkcert -CAROOT` (as operator, no env) merely *happens* to
echo the same thing. Single-sourcing on the string is therefore the correct
direction — we trust the value we forced, not a re-derivation.

### 4.2 `tasks/stacks/core-up.yml` — reuse the fact, fallback, then assert

Replace the current three-task sequence (resolve via bare `mkcert -CAROOT` →
mkdir → copy) with:

```yaml
# CAROOT single source of truth: reuse the value tls-certs.yml forced into
# mkcert -install. Only re-derive via `mkcert -CAROOT` if this play reached
# core-up WITHOUT running tls-certs.yml (e.g. `--tags stacks` standalone),
# in which case the bare default is the best we can do.
- name: "[Core] Resolve mkcert CAROOT (fallback when tls-certs.yml did not run)"
  ansible.builtin.command: mkcert -CAROOT
  register: _mkcert_caroot_fallback
  changed_when: false
  check_mode: false
  failed_when: false
  when: _mkcert_caroot_dir is not defined

- name: "[Core] Pin effective CAROOT (pinned value wins; fallback otherwise)"
  ansible.builtin.set_fact:
    _core_caroot: >-
      {{ _mkcert_caroot_dir
         if _mkcert_caroot_dir is defined
         else (_mkcert_caroot_fallback.stdout | default('') | trim) }}

# Local TLD only: the CA MUST exist before we publish it to containers.
# A stale/missing rootCA.pem here is the silent failure this gate kills —
# fail loud instead of skipping the copy and breaking OIDC TLS downstream.
- name: "[Core] Assert mkcert root CA exists before publishing to containers"
  ansible.builtin.stat:
    path: "{{ _core_caroot }}/rootCA.pem"
  register: _core_caroot_stat
  when:
    - tenant_domain_is_local | default(true) | bool
    - _core_caroot | length > 0

- name: "[Core] Fail loud if local CA is missing/diverged"
  ansible.builtin.assert:
    that:
      - _core_caroot_stat.stat.exists | default(false)
    fail_msg: >-
      mkcert root CA not found at {{ _core_caroot }}/rootCA.pem on a local-TLD
      install. tls-certs.yml's `mkcert -install` and this CA-publish step
      resolved different CAROOT directories (Darwin/mkcert/shell-env drift),
      or `mkcert -install` never ran. Re-run with --tags ssl,stacks.
  when:
    - tenant_domain_is_local | default(true) | bool
    - _core_caroot | length > 0

- name: "[Core] Create shared certs directory for containers"
  ansible.builtin.file:
    path: "{{ stacks_dir }}/shared-certs"
    state: directory
    mode: '0755'
  when: _core_caroot | length > 0

- name: "[Core] Copy mkcert root CA to shared-certs"
  ansible.builtin.copy:
    src: "{{ _core_caroot }}/rootCA.pem"
    dest: "{{ stacks_dir }}/shared-certs/rootCA.pem"
    mode: '0644'
    remote_src: true
  when:
    - _core_caroot | length > 0
    - tenant_domain_is_local | default(true) | bool
```

Notes:
- The assert is gated on `tenant_domain_is_local` so a **public-TLD** install
  (no local CA, by design) still skips cleanly — preserving today's behaviour
  and keeping ubuntu/macOS CI wet-tests green (Docker-less CI never reaches the
  copy; a public-TLD CI run skips the assert).
- The `when: _mkcert_caroot_dir is not defined` fallback keeps
  `tools/nos-stacks.sh stacks` / `--tags stacks` standalone working (those skip
  `tasks/tls-certs.yml`), now with a documented degraded path instead of an
  invisible second resolver.
- All new tasks inherit the existing `tags: ['core', 'always']` convention of
  surrounding core-up tasks (verify against neighbours when implementing).

### 4.3 Stock-Jinja vars trap — N/A by construction

`_core_caroot` / `_mkcert_caroot_dir` are **task-scoped `set_fact`s**, not keys
in `default.config.yml` / `default.credentials.yml`, and they are not consumed
by the `{{ vars }}` plugin-loader namespace. So neither the filter-load gate
nor the every-ref-resolves-before-core-up gate applies. The `set_fact`
expressions use only stock Jinja (`if/else`, `~` concat, `default`, `trim`,
`length`) regardless. Do **not** promote either to a config var.

## 5. Risks

- **R1 — fact persistence assumption.** Reusing `_mkcert_caroot_dir` in core-up
  relies on tls-certs.yml and core-up.yml running in the **same play**.
  Verified: both are `import_tasks` under the single `hosts: all` play
  (`main.yml:1432` tls-certs, `main.yml:1519` core-up); set_fact persists for
  the host across the play. The `is not defined` fallback covers the only path
  that breaks the assumption (standalone `--tags stacks`).
- **R2 — over-strict assert breaking a legitimate path.** The assert is gated
  on `tenant_domain_is_local`; a real public TLD never trips it. The only
  local-TLD case where `rootCA.pem` is legitimately absent is a render-only
  pass that skipped `mkcert -install` (`--skip-tags ssl`); the fail_msg names
  the exact remedy (`--tags ssl,stacks`). Acceptable — this is the loud failure
  we want. (Consider downgrading assert→`debug` + skip if operator feedback
  shows render-only core-up is a common intentional flow; default to assert.)
- **R3 — Darwin path string still hard-coded.** This plan does NOT switch the
  install leg to `mkcert -CAROOT` (it can't — `become` would resolve root's
  HOME). If a future Darwin genuinely changes `os.UserConfigDir()`, the
  hard-coded string in tls-certs.yml is wrong AND the assert now catches it
  loudly (it was silent before). So this plan converts a silent-stale-CA bug
  into a fail-fast — it does not auto-heal a path change. A follow-up (out of
  scope) could compute the string from a `become: false` `mkcert -CAROOT` probe
  run as the operator and feed *that* into the `become: true` install env;
  noted but deferred to avoid a probe-ordering rewrite tonight.
- **R4 — idempotence churn.** New `stat`/`assert`/`set_fact` tasks are
  `changed_when: false` by nature (stat/assert never report changed; set_fact
  reports changed but is benign and already used throughout core-up). The copy
  task is unchanged. No new `changed=` on a steady-state re-run. Confirm in the
  verification recipe.

## 6. Gates it needs (mandatory)

New file `tests/anatomy/test_mkcert_caroot_single_source.py` — offline static
parse of the two YAML task files (no live system, no Docker), in the style of
`test_postgresql_ssl.py`. Assert:

1. **Single source of truth** — `tasks/stacks/core-up.yml` references
   `_mkcert_caroot_dir` (it reuses the pinned fact) AND the bare `mkcert
   -CAROOT` command, if still present, is guarded by `_mkcert_caroot_dir is not
   defined` (fallback only). Regex/string asserts:
   - `"_mkcert_caroot_dir" in core_up_src`
   - if `"mkcert -CAROOT" in core_up_src` then
     `"_mkcert_caroot_dir is not defined" in core_up_src`
2. **Resolution lifted out of the local-TLD block** — in `tasks/tls-certs.yml`,
   the `_mkcert_caroot_dir` `set_fact` appears **before** the
   `when: tenant_domain_is_local` block line (so it runs unconditionally).
   Parse the YAML with `yaml.safe_load`, find the index of the resolve task and
   the index of the install block, assert resolve-index < install-index.
3. **Hard assert present** — `tasks/stacks/core-up.yml` contains an
   `ansible.builtin.assert` whose `that:` checks
   `_core_caroot_stat.stat.exists` and is gated on `tenant_domain_is_local`.
   String asserts on the assert/stat task names + the gate.
4. **Public-TLD safety** — the copy task and the assert are both gated on
   `tenant_domain_is_local` (so a public TLD skips). Assert the substring
   `tenant_domain_is_local` co-occurs with the copy `when:`.
5. **No new config var** — `_core_caroot` / `_mkcert_caroot_dir` do NOT appear
   as top-level keys in `default.config.yml` / `default.credentials.yml`
   (guards the vars-trap by construction). `grep`-style assert: neither token
   starts a line in those two files.

Existing suite must stay green; `test_config_stock_jinja_only.py` must stay
green (no new config var introduced).

## 7. Verification recipe

Read-only / repo-only. No blank, no live mutation.

```bash
# 1. New gate passes, full anatomy suite stays green
python3 -m pytest tests/anatomy/test_mkcert_caroot_single_source.py -q
python3 -m pytest tests/anatomy/ -q

# 2. Stock-Jinja vars trap untouched
python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py -q

# 3. Syntax-check clean (the non-negotiable)
ansible-playbook main.yml --syntax-check

# 4. ansible-lint on the two touched task files (production profile)
ansible-lint tasks/tls-certs.yml tasks/stacks/core-up.yml

# 5. Manual confirm the live resolver matches the pinned string on THIS box
#    (read-only; just proves today's happy path is unchanged)
mkcert -CAROOT
#    expect: /Users/<op>/Library/Application Support/mkcert  (Darwin)
ls -la "$(mkcert -CAROOT)/rootCA.pem"   # the file the assert now guards
```

Optional (operator-supervised, NOT part of the overnight run): a local-TLD
`ansible-playbook main.yml --tags ssl,stacks --check` to confirm no unexpected
`changed=` on the new tasks and that the assert passes on a box with the CA
already installed. Skipped tonight (no live runs).

## 8. Out of scope (deferred, noted for the next pass)

- Auto-healing a genuine Darwin `os.UserConfigDir()` path change by probing
  `mkcert -CAROOT` as the operator and feeding it into the `become` install env
  (R3) — needs a probe-ordering rewrite of the tls-certs block; defer.
- Linux CAROOT (`~/.local/share/mkcert`) gets the same single-source treatment
  for free via the shared fact; no Linux-specific work needed, but the gate
  should not assume Darwin-only strings (keep asserts OS-agnostic where they
  test the *mechanism*, not the *value*).
