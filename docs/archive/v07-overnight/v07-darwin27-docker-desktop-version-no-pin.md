# Plan — Docker Desktop has no version floor on Darwin (v0.7 overnight)

**Status:** PLAN (not implemented). Branch: `feat/v0.7-overnight`.
**Owner:** pazny. **Confirmed item:** `v07-darwin27-docker-desktop-version-no-pin`.
**Class:** missing preflight guard around an unpinned, manually-installed host
dependency — the only nOS dependency with **zero** version assertion. Same shape as
`tasks/preflight-at-rest.yml` (host-property hard-check before the compose layer) and
the `homebrew_prefix` ISA-bound doctrine (`test_homebrew_prefix_isa_bound.py`).

---

## 1. Problem / why

Docker Desktop is the **one** load-bearing host dependency nOS installs **manually,
outside Homebrew and outside any pin**:

- `default.config.yml:585-588` — the `homebrew_cask_apps` list explicitly **omits**
  Docker: *"Docker Desktop: installed manually, managed by external-storage.yml … Do
  not manage via brew cask."* So Homebrew never sees it, never tracks its version,
  never upgrades it.
- `tasks/iiab/docker-prereqs.yml` — the only runtime contact point. It locates the
  `docker` binary (symlinking from `/Applications/Docker.app/Contents/Resources/bin/`
  after an external-SSD move), runs `open -a Docker`, then waits up to 90 s for
  `docker info` to return `rc == 0`, and finally records `nos_docker_ready`.

**The probe asserts the daemon *responds* — never that the installed Docker Desktop
build is one that can actually run on the host's macOS (Darwin) major version.** There
is no minimum-version floor and no Darwin↔Docker-Desktop compatibility check anywhere
in the repo. Today (live host: macOS 26.3.1 / Darwin 25.3.0, Docker Desktop 4.72.0,
Engine 29.4.2) it works because the operator keeps Docker current. The gap bites on
the **next macOS major bump — Darwin 27 / macOS 27** — the forward-looking scenario
this item names:

1. Operator upgrades the host to macOS 27.
2. The pre-existing, unpinned Docker Desktop (e.g. a 4.3x build from before the bump)
   is **too old for the new kernel/Virtualization.framework ABI** — Docker's own
   support matrix drops the previous Docker Desktop line on each new macOS major. The
   Linux VM (`com.docker.virtualization`) fails to launch.
3. `open -a Docker` "succeeds" (the GUI app opens), but `docker info` never returns
   `rc == 0`. nOS spins the **full 90 s wait** (`docker-prereqs.yml:106-119`), then
   drops to the **generic** *"Docker daemon is not responding even after 90 s … Start
   Docker Desktop manually and press ENTER"* pause (`:121-138`).
4. That pause is **wrong and dead-ends an unsupervised run**: the operator is told to
   "start Docker manually" when the real fix is "**upgrade Docker Desktop** — your
   build predates macOS 27 support." On an overnight/agent run there is no human to
   press ENTER, so the playbook hangs at the pause forever, or (in CI/`--check`) skips
   and silently records `nos_docker_ready: false`, disabling the **entire** compose
   layer with no actionable diagnostic.

This is a **diagnosis-quality** defect, not a runtime regression: nothing is broken
on a current host, but the day a macOS major lands, nOS gives the operator a slow,
misleading, unsupervised-hostile failure instead of a fast, correct one. The
`homebrew_prefix` doctrine note (`CLAUDE.md:334`) already declares Intel out of scope
"post-macOS 27" — macOS 27 is an explicitly-anticipated boundary in the codebase, and
the Docker dependency has no guard for crossing it.

**Why a floor and not "just keep Docker current":** Docker Desktop is unpinned *by
design* (it self-updates via its own updater, and a brew-cask pin fought that updater
— hence the manual-install note). We do **not** want to start *managing/forcing* a
Docker Desktop version (that re-introduces the updater conflict the manual-install note
avoided, and would be a live mutation this run forbids). We want a **read-only
preflight assertion**: *if* the installed Docker Desktop is below the floor known to
support the running Darwin major, fail **loud and early with the right instruction**
("upgrade Docker Desktop to ≥ X"), before the 90 s wait and before the misleading
"start it manually" pause.

---

## 2. Scope (explicit)

**In scope (repo edits only — live system stays READ-ONLY):**
- Add a `docker_desktop_min_version` floor var (+ optional per-Darwin-major override
  map) to `default.config.yml`, with a real default and stock-Jinja-only filters.
- Add a **read-only** preflight check in `tasks/iiab/docker-prereqs.yml`: read the
  installed Docker Desktop version (from `Docker.app`'s `Info.plist` /
  `docker version`), compare against the floor for the host's Darwin major, and **fail
  with an upgrade-Docker message** *before* the 90 s daemon wait when below floor.
- Make the existing generic daemon-not-responding pause **version-aware**: when the
  installed build is below floor, the message says "upgrade Docker Desktop to ≥ X for
  macOS {major}", not "start it manually."
- Make the check **escape-hatchable** (`-e nos_skip_docker_version_check=true`) and
  **default-inert on non-Darwin / Docker-less hosts** (CI macOS runners, Linux) — same
  gating idiom as the at-rest preflight and the `_docker_desktop_app.stat.exists` gate
  already in the file.
- One anatomy pytest gate that pins the floor var, the stock-Jinja-safety of it, the
  preflight task's presence + gating, and the version-comparison logic.

**Out of scope (do NOT do tonight — separate items / forbidden this run):**
- **Installing or upgrading Docker Desktop** (live mutation — forbidden; and would
  re-fight the self-updater the manual-install note deliberately sidesteps). The check
  *diagnoses and instructs*; it never mutates the host.
- **Managing Docker Desktop via brew cask / a pinned cask** — explicitly rejected by
  the `default.config.yml:587` note; out of scope.
- Adding the symmetric **Linux** Docker-CE version floor (`pazny.linux.docker`) — a
  separate platform; this item is Darwin-scoped (the item name says `darwin27`). The
  var/gate is written so a Linux floor can be added later without rework.
- A **live network** "is there a newer Docker Desktop" freshness probe — overnight run
  is offline; that is an `upgrade-advisor`-class on-demand job.
- Touching `external-storage.yml`'s `Docker.app` move/symlink logic (correct as-is).

---

## 3. Approach (exact files + edits)

### 3.1 The floor var — `default.config.yml`

Add near the existing Docker host settings (around `default.config.yml:458`, the
`docker_bin` block — same "Docker Desktop host" neighbourhood):

```yaml
# Docker Desktop is installed + self-updated manually (NOT via brew cask — see
# homebrew_cask_apps). It carries no Homebrew pin, so nOS asserts a minimum
# version at preflight: a build older than the floor for the running macOS
# (Darwin) major cannot launch the Linux VM and dead-ends the compose layer
# with a misleading "start it manually" prompt. The floor is the lowest Docker
# Desktop release that supports the host's macOS major; below it the preflight
# fails loud with an "upgrade Docker Desktop" message instead of a 90 s hang.
# Override per macOS major via docker_desktop_min_version_by_darwin (keys are
# the Darwin major: 25 = macOS 26, 27 = macOS 27). The bare floor is the
# fallback when the host's Darwin major isn't in the map.
docker_desktop_min_version: "4.30.0"          # conservative global floor
docker_desktop_min_version_by_darwin:
  "27": "4.55.0"                              # macOS 27 floor — REVIEW the real value
# Escape hatch for an operator who has out-of-band-verified compatibility:
nos_skip_docker_version_check: false
```

> **Floor values are placeholders to confirm in review** — the *mechanism* is the
> deliverable, not a hard-coded "Docker 4.55 supports macOS 27" claim (that needs the
> real Docker support matrix, which is a network lookup out of scope tonight). The gate
> (§4) asserts the **var shape, the comparison logic, and the fail-message wording**,
> not a specific upstream number, so the floor can be tuned later without touching the
> gate. The conservative global `4.30.0` floor is safe today (live build is 4.72.0);
> the `"27"` override is the forward-looking knob this item is about.

**Stock-Jinja trap compliance:** both new vars use **only** stock filters where they
land in a `{{ vars }}`-eager namespace. The map lookup in the task (§3.2) uses
`docker_desktop_min_version_by_darwin[<major>] | default(docker_desktop_min_version)`
— `default` is a stock builtin; dict-subscript is core Jinja. Both keys carry a real
literal default (`4.30.0`, the map, `false`), so they cannot trip the
"undefined-before-core-up" variant of the trap. No `regex_*`, `| bool` on a
config-namespace value, `b64encode`, or `hash` anywhere. Pinned by the new gate +
the standing `test_config_stock_jinja_only.py`.

### 3.2 The preflight check — `tasks/iiab/docker-prereqs.yml`

Insert a new block **between** "§1 Docker binary" and "§2 Start Docker daemon"
(i.e. after the binary is located/symlinked at line ~73, before `open -a Docker` at
line ~97), so the version verdict is known **before** the 90 s wait. All tasks
`changed_when: false`, `failed_when: false` on the probes, `check_mode: false`, and
gated on Darwin + Docker.app-present + not-skipped — byte-identical-inert on Linux/CI:

1. **Read installed Docker Desktop version (read-only).** Prefer the app bundle so it
   works even when the daemon is down (the exact failure case):
   ```yaml
   - name: "[Docker] Read installed Docker Desktop version"
     ansible.builtin.command: >-
       defaults read /Applications/Docker.app/Contents/Info.plist
       CFBundleShortVersionString
     register: _docker_desktop_ver
     changed_when: false
     failed_when: false
     check_mode: false
     when:
       - ansible_os_family == 'Darwin'
       - _docker_desktop_app.stat.exists | default(false)   # reuse the existing stat
       - not (nos_skip_docker_version_check | default(false) | bool)
   ```
   (Reuse/relocate the existing `_docker_desktop_app` stat — it is currently in §2 at
   line ~91; hoist it above this block so both consumers see it. Fallback to
   `{{ docker_bin }} version --format '{{.Server.Version}}'` is **not** used here —
   that needs a live daemon, which is exactly what's broken; the `Info.plist` read is
   daemon-independent.)

2. **Resolve the floor for this Darwin major + compare.** `ansible_facts['distribution_version']`
   is the macOS product version; the Darwin major comes from
   `ansible_facts['kernel'].split('.')[0]` (e.g. `25` today, `27` on macOS 27). Use
   `set_fact` with a stock `version` test:
   ```yaml
   - name: "[Docker] Resolve Docker Desktop version floor verdict"
     ansible.builtin.set_fact:
       _docker_desktop_floor: >-
         {{ docker_desktop_min_version_by_darwin[ansible_facts['kernel'].split('.')[0]]
            | default(docker_desktop_min_version) }}
       _docker_desktop_below_floor: >-
         {{ (_docker_desktop_ver.stdout | default('') | trim) is version(
              docker_desktop_min_version_by_darwin[ansible_facts['kernel'].split('.')[0]]
              | default(docker_desktop_min_version), '<') }}
     when:
       - ansible_os_family == 'Darwin'
       - _docker_desktop_app.stat.exists | default(false)
       - not (nos_skip_docker_version_check | default(false) | bool)
       - (_docker_desktop_ver.stdout | default('') | trim) | length > 0
   ```
   (`is version(..., '<')` is the stock Ansible `version` test — allowed; this task is
   **not** in the `{{ vars }}` loader namespace, so even if it weren't stock it's safe
   here, but `version` is stock regardless.)

3. **Fail loud + early when below floor.** This *replaces* the slow-hang path with a
   fast, correct diagnosis:
   ```yaml
   - name: "[Docker] Refuse a run on an under-floor Docker Desktop"
     ansible.builtin.fail:
       msg: |
         Docker Desktop {{ _docker_desktop_ver.stdout | default('?') | trim }} is below
         the minimum {{ _docker_desktop_floor }} required for macOS
         {{ ansible_facts['distribution_version'] | default('?') }}
         (Darwin {{ ansible_facts['kernel'].split('.')[0] }}).

         An under-floor Docker Desktop cannot launch the Linux VM on this macOS
         major — the daemon will never come up and the compose layer can't run.

         Fix:  open Docker Desktop -> check for updates, or
               download the latest from https://docs.docker.com/desktop/release-notes/
         Then re-run the playbook.

         Override (only if you have verified compatibility out-of-band):
               ansible-playbook main.yml -e nos_skip_docker_version_check=true
     when:
       - ansible_os_family == 'Darwin'
       - not (nos_skip_docker_version_check | default(false) | bool)
       - _docker_desktop_below_floor | default(false) | bool
   ```

### 3.3 Make the existing daemon-not-responding pause version-aware

`docker-prereqs.yml:121-138` (the generic *"Docker daemon is not responding … Start
Docker Desktop manually"* pause). The §3.2 fail already short-circuits the under-floor
case before this pause is reached, so this is a **belt-and-suspenders** wording fix for
the at-or-above-floor-but-still-down case: append one line to the prompt —

```
If you just upgraded macOS, confirm Docker Desktop also supports this macOS
major (Docker -> Check for Updates); an older build can't start the VM.
```

This keeps the misleading-instruction risk closed even if the version read failed
(e.g. a non-standard `Info.plist`), without changing the pause's existing gating.

### 3.4 No live mutation, no install

Nothing here installs, upgrades, or starts anything new. The two probes are
`defaults read` and a `set_fact` (read-only); the only behaviour change is **failing
earlier with a better message**. The escape hatch + Darwin/Docker.app gating keep CI
(no Docker.app) and Linux byte-identical-inert.

---

## 4. The gate (NON-NEGOTIABLE — every fix ships a gate)

New file: **`tests/anatomy/test_docker_desktop_version_floor.py`** — offline, fast,
ROOT-relative paths, modelled on `test_homebrew_prefix_isa_bound.py` (config-var
extraction + doctrine-sync) and the YAML-task introspection used by other
`tests/anatomy/` task gates. No network, no live system, no Docker required.

Tests:

1. `test_floor_vars_defined_with_real_defaults` — `default.config.yml` defines
   `docker_desktop_min_version` (a real `x.y.z` literal), `docker_desktop_min_version_by_darwin`
   (a mapping with a `"27"` key), and `nos_skip_docker_version_check: false`. Pins that
   the floor exists and the macOS-27 knob is present.
2. `test_floor_vars_are_stock_jinja_safe` — none of the three new vars' values contain
   a non-stock filter (`regex_`, `| bool` on the config value, `b64encode`, `hash`,
   `regex_replace/search`) — re-asserts the stock-Jinja rule at the var level
   (belt-and-suspenders with `test_config_stock_jinja_only.py`).
3. `test_prereqs_reads_docker_desktop_version` — parse `tasks/iiab/docker-prereqs.yml`
   as YAML; assert a task reads `CFBundleShortVersionString` from
   `Docker.app/Contents/Info.plist` (the daemon-independent version source) and is
   gated on `ansible_os_family == 'Darwin'` + `_docker_desktop_app.stat.exists` +
   `not (nos_skip_docker_version_check ...)`.
4. `test_prereqs_fails_before_daemon_wait_when_below_floor` — assert the `fail:` task
   keying on `_docker_desktop_below_floor` appears **before** the "Wait for Docker
   daemon to be ready" task in the file's task order (index comparison), so the fast
   diagnosis precedes the 90 s hang.
5. `test_below_floor_fail_message_says_upgrade_not_start` — the under-floor `fail:`
   `msg` contains "upgrade"/"Check for Updates"/release-notes guidance and the
   `nos_skip_docker_version_check` override, and does **not** tell the operator to
   merely "start Docker Desktop manually" (the misleading instruction).
6. `test_version_compare_uses_stock_version_test` — the comparison uses the stock
   Ansible `is version(..., '<')` test (not a hand-rolled string compare that would
   mis-order e.g. `4.9.0` vs `4.30.0`).
7. `test_escape_hatch_gates_every_new_task` — every task added by this item carries the
   `not (nos_skip_docker_version_check | default(false) | bool)` guard (so the override
   genuinely disables the whole check) **and** the Darwin gate (so CI/Linux stay inert).
8. `test_doctrine_note_in_sync` — a CLAUDE.md "Operator gotchas" / "Apple Silicon
   Constraints" line documents the floor + the macOS-major boundary, kept in sync with
   the var name (same doctrine-sync idiom as the ISA-bound gate's CLAUDE.md assertion).

Each test gets a surgeon-tone docstring naming the symptom it pins (the slow misleading
hang on a macOS-major bump with an under-floor Docker Desktop).

**Why a gate, not just the fix:** doctrine — "If you cannot gate it, it is a PLAN not a
fix." The failure mode is invisible on a current host (it only manifests after a future
macOS major), so without a gate the guard could silently rot (someone deletes the floor
var, or the fail message regresses to the misleading wording) and nobody notices until
macOS 27 ships. The gate pins the mechanism so it survives to when it's needed.

---

## 5. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Floor value wrong** → false-positive fail on a build that actually works (too-high floor blocks a good host) | medium | The global floor (`4.30.0`) is far below the live build (4.72.0) so today it never fires. The forward `"27"` override is flagged "REVIEW the real value" and the **escape hatch** (`-e nos_skip_docker_version_check=true`) is documented in the fail message itself — an operator is never hard-locked. The gate pins the *mechanism*, not the number, so tuning the floor later is a one-line edit with no gate churn. |
| `Info.plist` read fails on a future Docker.app layout → `_docker_desktop_ver.stdout` empty → comparison skipped | low | The `set_fact`/`fail` tasks are gated on `(_docker_desktop_ver.stdout | trim) | length > 0`; an empty read → check self-skips → falls through to the existing 90 s wait + the §3.3-improved pause. Degrades to today's behaviour, never to a crash. |
| `is version()` test unavailable in some ansible-core | very low | `version` is a long-stable stock test present in 2.20.5 and 2.21 (the frozen CI floor). Gate #6 pins its use; syntax-check + the local CI freeze catch a regression. |
| Stock-Jinja vars trap | N/A → pinned | New vars use only stock filters + real defaults; gate #2 + `test_config_stock_jinja_only.py` enforce it. The task-side `is version` test is not in the `{{ vars }}` loader namespace (it's a stack-layer task, not a `default.config.yml` value). |
| Darwin major from `ansible_facts['kernel']` mis-parsed (e.g. `kernel` fact shape differs) | low | `.split('.')[0]` on the Darwin kernel release (`25.3.0` → `25`) is the documented shape; if the key is absent, the map lookup `| default(docker_desktop_min_version)` falls back to the global floor — no crash, just the conservative floor. Could alternatively key off `ansible_facts['distribution_major_version']` — pick in review (gate accepts either as long as a per-major override path exists). |
| Check annoys operators on every run | none | `changed_when: false` everywhere; on an at-or-above-floor host the probe is a silent no-op read + a `false` verdict. No prompt, no change, no log noise beyond a registered fact. |
| New `fail` blocks an *unattended* run that *should* proceed | by design / mitigated | A below-floor Docker genuinely cannot run the stacks, so failing is correct — but the message gives the exact fix + the `-e` override so an automated rerun can proceed once Docker is upgraded (or the operator opts out). This is strictly better than the current silent 90 s hang → forever-blocking pause. |

---

## 6. Deferred (explicitly NOT this item)

- **Linux Docker-CE version floor** (`pazny.linux.docker`) — symmetric guard for the
  apt-installed engine; separate platform. The var/gate is shaped so it slots in later.
- **Live "is a newer Docker Desktop available" freshness probe** — needs network;
  `upgrade-advisor` on-demand territory, not an offline overnight edit.
- **Auto-installing / auto-upgrading Docker Desktop** — live mutation, and re-fights the
  self-updater the manual-install note avoids. Permanently a "diagnose + instruct", not
  "do", boundary for this dependency.
- **Deriving the per-Darwin floor from Docker's published support matrix** at run time —
  architectural (a data file + refresh job); the static override map is the overnight-safe
  version.

---

## 7. Verification recipe

All offline, no live mutation, no network — safe for an unsupervised run:

```bash
cd /Users/pazny/projects/nOS

# 1. The new gate — run BEFORE the edits to confirm it RED-flags the missing
#    floor/preflight, then AFTER to confirm GREEN.
python3 -m pytest tests/anatomy/test_docker_desktop_version_floor.py -v

# 2. Stock-Jinja safety + the ISA-bound sibling stay green (shared patterns).
python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py \
                  tests/anatomy/test_homebrew_prefix_isa_bound.py -q

# 3. Full anatomy suite stays green (no regression).
python3 -m pytest tests/anatomy/ -q

# 4. Playbook syntax-check clean (the new docker-prereqs tasks must parse).
ansible-playbook main.yml --syntax-check

# 5. The new vars exist with real defaults + the macOS-27 override.
grep -nE "docker_desktop_min_version|nos_skip_docker_version_check" default.config.yml

# 6. The preflight reads the bundle version + fails before the 90 s wait.
grep -n "CFBundleShortVersionString\|below_floor\|Wait for Docker daemon" \
     tasks/iiab/docker-prereqs.yml
#   → the below_floor fail line number must be < the "Wait for Docker daemon" line.

# 7. (Read-only host sanity — proves the probe's data sources exist; NO mutation.)
sw_vers ; uname -r
defaults read /Applications/Docker.app/Contents/Info.plist CFBundleShortVersionString
#   → on the live host: macOS 26.x / Darwin 25.x / Docker Desktop 4.72.0 → far above
#     the 4.30.0 global floor and no "27" Darwin match → check is a silent no-op.
```

Expected: gate #1 RED before §3 edits (proves it catches the missing guard), GREEN
after; #2–#4 GREEN throughout; #5/#6 show the floor var + the fail-before-wait ordering;
#7 confirms the live host is above floor (check stays inert today).

---

## 8. Commit shape (when implemented — separate from this plan commit)

```
feat(docker): preflight Docker Desktop version floor on Darwin

- Docker Desktop is unpinned (manual install, no cask) — an under-floor
  build on a new macOS major can't start the VM, dead-ending the compose
  layer behind a 90 s hang + misleading "start it manually" pause.
- read CFBundleShortVersionString, compare to a per-Darwin-major floor,
  fail loud with an "upgrade Docker Desktop" message BEFORE the daemon wait.
- escape hatch nos_skip_docker_version_check; Darwin/Docker.app-gated so
  CI + Linux stay byte-identical-inert.
- gate: test_docker_desktop_version_floor pins floor var + ordering + msg.
```

(Conventional Commits, subject ≤50 chars, surgeon-tone body ≤6 bullets, no
Co-Authored-By, no `--author`, branch-only — never pushed.)
