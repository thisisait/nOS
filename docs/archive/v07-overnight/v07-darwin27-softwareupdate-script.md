# v0.7 — Darwin 27 `softwareupdate` host-update script

Status: PLAN (not implemented). Target branch: `feat/v0.7-overnight`.
Owner: overnight agent batch. Scope: repo edits only, no live mutation.

## Problem / why

nOS pins **every layer it controls** — service image tags (`*_version` in
`default.config.yml`), the Ansible toolchain (`tools/ci-freeze.env` +
`requirements.lock.yml`), language runtimes (Homebrew formulae), even the
mkcert CA. The **one layer it does not touch is the host macOS itself.** The
Mac that runs the whole AIT stack is also the most security-load-bearing
component — it holds FileVault keys, the Authentik session cookie domain, the
launchd daemons (Wing/Bone/Pulse), and the Docker VM — yet OS security updates
are left to whatever the operator remembers to click in System Settings, on an
unattended machine that runs overnight.

Three concrete gaps this opens:

1. **No deterministic OS-patch posture.** The CLAUDE.md security backlog
   tracks ~14 pending service CVEs through `remediation-queue.json`, but a
   macOS RSR (Rapid Security Response) or a WebKit/kernel CVE on the *host* has
   no nOS-visible state. The host is a CVE blind spot in an otherwise
   pin-everything posture.
2. **Darwin 27 is the forcing function.** macOS 27 (next major, Darwin
   kernel 27.x) lands a new `softwareupdate(8)` surface and changes the RSR /
   deferral knobs. nOS already reads `ansible_facts['distribution_version']`
   in `tasks/export-state.yml` (L149) and the Homebrew bottle path assumes
   `arm64_sequoia` (default.config.yml L570) — both go stale silently when the
   host jumps to 27. There is nowhere in the repo that *records* the host
   Darwin version, asserts a floor, or surfaces "your OS has N pending security
   updates" into Wing / the final summary.
3. **Unattended box = the worst place to be surprised by a forced reboot.**
   A macOS auto-install that reboots at 02:00 takes down all ~50 services and
   every launchd daemon with zero nOS awareness. Operators want the *opposite*
   of Apple's default: **report and stage security updates, never auto-reboot**,
   and let the operator (or a future supervised Pulse job) choose the window.

### The script, not auto-apply (doctrine alignment)

Per the destructive-op safety model (memory `feedback-destructive-op-safety`)
and machinery doctrine: this ships a **dry-run-by-default reporting script**
plus a **non-mutating preflight probe**, NOT an auto-installer. Installing an
OS update / rebooting is a destructive, not-trivially-reversible host mutation —
exactly the class the overnight rules forbid. The script's *default* mode is
`softwareupdate --list` (read-only); applying is an explicit, operator-gated,
off-by-default path that the unattended playbook run never takes.

## Approach

Mirror the proven **`pazny.backup` host-script + dual-scheduler** pattern (the
only existing "render a host script, schedule it, surface its state" precedent)
and the **`tasks/preflight-at-rest.yml`** default-OFF host-probe pattern. Two
cooperating pieces:

### A. A read-only host preflight probe (`tasks/preflight-os-update.yml`)

Runs early in `tasks:` (after `tasks/_platform.yml`, alongside the existing
`preflight-at-rest.yml`), macOS-only, **always read-only**:

1. `sw_vers -productVersion` + `uname -r` → record host version + Darwin
   kernel rev into facts (`nos_host_os_version`, `nos_host_darwin_major`).
2. `softwareupdate --list --no-scan` (fast, cache-only; `--no-scan` avoids a
   network round-trip on every run) → parse the count of pending updates and
   whether any are flagged `[recommended]` / security (RSR).
3. Optional **floor assertion**: if `require_macos_floor` (default `false`) is
   set and `nos_host_darwin_major < macos_darwin_floor`, **warn** (default) or
   **hard-fail** (gov profile) — same default-OFF shape as the at-rest gate.
   This is the Darwin-27-readiness seam: a gov tenant can pin "must be on
   Darwin ≥ 27".
4. Emit the pending-update count into the run summary + (when Bone is up) a
   Wing/A9 notification at `on_info` severity. **No install. No reboot.**

Every task gated `ansible_os_family == 'Darwin'` so Linux is byte-inert (the
playbook's Linux wet-test never executes a line of it), and the whole file is
gated on `manage_os_updates | default(true)` so an operator can disable the
probe entirely.

### B. The host update script (`pazny.os_update` role → `~/.nos/os-update.sh`)

A thin role following the backup-role shape exactly:

- `roles/pazny.os_update/tasks/main.yml` renders
  `templates/os-update.sh.j2` → `~/.nos/os-update.sh` (mode `0700`), and
  installs an **opt-in, default-OFF** launchd LaunchAgent
  (macOS) / `systemd --user` timer (Linux no-op stub) that runs the script in
  **report-only** mode on a cadence (default weekly, Sun 09:00 — daytime, never
  overnight, so a human is present if anything surfaces).
- The script itself (`os-update.sh.j2`):
  - **`report` (default)** — `softwareupdate --list`, write a structured
    summary to `~/.nos/os-update-status.json` (mirrors `backup-status.json`),
    POST an A9 notification via Bone (`on_info`, or `on_high` if a security
    update is pending). Read-only. This is what the launchd agent runs.
  - **`stage`** — `softwareupdate --download --recommended` (downloads only,
    does **not** install or reboot). Still non-destructive (just fills the
    update cache); gated behind an explicit `--stage` arg the agent never
    passes.
  - **`apply`** — `softwareupdate --install --recommended --no-restart`
    (installs, suppresses the auto-reboot). **Operator-only**, requires
    `--apply --i-understand-this-reboots` double-confirm, refuses unless run
    on a TTY (`[ -t 0 ]`) so no scheduled/automated path can ever trip it.
    Mirrors the `blank=true` / coexistence-cutover "double-gate a destructive
    op" doctrine.
  - A textfile-collector metric (`os_update.prom` → Alloy, same dir as
    `backup.prom`: `node_exporter_textfile_dir`) exposing
    `nos_macos_pending_updates` + `nos_macos_pending_security_updates` +
    `nos_host_darwin_major` so Grafana/Prometheus can alert on a stale host —
    closing the "host CVE blind spot" with the same observability vein backups
    already use.

- The role is wired via `import_role` in `main.yml` next to `pazny.backup`
  (it's a non-Docker host role), gated `install_os_update | default(true)` +
  `ansible_os_family == 'Darwin'` for the launchd path, with the script render
  itself platform-portable (Linux renders a `report`-only stub that shells
  `apt list --upgradable` / no-op — keeps the dual-platform contract without
  pretending to manage Linux kernel updates this round).

### Why a script *and* a preflight task (not one or the other)

- The **preflight probe (A)** runs on **every** playbook converge and is what
  surfaces "host has 3 pending security updates" into the run the operator is
  already watching — zero new scheduling, immediate visibility, the Darwin-27
  floor seam.
- The **script + agent (B)** is what keeps the posture *between* converges (a
  box that isn't re-run for weeks still reports weekly) and is the
  operator-driven `stage`/`apply` entry point. Same split as backup:
  `backup.sh` (the doer) vs the launchd agent (the cadence) vs the exporter
  (the state).

## Files to touch

New:

- `tasks/preflight-os-update.yml` — read-only host probe (A). Modeled on
  `tasks/preflight-at-rest.yml` (default-OFF floor, Darwin-gated, no mutation).
- `roles/pazny.os_update/defaults/main.yml` — `install_os_update`,
  `manage_os_updates`, `os_update_schedule_*` (weekday/hour/minute),
  `os_update_script_path`, `os_update_status_file`, `os_update_launchd_label`,
  `macos_darwin_floor`, `require_macos_floor`, `os_update_exporter_enabled`.
- `roles/pazny.os_update/tasks/main.yml` — render script + status skeleton +
  dual-scheduler block (lifted structurally from `pazny.backup/tasks/main.yml`,
  incl. the `launchctl list` rc-probe idempotence idiom).
- `roles/pazny.os_update/templates/os-update.sh.j2` — the `report`/`stage`/
  `apply` script (Jinja-rendered host script; **no `${#arr[@]}`** per the
  brace-hash trap memory).
- `roles/pazny.os_update/templates/os-update-launchd.plist.j2` — report-only
  weekly agent (`StartCalendarInterval`).
- `roles/pazny.os_update/handlers/main.yml` — `Reload os-update launchd`.
- `roles/pazny.os_update/meta/main.yml` — role metadata stub.
- `tests/anatomy/test_os_update_report_only_default.py` — **the gate** (below).

Edited:

- `main.yml` — `import_tasks: tasks/preflight-os-update.yml` in `tasks:` next to
  the at-rest preflight (after `_platform.yml`); `import_role: pazny.os_update`
  next to the `pazny.backup` host-role wiring. Both with `tags:` so `--tags`
  reaches them.
- `default.config.yml` — `install_os_update: true`, `manage_os_updates: true`,
  `macos_darwin_floor: 24` (current Sequoia floor; Darwin 27 = macOS 27),
  `require_macos_floor: false`, schedule vars. **All stock-Jinja, real
  defaults, defined before core-up** (satisfies `test_config_stock_jinja_only.py`
  both variants).
- `profiles/gov-local.yml` — flip `require_macos_floor: true` (gov tenants must
  be on a supported OS) — opt-in, mirrors how the at-rest gate flips there.
- `docs/security-baseline.md` — a paragraph: host OS update posture is
  report-only by default; `apply` is TTY-gated double-confirm; floor pinnable;
  pending-update count exported to Prometheus + Wing.
- `docs/active-work.md` — one-line pointer.

## Gates it needs

New `tests/anatomy/test_os_update_report_only_default.py` — **offline,
source-level** (no playbook run, no `softwareupdate`, no Docker), parsing the
role template + task YAML the way `test_config_stock_jinja_only.py` and
`test_plugin_wiring_contract.py` do:

1. **`test_script_default_mode_is_report`** — parse `os-update.sh.j2`; the
   default branch (no `--apply`/`--stage` arg) MUST resolve to
   `softwareupdate --list` and MUST NOT contain `--install` / `--restart` /
   `shutdown`/`reboot` on the default path. This is the load-bearing pin:
   the unattended path can never install or reboot.
2. **`test_apply_path_is_tty_and_double_confirm_gated`** — the `apply` branch
   MUST be guarded by both a `[ -t 0 ]` TTY check AND an
   `--i-understand-this-reboots` (or equivalent) second flag, AND uses
   `--no-restart`. Regex-assert all three tokens co-occur in the apply branch.
3. **`test_launchd_agent_runs_report_only`** — the rendered
   `os-update-launchd.plist.j2` `ProgramArguments` MUST invoke the script with
   **no** `--apply`/`--stage` (the scheduled agent is report-only by
   construction).
4. **`test_default_config_flags_are_stock_and_off_safe`** — `default.config.yml`
   declares `install_os_update`, `manage_os_updates`, `macos_darwin_floor`,
   `require_macos_floor` as plain scalars (no non-stock filter); assert
   `require_macos_floor` defaults to `false` (probe warns, never hard-fails, on
   a normal run). Belt-and-suspenders alongside the existing stock-Jinja gate.
5. **`test_preflight_is_darwin_gated_and_nonmutating`** — every task in
   `tasks/preflight-os-update.yml` carries `ansible_os_family == 'Darwin'`
   (or is a Darwin-conditional fact) AND no task uses `--install`/`--download`
   (the preflight is `--list --no-scan` only). Pins the "Linux byte-inert +
   probe never mutates" contract.
6. **`test_no_brace_hash_in_rendered_script`** — assert `os-update.sh.j2`
   contains no `${#` (the Jinja comment-open `{#` trap from memory
   `jinja-rendered-shell-brace-hash-trap`); use `${arr[@]+...}`/`${!arr[@]}`.

The suite must stay green and `ansible-playbook main.yml --syntax-check` must
pass. The whole feature is default-report-only, so the **Linux integration
wet-test runs zero `softwareupdate` lines** (Darwin gate) and the macOS
integration wet-test runs only the read-only `--list --no-scan` probe (no
state change, no `changed=1` churn on the idempotence re-run — the status JSON
is written with `force: false` skeleton + content-stable update).

## Risks

- **`softwareupdate --list` is slow / network-bound on cold cache.** Mitigated
  by `--no-scan` in the preflight (cache-only, fast); the full scan happens only
  in the weekly agent (daytime, not on the converge critical path) and the
  manual `report` run. If `--no-scan` returns stale data, the weekly agent's
  full scan reconciles it.
- **Parsing `softwareupdate --list` output is fragile across macOS versions.**
  The Darwin-27 surface changes the list format — this is *the whole point*
  (the floor + version record catch it), but the parser must degrade gracefully
  (unknown format → `pending=unknown`, surface a warning, never crash the
  converge). The gate asserts the script never `set -e`-aborts the playbook on
  a parse miss (probe is `failed_when: false`, mirroring the at-rest probe).
- **Accidental destructive path.** The single biggest risk is the `apply`
  branch ever firing unattended. Defended by **three independent locks** (TTY
  check, double-confirm flag, `--no-restart`) AND gate #1/#2/#3 pinning all
  three — a regression that weakens any lock fails the suite. The launchd agent
  literally cannot pass the flags (gate #3).
- **Floor false-positive on a supported-but-old OS.** `require_macos_floor`
  defaults `false` → normal runs only *warn*. Hard-fail is gov-opt-in only,
  same risk profile as the at-rest gate (which operators already accept).
- **Idempotence churn.** Status JSON + `.prom` written every run. Mitigated by
  the backup-exporter precedent: write content-stable output (sorted keys,
  no timestamps in the gated-diff body) so a steady-state re-run is
  `changed=0`. The launchd `launchctl list` rc-probe idiom (copied from backup)
  keeps the agent-load idempotent.
- **Scope creep into "manage Linux kernel updates".** Explicitly out: the Linux
  path renders a report-only stub. Managing `apt`/`unattended-upgrades` is a
  separate plan; this one is Darwin-27-driven and macOS-first.

## Verification recipe

```bash
# 0. On the right branch
git switch feat/v0.7-overnight

# 1. The new gate + the stock-Jinja gate (offline, fast — no softwareupdate run)
python3 -m pytest tests/anatomy/test_os_update_report_only_default.py \
                  tests/anatomy/test_config_stock_jinja_only.py -q

# 2. Full anatomy suite stays green
python3 -m pytest tests/anatomy/ -q

# 3. Syntax-check clean (new task file + role render are valid YAML/Jinja)
ansible-playbook main.yml --syntax-check

# 4. Prove the default/scheduled path can never install or reboot
#    (should print nothing — no install/restart token on the default branch)
grep -nE 'softwareupdate.*(--install|--download)|--restart|reboot|shutdown' \
     roles/pazny.os_update/templates/os-update.sh.j2 \
  | grep -v -- '--no-restart' \
  | grep -vE '#|apply\)' || echo "OK: no destructive token outside the gated apply branch"

# 5. Confirm no Jinja brace-hash trap in the rendered script
grep -n '\${#' roles/pazny.os_update/templates/os-update.sh.j2 \
  && echo "FAIL: ${#...} = Jinja {# comment-open" || echo "OK: no brace-hash"

# 6. READ-ONLY live spot-check (no playbook mutation): run the preflight probe
#    tag against the live Mac — it only runs `sw_vers` + `softwareupdate --list
#    --no-scan`, no install:
ansible-playbook main.yml --tags os-update,preflight --skip-tags stacks --check
#    --check + the probe's failed_when:false means zero host change; eyeball the
#    reported pending-update count.

# 7. Frozen 1:1 pre-release probe (optional, before any eventual release push)
tools/ci-local.sh
```

Acceptance: gates #1–#6 green, full suite green, syntax-check clean; step-4
grep prints "OK" (no destructive token on the default/scheduled path); step-5
prints "OK"; the macOS idempotence re-run stays `changed=0` for the status
JSON + agent load.

## Follow-ups (NOT this plan)

- A **supervised Pulse job** (`os-update-report`) that runs the `report` script
  on the A8 conductor cadence and routes a pending-security-update count into
  the Wing inbox — once the scheduled-loop conductor lands (CLAUDE.md: still
  queued). Keep it report-only; `apply` stays operator-TTY-only forever.
- A Grafana panel on dashboard `91-backups` (or a new `92-host-health`) reading
  `nos_macos_pending_security_updates` so a stale host alerts like a stale
  backup does.
- Linux `unattended-upgrades` / kernel-livepatch posture as its own plan when
  the Linux port grows a host-hardening track.
- Wire `nos_host_darwin_major` into `tasks/export-state.yml` / the Art-30
  systems register so the host OS version is part of the audited state shape.
