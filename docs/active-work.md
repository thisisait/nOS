# Active work — what to do right now

> **Always-current pointer for the next session.** Read this BEFORE
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md) — that file is the
> long-form plan, this one is just the next-step finger-pointer.
>
> Last updated: 2026-04-29 evening • commit on update: `f9e57c1` (+ this commit) • by: pazny+claude

---

## Current track: **E — Tier-2 apps_runner wet test**

[Section in roadmap →](roadmap-2026q2.md#track-e--tier-2-appsrunner-wet-test--d8d9)

## Current sub-step: **D8 — single-pilot end-to-end live**

The previous three blank-runs (2026-04-29) produced a healthy Tier-1
deploy (`ok=842 changed=262 failed=0`) but the Tier-2 `apps` stack
never came up to a state where post-hooks could fire. Code-side defence
is now exhausted (image pre-flight catches typos, post-hook gate stops
false `app.deployed` events). Track E's first job is a **wet test of
ONE pilot from blank to fully observable**, using
[`docs/tier2-wet-test-checklist.md`](tier2-wet-test-checklist.md) as
the operator runbook.

### What's in the way (none — ready to run)

- Image pre-flight commit `f9e57c1` is in master
- `apps/twofauth.yml` has the right image (`docker.io/2fauth/2fauth:6.1.3`)
- `apps/roundcube.yml` and `apps/documenso.yml` exist as Tier-2 manifests; for D8 we want to **temporarily demote them** so only `twofauth` deploys (renaming `.yml` → `.yml.draft` or prefixing `_`). Restore at start of D9.

### How to enter the work

1. **Operator step**: rename Roundcube + Documenso to skip-list:
   ```bash
   cd /Users/pazny/projects/nOS
   mv apps/roundcube.yml apps/roundcube.yml.draft
   mv apps/documenso.yml apps/documenso.yml.draft
   ```
2. Run a blank: `ansible-playbook main.yml -K -e blank=true`. Expected outcome:
   - `ok=N failed=0` (where N is around 800)
   - `docker compose -p apps ps` shows 1 container `twofauth (healthy)`
   - The 8 post-hooks all log "OK" / "1 app upserted" / "(unsigned fallback HTTP 200)" etc.
3. Walk through [`docs/tier2-wet-test-checklist.md`](tier2-wet-test-checklist.md) line by line.
4. Anything red on the checklist becomes a `fix(apps): ` commit.
5. When all checklist rows are green, restore Roundcube + Documenso (`mv .draft .yml`), re-run, repeat. That's D9.
6. Plane stays `.draft` for now — separate stress-test sprint after D9 is done.

### Where to look for diagnostics if something fails

| Symptom | Where to look |
|---|---|
| Apps stack 0 containers | `grep "Apps stack result" ~/.nos/ansible.log \| tail -1` — error message in the rc=1 path |
| Post-hook crashed | `grep "Apps Post" ~/.nos/ansible.log \| tail -30` — last task before fatal |
| Authentik provider missing | `https://auth.dev.local/if/admin/#/core/applications` — search for slug |
| Wing /hub missing entry | `sqlite3 ~/wing/wing.db "SELECT id, name FROM systems"` |
| GDPR row missing | `sqlite3 ~/wing/wing.db "SELECT id, legal_basis FROM gdpr_processing"` |
| Bone event missing | `tail -20 ~/.nos/events/playbook.jsonl \| grep app.deployed` |
| Smoke probe red | `python3 tools/nos-smoke.py --tier 2` |
| Browser 404 / cert error | `curl -kIL https://twofauth.apps.dev.local/` |

---

## Tracks coming next (don't start until E is DONE)

- **F — Dynamic instance_tld + per-host alias** ([roadmap section](roadmap-2026q2.md#track-f--dynamic-instance_tld--per-host-alias-after-e-d10))
- **G — Cloudflare proxy + public exposure (bsky / SMTP / maybe Mastodon)** ([roadmap section](roadmap-2026q2.md#track-g--cloudflare-proxy--le-production-exposure-after-f-d11))
- **H — ansible-core ≥ 2.24 upgrade** ([roadmap section](roadmap-2026q2.md#track-h--ansible-core--224-upgrade-after-g-d12))

Tracks A–D are DONE. If you find yourself there, stop and re-read this file.

---

## Quick state-of-the-world snapshot

| Surface | State |
|---|---|
| `git status` | clean (or pending commits — check before any write) |
| Last blank result | `ok=842 changed=262 failed=0 skipped=364` (PID 52853, 2026-04-29) |
| Apps stack | rc=1 last attempt (twofauth image typo) — fixed in `f9e57c1`, untested at time of writing |
| Tier-1 services | all healthy (12 infra + 10 obs + 21 iiab + …) |
| Tests | 386 Python passing (72 apps + 25 schema + 13 importer + 276 baseline), 71 PHP passing |
| Pilots | `apps/twofauth.yml` (live), `apps/roundcube.yml` (live but demote for D8), `apps/documenso.yml` (live but demote for D8), `apps/plane.yml.draft` (deliberate — 13 containers, separate sprint) |

---

## How to update this file

This file rots in days, not weeks. After every meaningful work session:

1. Update **Current track / sub-step** if you advanced
2. Update the snapshot table at the bottom (last blank result, anything that flipped state)
3. If a track-level decision was made (e.g. "documenso DB moved from embedded to shared infra-postgres"), log it in the **Decision log** in `roadmap-2026q2.md` — that file is the long-form record
4. Commit `docs(roadmap): refresh active-work pointer`

If you finish a track entirely:
- Mark the track DONE in `roadmap-2026q2.md`
- Flip "Current track" here to the next one
- Reset "Current sub-step" to the next track's first sub-step
- Update the "Where to look for diagnostics" table to match the new track's surfaces
