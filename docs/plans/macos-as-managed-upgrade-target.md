# macOS as a managed upgrade target — design + build log

Status: BUILDING (operator-confirmed 2026-06-21). Increment 1 (continuation
scripts) shipped + validated; Increment 2 (launchd + playbook install) next. An
extension of the reset-scope / `host_reboot` machinery
([upgrade-reset-scope-and-session-safety.md](upgrade-reset-scope-and-session-safety.md)).

## Why

A macOS update is a `host_reboot`-class change nOS cannot survive: the install
happens in a sealed reboot environment Apple controls, so nOS (playbook, Wing,
Bone, Pulse) is **not running** during it. The manual "after a macOS update"
checklist (verify python/CLT, bring Docker up, reload daemons, re-converge) is
exactly the tribal knowledge the operator wants **codified and executed by the
machinery**, not run by hand. Goal: managed continuity across the reboot.

## Model — three phases around one reboot

```
PRE  (old OS, nOS alive)   →  REBOOT + install (Apple; nOS dead)  →  POST (new OS, first login)
  operator: `arm`             operator: triggers the macOS update     nOS: resume → settle, auto
  nOS: write continuation     nOS: nothing                            nOS: notify + clear plan
       plan (boot-id + OS ver)
```

**The operator's only manual act is triggering the OS update** (Apple requires a
human + reboot anyway). Everything else is automatic. The enabling primitive is a
launchd `RunAtLoad` login agent that, on every login, checks the armed plan and
acts **only** once the host has rebooted into a *different* OS version.

## Decision table (the safety property — never fire prematurely)

Armed boot-id (at PRE) vs the live boot-id + OS version:

| state | action |
| --- | --- |
| no plan armed | no-op |
| boot-id UNCHANGED | no-op (still PRE, or a plain re-login) |
| boot-id CHANGED, OS version SAME | re-arm against this boot, keep waiting (an *unrelated* reboot, not the update) |
| boot-id CHANGED, OS version DIFFERENT | **the update** → run settle, archive plan (one-shot), notify |

boot-id = `kern.boottime` boot epoch (the FIRST integer; a greedy `sec =` match
grabs usec). Same source as the upgrade-engine reboot-required marker.

## Increment 1 — continuation scripts (SHIPPED, validated 2026-06-21)

- `files/anatomy/scripts/nos-boot-id.sh` — stable per-boot id (macOS epoch / Linux boot_id).
- `tools/nos-os-update-arm.sh` — PRE: write `~/.nos/continuation-plan.json` (boot-id, OS version+build), print "safe to update now". Sudo-free; `rm` the plan to cancel.
- `files/anatomy/scripts/nos-os-resume.sh` — the login-agent executor (decision table above). `NOS_RESUME_DRY=1` previews without running settle. `NOS_DIR` override for tests.
- `files/anatomy/scripts/nos-os-settle.sh` — POST: SUDO-FREE health — bring Docker Desktop up + wait, verify python pin / CLT / daemons, report. Anything needing sudo/GUI (CLT after a major bump) is an `ATTENTION` line, not an attempt.
- Gate `tests/anatomy/test_os_resume_scripts.py` (8 checks: parse, epoch-not-usec, never-fire-prematurely, sudo-free settle, arm→resume PRE no-op). All 4 resume branches smoke-verified in a temp dir; settle validated on the live OS (SETTLE OK).

## Increment 2 — launchd login agent + playbook install (NEXT)

A macOS-only `eu.thisisait.nos.resume` LaunchAgent (`RunAtLoad`, one-shot per
login) pointing at `nos-os-resume.sh`, rendered + bootstrapped by the playbook so
the install is via the machinery, not by hand. FileVault note: a *user*
LaunchAgent runs at first **GUI login** (not pre-login) — which is fine, the
operator logs in to use the machine; a LaunchDaemon would run earlier but lacks
the user/Docker context.

## Increment 3 / 4 — later

- A9/Bone notification of the settle outcome (v0 uses a native `osascript`
  notification + a `~/.nos/os-resume-result.json` Wing can surface).
- First-class Wing surface + a `host_reboot` recipe `upgrades/macos.yml` so a
  macOS update is planned through `/upgrades` like any other upgrade target.

## Honest limits

- The install reboot is Apple's; nOS owns PRE + POST, not the install.
- Point update → effectively zero manual steps post-arm. MAJOR bump → CLT/Docker
  Desktop may need a one-time human/GUI nudge the first time; settle DETECTS +
  guides + the flow is resumable/audited rather than tribal.
- Trigger stays human (operator decision, 2026-06-21); nOS does not run
  `softwareupdate -i` (deferred opt-in).
