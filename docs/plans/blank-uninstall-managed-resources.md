# Blank / uninstall drift → manifest of managed resources

**Status:** OPEN epic (opened 2026-07-19). Pivot away from the nOS-face companion
work after an operator caught a blank-run drift. Related: [`fs-doctrine.md`](fs-doctrine.md)
(storage layout), [`keap-datatables-apps-systems.md`](keap-datatables-apps-systems.md).

## Symptom (operator-observed 2026-07-19)

After a `blank=true` run yesterday → today, state from BEFORE the blank survived:
- A screenshot from **2026-04-20** still visible in nOS-face Files, and mirrored
  in KEAP `/explore`.
- A **duplicate `face-controls`** DataTable in KEAP.

`blank=true` is documented as "clean reinstall — wipes Docker state, data dirs,
configs" but it does **not** actually wipe the user-file tree, and it is not
reconciliation, so orphans persist.

## Diagnosis (evidence, live)

### 1. User-file tree is never wiped
- `nos_data_root: ~/nos` (`default.config.yml:41`). Bone VFS filed class-3 at
  `~/nos/tenants/<slug>/users/<uid>/{documents,library,inbox,agents,…}`
  (`files/anatomy/bone/vfs.py:84`).
- The surviving file lives at
  `~/nos/tenants/pazny/users/fceffd43…/documents/screenshots/Screenshot 2026-04-20 ….png`.
- `tasks/blank-reset.yml` builds `_blank_dirs` as a **hand-maintained per-service
  allowlist** (`stacks_dir` + DB dirs + one `<svc>_data_dir` per enabled service).
  **`nos_data_root/tenants` is not in the list at all** → user files survive every
  blank. Downstream services (KEAP fs-sync, Nextcloud, …) then re-hydrate the old data.

### 2. Allowlist misses services
- `keap_data_dir: {{ nos_data_root }}/platform/services/keap/data` is defined
  (`default.config.yml:68`) but `tasks/blank-reset.yml` has **no `install_keap`
  entry** (`grep -c install_keap` → 0) → KEAP's data dir is not wiped either.
- Any service added without also editing the 150-line `_blank_dirs` set-fact is
  silently un-wiped. The allowlist is the wrong mechanism.

### 3. Not reconciliation → orphans persist
- The duplicate KEAP table is `face.controls` (dot) **and** `face-controls` (dash),
  both HTTP 200 on the per-slug bearer route. The dot slug is an **orphan** from the
  pre-v1.12.1 ad-hoc seed (slug convention changed dot→dash). The face seeder is
  **create-or-return**, so it never removed the renamed-away slug. A rename or a
  regex-fallback change duplicates instead of reconciling.

## KEAP agent's guidance (2026-07-19) — adopt

KEAP is a **pure downstream mirror**: `73 files → 73 objects, removed: 0`. What was
seen is not a KEAP bug — fs-sync faithfully mirrors the mount. Key principle:

**KEAP data has two layers with different semantics:**
- `/data` (libsql) = **derived** state — fully regenerable from FS + ingests.
  Uninstall may delete it freely; KEAP rebuilds it.
- `/user-files` (= `~/nos/tenants/<slug>/users`) = **source of truth**, an
  **nOS-managed mount**. nOS must clean this, not KEAP.

**Uninstall order:** FS cleanup first (nOS) → KEAP self-reconciles on next fs-sync
(prunes vanished). If nOS wipes only KEAP `/data` but not the FS, KEAP just
re-mirrors the same stale data. **FS source cleanup is the authority.**

**Verification hook offered:** KEAP exposes `/agent/v1/fs/status` + `/agent/v1/objects`
— nOS can use them as a post-uninstall check ("KEAP reports 0 objects → clean FS").

## Design — manifest of managed resources

The core fix is to stop hand-maintaining an allowlist and instead **record what nOS
created** and remove exactly that.

1. **Managed-resource manifest.** On install, nOS records everything it creates —
   data dirs, docker volumes, DB files, bind-mounts, `tenants/<slug>/…` trees,
   containers, LaunchAgents, nginx/dnsmasq/cert artifacts. Uninstall walks the
   manifest and removes only manifest entries. **Pre-existing paths (not in the
   manifest) stay untouched** — this automatically satisfies "preserve the mess that
   existed before nOS." (Likely home: extend `~/.nos/state.yml` / `pazny.state_manager`,
   which already tracks runtime state, rather than a new store.)

2. **User files ARE managed.** `~/nos/tenants/<slug>/users/**` must be in the
   manifest and removed on uninstall/blank. This is the specific gap that let the
   screenshot survive.

3. **Reconciliation, not create-or-return.** Seeders (face DataTables, and the
   pattern generally) declare a canonical set and **remove entries outside it**.
   Face-side: one explicit canonical slug per table (not name-derived, so the regex
   fallback can't mutate it) + delete `face-*` slugs not in the declared set. (Needs
   KEAP agent DELETE on the agent surface; until then, human `/api/tables/:id` DELETE.)

4. **`--blank` semantics, precisely.** Either retire `--blank`, or define it as
   **"reset DERIVED state, preserve SOURCE"** (the opposite of uninstall):
   - `blank` = wipe Docker + `/data` + derived dirs, KEEP `tenants/<slug>/users`
     (user source) → a clean-services reinstall that preserves user files.
   - `uninstall` = walk the manifest, remove **everything nOS created** incl. user
     files → true drop-in removal.
   The current blank is neither: it wipes some derived state but leaks user files AND
   misses services. The drift came from that ambiguity.

5. **Idempotence as an acceptance test** (stronger than "blank and hope):
   - `install → uninstall` leaves **nothing** from the manifest.
   - `install → uninstall → install` yields a **bit-identical** state to a clean
     install.
   - Post-uninstall: KEAP `/agent/v1/fs/status` reports 0 objects.

## Phased plan (proposed — needs operator scoping before build)

- **P0 tactical (unblocks today, low-risk):**
  - Add `nos_data_root/tenants` + `nos_data_root/platform/services` to the blank wipe
    scope **gated behind an explicit opt-in** (`wipe_user_files=true`), since deleting
    user source is destructive — dry-run/confirm per the destructive-op safety model.
  - Add the missing `install_keap` entry to `_blank_dirs` (mechanical).
  - Delete the orphan `face.controls` KEAP table (human DELETE; operator-confirmed).
  - Face seeder: pin one canonical explicit slug per `face-*` table.
- **P1 architectural:** the managed-resource manifest + reconciling uninstall +
  idempotence acceptance test + KEAP fs/status post-check.

## Open decisions for the operator
1. **Blank vs uninstall split** — keep `--blank` as "preserve source" and add a
   separate `uninstall`? Or one path with a `wipe_user_files` flag?
2. **Manifest home** — extend `state_manager`/`~/.nos/state.yml`, or a dedicated
   install manifest?
3. **Scope now** — ship P0 tactical first (stop the bleeding), then design P1? Or
   design the manifest first and do it once, properly?
