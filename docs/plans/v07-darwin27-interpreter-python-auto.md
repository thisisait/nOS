# Plan — Darwin 27 `interpreter_python = auto` hard-pin (custom-module yaml crash)

**Status:** PLAN (not implemented). Branch: `feat/v0.7-overnight`.
**Owner:** pazny. **Confirmed item:** `v07-darwin27-interpreter-python-auto`.
**Class:** macOS forward-compat / portability hardening — defeat Ansible's
interpreter auto-discovery on future Darwin releases so the custom modules
(`nos_state`, `nos_migrate`, …) never dispatch through Apple's pyyaml-less
`/usr/bin/python3` and crash a blank run with `ModuleNotFoundError: No module
named 'yaml'`.

> **Scope envelope:** this is a **repo-only config + gate** change. No live
> mutation, no playbook run, trivially reversible (a one-line cfg edit + one
> test file). It is fully inside the unsupervised-overnight rules.

---

## 1. Problem / why

### 1.1 The mechanism (verified against the installed ansible-core)

`ansible.cfg` currently ships `interpreter_python = auto` (line 8). With `auto`,
on the **first** `gather_facts` Ansible probes the host with
`INTERPRETER_PYTHON_FALLBACK` (verified in
`ansible/config/base.yml`) and caches `discovered_interpreter_python` onto the
host *before* play-vars / inventory pins reach module dispatch. The fallback
list (installed ansible-core 2.20.5, confirmed live) is:

```
python3.14 → python3.13 → python3.12 → python3.11 → python3.10 →
python3.9 → /usr/bin/python3 → python3
```

probed **by bare name on the discovery PATH first**, and the ultimate hard
fallback is `_FALLBACK_INTERPRETER = '/usr/bin/python3'`
(`ansible/executor/interpreter_discovery.py:12`).

On Apple Silicon macOS there are **two** Pythons in play:

- Homebrew's (`/opt/homebrew/bin/python3` → `python@3.14` → has pyyaml,
  ansible-core, jinja2 — the operator interpreter the playbook bootstraps).
- Apple's CommandLineTools (`/usr/bin/python3`, currently 3.9 — **no pyyaml**).

**The trap (already documented doctrine — memory `feedback_ansible_python_interpreter`):**
the cached `discovered_interpreter_python` overrides BOTH the inventory host-line
pin (`inventory:4` → `ansible_python_interpreter=/opt/homebrew/bin/python3`) AND
any play-`vars` pin **for custom modules** (`nos_state`, `nos_migrate`). Built-in
modules that template `argv: ['{{ ansible_python_interpreter }}', …]` dodge it;
custom modules dispatch through the cached discovery → load on Apple Python 3.9
→ `nos_state` crashes `ModuleNotFoundError: No module named 'yaml'`. This was
**reproduced on a clean blank 2026-05-10**; inventory and play-var pins did NOT
fix it; only a hard `interpreter_python = <abs path>` cfg pin did.

### 1.2 Why "Darwin 27" specifically — the forward-compat cliff

Today (`sw_vers` = macOS 26.3.1, Darwin 25.x) `auto` *happens* to resolve to
`/opt/homebrew/bin/python3.14` — verified live via a dry `setup` probe. **That is
luck of PATH ordering, not design.** The fallback list probes bare `python3.14`
first; on this host Homebrew's shim wins the PATH race. But the resolution is
fragile across exactly the cases a future operator hits:

1. **Fresh host, pre-bootstrap.** Before `pazny.mac.homebrew` + `tasks/python.yml`
   run, Homebrew's versioned `python3.14` may not be on the discovery PATH yet,
   while Apple's `/usr/bin/python3` always is → `auto` lands on Apple Python on
   the very first `gather_facts`, caches it, and the custom-module dispatch is
   poisoned for the whole run. (The preflight pip task installs pyyaml into the
   *operator* interpreter, not into Apple's `/usr/bin/python3`.)
2. **Darwin 27 / future macOS.** When Apple bumps the system Python's bare-name
   shims (or a new Darwin reshuffles `/usr/bin` precedence, or Homebrew lags the
   OS bump), the bare-name `python3.14`/`python3.13` probes can resolve to Apple
   shims ahead of Homebrew. The `/usr/bin/python3` hard fallback at the tail of
   the list is the explicit failure mode the doctrine warns about. "Darwin 27" is
   shorthand for *the next macOS where the current PATH-luck stops holding*.
3. **The CI already pays this tax.** `.github/workflows/ci.yml` proves the bug is
   real and unsolved-by-pins on macOS runners: the integration job does
   `echo "interpreter_python = $PY" >> ./ansible.cfg` (a cfg pin), sets
   `ANSIBLE_PYTHON_INTERPRETER` (env pin), AND passes
   `-e ansible_python_interpreter="$PY"` (extra-vars, highest precedence) — three
   layers — and the macOS integration job is *still* `continue-on-error: true`
   because the runner's custom-module discovery ignores all three (CLAUDE.md
   "Known Tech Debt"; memory `ci-diagnose-by-comparison`). The operator Mac is not
   that runner, but the **mechanism is identical** — a hard cfg pin to an absolute
   path is the one lever that worked locally.

### 1.3 Why it is debt, not a working feature

The repo's own committed doctrine says the fix and then **does not apply it**:

- Memory `feedback_ansible_python_interpreter`: *"For macOS Apple Silicon hosts,
  hard-pin `interpreter_python = /opt/homebrew/bin/python3` in `ansible.cfg`. The
  play-vars + inventory pins remain as belt-and-suspenders but are NOT sufficient
  on their own when `auto` is in play."*
- Yet `ansible.cfg:8` is still `interpreter_python = auto`.

So the operator install is one fresh-host blank or one macOS upgrade away from the
exact 2026-05-10 crash, with the documented fix sitting un-applied. The inventory
pin (`/opt/homebrew/bin/python3`) is the belt; the cfg is missing the suspenders.

---

## 2. Scope (explicit)

**In scope — repo edits only, ship tonight, fully gated:**

- Change `ansible.cfg` `interpreter_python = auto` → a **platform-aware hard pin**
  that resolves to Homebrew's Python on macOS and does NOT break Linux (where
  `auto` is correct and there is no Apple-Python trap). The Linux port
  (`feat/linux-port`, v0.4-beta) means a bare `interpreter_python =
  /opt/homebrew/bin/python3` would now break the Ubuntu CI wet-test — so the pin
  must be conditional. See §3 for the chosen mechanism (env-var indirection with
  an `auto` fallback, so Linux keeps `auto` and macOS gets the absolute path).
- A new anatomy gate `tests/anatomy/test_interpreter_python_pin.py` that pins the
  contract: cfg is NOT bare `= auto`, the macOS path is an absolute Homebrew
  interpreter, the inventory belt-pin still agrees, and the Linux/CI path is
  preserved.
- Mirror the change into `tests/ansible.cfg` IF the chosen mechanism touches the
  `[defaults]` keys CI copies (the CI integration step does
  `cp tests/ansible.cfg ./ansible.cfg` then appends its own `interpreter_python`
  — see §3.3 for the interaction; the plan must not double-pin or fight the CI
  append).
- Doc reconciliation: flip the memory/CLAUDE.md line from "should hard-pin" to
  "hard-pinned (env-indirected, Linux-safe)".

**Out of scope (explicitly NOT tonight):**

- Any playbook run (`ansible-playbook main.yml`, blank, idempotence). The change
  is config-only; `--syntax-check` is the playbook-side proof and is non-mutating.
- Touching the operator's `~/.ansible`, the live containers, or `~/.nos/`.
- The CI `continue-on-error: true` on the macOS integration job — that is a *runner*
  quirk (discovery ignores even extra-vars there) and a separate item; this plan
  fixes the **operator-Mac** path, which a hard cfg pin demonstrably does fix
  locally. Do NOT flip `continue-on-error` as part of this.
- Reworking the inventory pin or the CI's three-layer pin scaffold — they stay as
  belt-and-suspenders; this adds the missing cfg suspender only.

---

## 3. Approach (exact files + edits)

### 3.1 The chosen mechanism — env-indirected pin, `auto` as Linux default

A **bare** `interpreter_python = /opt/homebrew/bin/python3` is wrong now that
Linux is supported (v0.4-beta: the Ubuntu integration job runs `main.yml`
end-to-end; that path has no `/opt/homebrew` and `auto` is the *correct* answer
on Linux — there is no Apple-Python sibling to collide with). The memory note
itself flags this: *"When Linux support lands, either keep the pin and let Linux
plays override at play-vars scope, OR conditionalize ansible.cfg via env var
(`ANSIBLE_PYTHON_INTERPRETER=…`)."* The env-var route is cleaner and is the one
this plan takes.

ansible-core's INI value supports env templating: set

```ini
# ansible.cfg  [defaults]
# macOS hard-pin (defeats interpreter auto-discovery's Apple-Python trap on
# fresh hosts / future Darwin — see docs/plans/v07-darwin27-interpreter-python-auto.md).
# Env-indirected so Linux/CI keeps the correct `auto` (no Homebrew, no Apple-py
# collision); the operator-Mac path resolves the absolute Homebrew interpreter.
interpreter_python = {{ ENV_NOS_INTERPRETER_PYTHON | default('auto') }}
```

> **Verify the templating syntax against installed ansible-core before
> implementing.** ansible-core resolves `{{ lookup('env','X') }}` / `{{ X }}`
> patterns inside INI values via its config templating, but the exact accepted
> form differs by version. If INI-value env-templating is NOT reliable on the
> pinned 2.20.5 + 2.21.0 toolchain, **fall back to mechanism B** (§3.2). The
> implementer MUST confirm with `ansible-config dump | grep INTERPRETER_PYTHON`
> on a Mac (expects the absolute path) and on the Ubuntu CI (expects `auto`)
> before claiming the gate green. Do not ship the templated form unverified.

The macOS shell profile / the playbook's own environment exports
`NOS_INTERPRETER_PYTHON=/opt/homebrew/bin/python3` on Darwin only. Concretely the
pin's *value source* is set in `tasks/_platform.yml` (already the platform seam)
— but note **cfg is read at process start, before any task runs**, so the env var
must be present in the operator's shell, not set by a task. That asymmetry is why
mechanism B may be preferable; see §3.2.

### 3.2 Mechanism B (fallback if INI env-templating is unreliable) — RECOMMENDED default

Because `ansible.cfg` is read at `ansible-playbook` process start (before
`tasks/_platform.yml` runs), a task-set env var cannot influence it. The robust,
version-proof mechanism is the one the **memory doctrine literally prescribes**
and that the CI already half-implements:

1. **Hard-pin the absolute macOS path in `ansible.cfg`:**

   ```ini
   interpreter_python = /opt/homebrew/bin/python3
   ```

   This is byte-for-byte the doctrine fix and fixes the operator Mac. `python3`
   (unversioned Homebrew symlink) is deliberate — it survives a `python@3.14 →
   3.15` Homebrew bump (verified live: the symlink retargets, the path is stable).

2. **Keep Linux correct without a per-OS cfg.** Linux/CI overrides the pin via
   the **already-present** higher-precedence lever: the Ubuntu integration job
   uses `tests/ansible.cfg` (which has NO `interpreter_python` line) via
   `cp tests/ansible.cfg ./ansible.cfg`, so the macOS absolute path never reaches
   Linux CI in the first place. For a *real* Linux operator running the root
   `ansible.cfg`, the inventory/play-var pin + extra-vars override at play scope
   wins for built-ins, and for custom modules Linux has no Apple-Python trap (the
   single system `python3` is correct) — but to be safe the Linux operator path
   should set `ANSIBLE_PYTHON_INTERPRETER=/usr/bin/python3` (already the
   `nos_docker_bin`-style platform reality) OR the plan ships a documented
   `ANSIBLE_CONFIG`/env override. **Decision for the implementer:** confirm
   whether any committed Linux entrypoint reads the *root* `ansible.cfg` (the CI
   doesn't — it copies `tests/ansible.cfg`). If nothing does, mechanism B's bare
   absolute pin is safe as-is and the Linux concern is moot for CI.

> **Plan's recommendation:** implement **mechanism B** (bare absolute Homebrew
> pin in root `ansible.cfg`), because (a) it is the exact doctrine fix, (b) the
> root cfg is provably macOS-only on the committed paths (CI copies
> `tests/ansible.cfg`), and (c) it has zero version-fragile INI templating. Keep
> mechanism A documented as the option if a future Linux operator is found to read
> the root cfg directly. The gate (§4) pins whichever lands.

### 3.3 CI interaction — do NOT double-pin

`.github/workflows/ci.yml` (syntax + both integration jobs) does:

```
cp tests/ansible.cfg ./ansible.cfg          # overwrites root cfg → no interpreter line
echo "interpreter_python = $PY" >> ./ansible.cfg   # appends the runner's $PY
```

So **CI never sees the root `ansible.cfg`'s pin** — it builds its own from
`tests/ansible.cfg` + an appended `$PY`. This means:

- Mechanism B changing the **root** cfg cannot affect CI (it's overwritten). 
- `tests/ansible.cfg` must stay WITHOUT an `interpreter_python` line, or the CI's
  `>>` append would create a duplicate key (last-wins in INI, but messy). The gate
  must assert `tests/ansible.cfg` has **no** `interpreter_python` line so the CI
  append remains the single source on the runner.
- The Linux integration job's `$PY` is the runner's setup-python path — correct.
  Untouched.

### 3.4 Inventory belt stays

`inventory:4` keeps `ansible_python_interpreter=/opt/homebrew/bin/python3` as the
belt. The cfg hard-pin is the suspenders for custom modules. The gate asserts the
two **agree** (both Homebrew Python) so a future edit can't split them.

### 3.5 No live mutation

Editing `ansible.cfg` changes how the *next* `ansible-playbook` invocation
dispatches modules; it renders nothing, recreates no container, writes nothing to
`~/.nos/` or the live system. `--syntax-check` exercises the cfg read path without
mutation. Overnight stays repo-only.

---

## 4. The gate (NON-NEGOTIABLE — every fix ships a gate)

New file: **`tests/anatomy/test_interpreter_python_pin.py`** (offline, fast, no
network, no live system, no playbook run). Pattern: static read of `ansible.cfg`
/ `tests/ansible.cfg` / `inventory`, exactly like
`test_tofu_destroy_guard.py::test_filter_is_discoverable_by_ansible` reads cfg.

Tests:

1. **`test_root_cfg_does_not_use_bare_auto`** — assert the root `ansible.cfg`
   `[defaults]` `interpreter_python` is NOT `auto` (the regression that re-opens
   the Apple-Python trap). Asserts it equals the absolute Homebrew path
   `/opt/homebrew/bin/python3` (mechanism B) — or, if mechanism A landed, that the
   value is the env-indirected template AND that the env default is the Homebrew
   path. Parse with `configparser` (handles the `[defaults]` section).
2. **`test_pin_is_unversioned_homebrew_symlink`** — assert the pinned path is the
   **unversioned** `/opt/homebrew/bin/python3` (not `…/python3.14`), so a Homebrew
   minor bump can't dead-pin it. (Mirrors the version-pin-shadow lesson — don't
   pin a value that silently rots.)
3. **`test_inventory_belt_agrees_with_cfg`** — parse `inventory`; assert the
   host-line `ansible_python_interpreter` equals the cfg pin (belt == suspenders;
   they can't drift to different Pythons).
4. **`test_tests_cfg_has_no_interpreter_line`** — assert `tests/ansible.cfg` has
   NO `interpreter_python` key, so the CI `>> echo "interpreter_python = $PY"`
   append stays the single source on the runner (no duplicate-key mess, Linux CI
   keeps the runner's `$PY`).
5. **`test_ci_still_appends_runner_python`** — assert `.github/workflows/ci.yml`
   still contains the `echo "interpreter_python = $PY" >> ./ansible.cfg` line in
   the integration job(s), i.e. this change did NOT accidentally remove the CI's
   runner-specific override (the macOS-runner path is a *separate* known quirk; we
   must not regress its scaffold).
6. **`test_doctrine_marks_pin_applied`** *(doc-honesty)* — assert CLAUDE.md / the
   relevant doc no longer says the pin is un-applied / "should hard-pin" in the
   present tense (prevents the doc-vs-code falsehood class the gov audit flagged).
   Light-touch: grep for the stale phrasing being absent.

**Why a gate and not just the cfg edit:** the value is one line a future refactor
(or a "let's go back to `auto` for Linux symmetry" instinct) can silently revert,
re-opening a crash that only surfaces on a *fresh-host blank* — the worst place to
discover it. The gate is the contract that `auto` never returns to the root cfg
and that belt/suspenders/CI-append stay coherent. It also red-flags the exact
regression (`= auto`) so the next person sees *why*.

---

## 5. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Bare absolute pin (mechanism B) breaks a real Linux operator who runs the **root** `ansible.cfg` directly (no `/opt/homebrew/bin/python3` on Linux → every module fails to find the interpreter) | medium IF such an entrypoint exists | Verify first: the committed CI Linux path copies `tests/ansible.cfg` (no interpreter line) — root cfg is macOS-only on committed paths. If a Linux entrypoint reading root cfg is found, switch to mechanism A (env-indirected, `auto` default) — gate #1 accepts either form. The implementer MUST grep for any `ANSIBLE_CONFIG`/root-cfg Linux usage before choosing. |
| INI env-templating (mechanism A) not supported on pinned ansible-core 2.20.5/2.21.0 → cfg value is literal `{{ … }}` → discovery silently re-enables, crash returns | medium | §3.1 mandates `ansible-config dump \| grep INTERPRETER_PYTHON` verification on BOTH a Mac and Ubuntu CI before claiming green. This is exactly why the plan **recommends mechanism B** (no templating). Gate #1 asserts the *resolved* value, not the literal, where feasible. |
| Homebrew `python@3.14 → 3.15` bump dead-pins an absolute versioned path | low | Pin the **unversioned** `/opt/homebrew/bin/python3` symlink (verified live: it retargets on bump). Gate #2 enforces unversioned. |
| CI macOS integration job (already `continue-on-error`) behaves differently after the root-cfg change | very low | CI overwrites root cfg with `tests/ansible.cfg` + its own `$PY` append — root cfg change cannot reach it (§3.3). Gate #4/#5 pin that the CI scaffold is untouched. |
| Intel-Mac operator (`/usr/local/bin/python3`, not `/opt/homebrew`) | low (target is M1+ only per CLAUDE.md) | CLAUDE.md hard-scopes to Apple Silicon (`homebrew_prefix: /opt/homebrew`). The inventory comment already notes the Intel override path; document the same one-line override next to the cfg pin. Out of the supported matrix, so not gated. |
| Stock-Jinja vars trap | n/a | No new var added to `default.config.yml`/`default.credentials.yml`; the cfg value is an INI literal read at process start, never walked by the `{{ vars }}` loader. `test_config_stock_jinja_only.py` is unaffected. |
| Someone reverts to `auto` for "Linux symmetry" | low | Gate #1 fails on bare `= auto` in the root cfg with a message naming the Apple-Python trap + this plan. The revert can't land green. |

---

## 6. Deferred (explicitly NOT this item)

- **The macOS CI integration `continue-on-error: true` flip.** That is a *GitHub
  runner* quirk where discovery ignores env + cfg + extra-vars pins (CLAUDE.md
  Known Tech Debt). A hard cfg pin fixed the *operator Mac* locally but the runner
  is a different environment; revert `continue-on-error` only when the runner /
  ansible ships a fix (separate item, needs the runner to reproduce).
- **A self-hosted macOS runner** that would make CI byte-identical to the operator
  Mac (CLAUDE.md "honest caveat") — would let CI prove the pin end-to-end.
  Infrastructure item, deferred.
- **Mechanism A (env-indirected cfg) rollout** if a Linux entrypoint reading the
  root cfg is ever added — only then is the conditional form needed; mechanism B
  suffices for the committed paths today.
- **Pyenv-interpreter alignment.** `tasks/python.yml` installs a pyenv Python
  (`python_version: "3.13"`); the cfg/inventory pin targets the *Homebrew* Python
  (the one with ansible-core + pyyaml). These are intentionally different roles
  (operator runtime vs Ansible's own interpreter). Reconciling them is a separate
  audit, not this item.

---

## 7. Verification recipe

All offline, no live system, no network, no container mutation — safe unsupervised:

```bash
cd /Users/pazny/projects/nOS

# 1. The new gate passes (run it RED first by hand-reverting cfg to `= auto`
#    in a scratch copy to confirm it catches the regression, then GREEN).
python3 -m pytest tests/anatomy/test_interpreter_python_pin.py -v

# 2. Confirm the resolved interpreter on THIS Mac is the Homebrew Python
#    (NOT Apple's /usr/bin/python3) — the whole point of the pin.
ansible-config dump | grep -i INTERPRETER_PYTHON
#   → expect: INTERPRETER_PYTHON(.../ansible.cfg) = /opt/homebrew/bin/python3

# 3. Prove the custom-module dispatch interpreter is the pinned one (the exact
#    path nos_state would load through) — dry, read-only setup probe.
ansible -i inventory 127.0.0.1 -m setup -a 'filter=ansible_python*' \
  | grep -E 'discovered_interpreter_python|executable'
#   → discovered/executable resolves to /opt/homebrew/... , pyyaml present.

# 4. Belt == suspenders: inventory pin and cfg pin name the same Python.
grep interpreter_python ansible.cfg
grep ansible_python_interpreter inventory
#   → both /opt/homebrew/bin/python3

# 5. tests/ansible.cfg has NO interpreter line (CI append stays sole source).
grep -c interpreter_python tests/ansible.cfg   # → 0

# 6. CI scaffold untouched (runner $PY append still present).
grep -n 'interpreter_python = \$PY' .github/workflows/ci.yml   # → still there

# 7. Full anatomy suite stays green (no regression).
python3 -m pytest tests/anatomy/ -q

# 8. Playbook still parses with the new pin (cfg read path exercised, no mutation).
ansible-playbook main.yml --syntax-check
```

Expected: #1 RED on a `= auto` revert (proves it catches the regression), GREEN
after; #2/#3 resolve to `/opt/homebrew/bin/python3` (Apple Python defeated);
#4 belt==suspenders; #5/#6 CI path intact; #7/#8 GREEN — config-only, no render
changes.

> **NOT run tonight:** a fresh-host blank that would *actually* trigger the
> discovery-on-empty-PATH crash — that is the destructive proof and a supervised
> lane. This plan ships the cfg pin + the static gate that pins it; the dry
> `setup`/`ansible-config dump` probes (#2/#3) are the non-mutating evidence the
> pin resolves correctly on this Mac.

---

## 8. Commit shape (when implemented, separate from this plan commit)

```
fix(cfg): hard-pin interpreter_python (defeat Darwin auto trap)

- `auto` lets fresh-host / future-Darwin discovery cache Apple's
  pyyaml-less /usr/bin/python3 → nos_state crashes "No module named
  'yaml'" (the 2026-05-10 blank); inventory+play-var pins lose to it.
- pin root ansible.cfg to /opt/homebrew/bin/python3 (unversioned
  symlink, survives a Homebrew bump); Linux CI copies tests/ansible.cfg
  so the macOS pin never reaches it.
- gate: test_interpreter_python_pin pins no-bare-auto + unversioned +
  belt==suspenders + tests-cfg-clean + CI-append-intact.
```

(Conventional Commits, subject ≤50 chars, surgeon-tone body ≤6 bullets, no
Co-Authored-By, no `--author`, branch-only — never pushed.)
