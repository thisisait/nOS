# Active work — what to do right now

> **Always-current pointer for the next session.** Read this BEFORE
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md) — that file is the
> long-form plan, this one is just the next-step finger-pointer.
>
> Last updated: 2026-05-01 • commit: post Track J landing • by: pazny+claude

---

## Current track: **H — ansible-core 2.24 upgrade**

[Section in roadmap →](roadmap-2026q2.md#track-h--ansible-core--224-upgrade-after-j-per-o16-was-d12)

## Current sub-step: **Phase 1 — collection version bumps + meta/main.yml min_ansible_version**

Track J Phase 4 (commit `85b933b`) landed the `ansible_env → ansible_facts['env']`
modernization (9 occurrences, not 200-400 as the original roadmap feared) — Track H
shrinks to ~1 day of mechanical work.

### What's done already (going into H)

- Track E (Tier-2 wet test) code-complete + wet-tested green 2026-04-30
  (3 recovery commits `8091c07..d4e99f2` + sign-off pending operator's
  manual checklist walk)
- Track J (tech-debt cleanup) DONE 2026-05-01 in 6 commits `0a6a960..f321b6e`
  + roadmap refresh: gate clarity, mailpit dual-attach, authentik post.yml
  rename, ansible_env modernization, pytest collection cleanup
- `ansible_env` count post-J: **0** (was 9). One Track H phase pre-paid.
- Pytest collection: 431 tests, 0 errors (was 8 + 4 errors pre-J)
- 89 apps tests still passing across all 6 J commits

### How to enter the work

1. Survey `requirements.yml` against ansible-galaxy for current 2.24-compatible
   versions of `community.general`, `community.docker`, `community.crypto`,
   `ansible.posix`. Bump versions; commit as `chore(deps): bump ansible
   collections for 2.24 compat`.
2. `find roles/ -name 'meta/main.yml' | xargs grep -l 'min_ansible_version'`
   — bump `"2.16"` → `"2.24"` everywhere. ~50 files; one commit
   `chore(meta): min_ansible_version 2.16 → 2.24`.
3. Audit custom modules (`library/nos_*.py`, `module_utils/nos_*.py`,
   `callback_plugins/wing_telemetry.py`) against 2.24 API:
   - `AnsibleModule` instantiation: still uses positional `argument_spec` (stable)
   - `module_utils.*` lazy-resolve: 2.24 may flag previously-permissive imports
   - Run `pip install ansible-core==2.24` in a sandbox venv, do
     `ansible-playbook main.yml --syntax-check` — catches most issues
4. Re-baseline `ansible-lint` — some 2.24 rules tighten (`schema[meta]`,
   `loop-var-prefix`).
5. CI matrix bump: `.github/workflows/ci.yml` — `ansible-core` pin to
   `>=2.24,<2.25`.
6. Strip `ansible_env needs migration` from `CLAUDE.md` "Known Tech Debt"
   section — that's now historic.
7. Operator runs blank with new ansible-core: `ansible-playbook main.yml -K -e blank=true`.
   Expected: same `ok=N changed=M failed=0` as pre-H, smoke 36+/36+.

### Where to look for diagnostics if something fails

| Symptom | Where to look |
|---|---|
| Collection install fails | `ansible-galaxy collection list` — verify pins |
| `module_utils` ImportError | Check 2.24 lazy-resolve note + module's relative imports |
| `lint` regression | `ansible-lint --offline -p main.yml` — note new rule violations |
| Custom module fail | Run `python -c 'from library import nos_apps_render'` — surface deprecations |
| Blank rc != 0 | Same triage as Track E: `~/.nos/ansible.log` for the failed task |

---

## Tracks coming next (do not start until H is DONE)

- **F — Dynamic instance_tld + per-host alias** ([roadmap section](roadmap-2026q2.md#track-f--dynamic-instance_tld--per-host-alias-after-e-d10))
  — 108 occurrences of `instance_tld`; `apps_subdomain` token already wired
  in 4 places (parser + render module + role) so the precedent exists. ~1-2 days.
- **G — Cloudflare proxy + LE production exposure (bsky / SMTP / maybe Mastodon)** ([roadmap section](roadmap-2026q2.md#track-g--cloudflare-proxy--le-production-exposure-after-f-d11))
  — Stalwart SMTP role new; Bluesky exposure flag flip; Mastodon optional. ~4-5 days.

Tracks A–D + E + J are DONE. If you find yourself there, stop and re-read this file.

---

## Quick state-of-the-world snapshot

| Surface | State |
|---|---|
| `git status` | clean (or pending commits — check before any write) |
| Last blank result | `ok=845 changed=261 failed=0 skipped=369` (PID 28378, 2026-04-29 23:27) |
| Last partial recovery | `ok=130 changed=10 failed=0 skipped=36` (PID 40835, 2026-04-30 13:59) — Tier-2 stack 4/4 healthy, post-hooks all fired |
| Apps stack | 4 healthy containers (twofauth, roundcube, documenso, documenso-db); Authentik proxy providers live; smoke runtime catalog populated |
| Tier-1 services | all healthy except transient Superset DNS hiccup (mDNS — re-probes green) |
| Tests | 431 tests collected, 0 collection errors. 89 apps + 25 schema + 25 importer + 4 pilot manifests + 71 PHP pass. 12 tests skipped (optional deps not installed). |
| Pilots live | `apps/twofauth.yml`, `apps/roundcube.yml`, `apps/documenso.yml` (all 3 wet-tested). `apps/plane.yml.draft` deferred. |
| Decision log | O1-O16 in roadmap-2026q2.md |

---

## How to update this file

This file rots in days, not weeks. After every meaningful work session:

1. Update **Current track / sub-step** if you advanced
2. Update the snapshot table at the bottom (last blank/partial result, anything that flipped state)
3. If a track-level decision was made (e.g. "documenso DB moved from embedded to shared infra-postgres"), log it in the **Decision log** in `roadmap-2026q2.md` — that file is the long-form record
4. Commit `docs(roadmap): refresh active-work pointer`

If you finish a track entirely:
- Mark the track DONE in `roadmap-2026q2.md`
- Flip "Current track" here to the next one
- Reset "Current sub-step" to the next track's first sub-step
- Update the "Where to look for diagnostics" table to match the new track's surfaces
