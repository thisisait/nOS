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

### 2b. KEAP mirrors the WHOLE tree; Files is uid-scoped (the visible symptom)
The operator saw the screenshot **in KEAP `/explore` but NOT in nOS-face Files**. That
is not "blank didn't delete" — it's a two-view inconsistency:
- Bone VFS scopes to ONE `uid` from the Authentik header (`vfs.py:81` `_user_root(uid)`),
  so Files shows only `users/akadmin/…`.
- KEAP mounts the ENTIRE users dir read-only
  (`roles/pazny.keap/templates/compose.yml.j2:47` — `…/users:/user-files:ro`) → it
  mirrors EVERY uid subtree.
- On disk, `tenants/pazny/users/` holds `akadmin`, `nos-docs`, **and two orphan
  64-hex (SHA256) uid trees** (`82b255…`, `fceffd43…`) — from a DIFFERENT/OLDER uid
  scheme (hash vs plaintext username). The screenshot lives in an orphan hash-uid tree
  → hidden in Files (wrong uid), surfaced by KEAP (whole-tree mirror).

So the drift compounds: (a) blank never wipes the tenants tree, and (b) old uid trees
orphan with nothing to reconcile them.

### 2c. ROOT of the uid orphans: Authentik uid is not stable across blanks
nOS never hashes uid — Bone/face use `X-Authentik-uid` verbatim (`grep sha256` in
face BFF + bone = none). `nos-docs` is the legit self-model tree
(`keap_selfmodel_uid`). The two 64-hex trees are **real Authentik uids**; the `akadmin`
tree is the anomaly (my Playwright harness sends the username as uid, not the real hash).

The mechanism: **`blank` wipes Authentik's DB → every user is re-provisioned with a NEW
uid hash → a NEW `users/<newhash>/` tree, ORPHANING the old one.** The old tree (with
the screenshot) survives (tenants not wiped), the user's new uid sees an empty tree in
Files, but KEAP mirrors ALL trees incl. the orphan → the screenshot reappears in
`/explore`. **This is the true root of the uid-orphan half** — and it means
"preserve source" is only coherent if uid is STABLE across blanks. **P1 design driver:**
either issue stable Authentik uids (seed the user pk / key the tree on username/email),
or migrate/re-key user trees when the uid changes, or prune trees whose uid maps to no
live Authentik user. Until then, even a correct preserve-source blank orphans user files.

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

## Operator decisions (2026-07-19) — LOCKED

1. **Split semantics (chosen).** `blank` = **reset DERIVED state, PRESERVE SOURCE**
   (user-files stay). `uninstall` = walk the manifest, **remove everything nOS created,
   incl. user-files**. Two clean paths.
   - Corollary: the screenshot surviving `blank` is now *intended* — the real defects
     are the ORPHAN uid-trees (junk) + KEAP surfacing files the current user can't see +
     KEAP `/data` NOT being wiped by blank (it's derived, so blank SHOULD wipe it and let
     KEAP re-sync from the preserved source).
2. **Approach (chosen): both in parallel** — ship P0 tactical now + design P1 manifest
   concurrently.
3. Manifest home — TBD in P1 design (lean toward extending `state_manager` /
   `~/.nos/state.yml`).

## Phased plan (under the split model)

- **P0 tactical (blank = preserve source; low-risk):**
  - **Wipe KEAP `/data` on blank** — add an `install_keap` → `keap_data_dir` entry to
    `_blank_dirs` (mechanical; `/data` is derived, KEAP re-syncs from the preserved
    source). This alone fixes the "KEAP shows stale mirror" half.
  - **Reconciling face seeder** — declare one canonical EXPLICIT slug per `face-*` table
    (not name-derived, so the regex fallback can't mutate it) so it never re-duplicates.
  - **Document `blank` = preserve-source** in `blank-reset.yml` header + `--blank` help
    (tenants/users surviving is intended, not a bug).
  - **Operator-confirmed cleanup (destructive — do NOT auto-run):** delete the orphan
    `face.controls` KEAP table (human `/api/tables/:id` DELETE) + prune the orphan
    hash-uid trees under `tenants/pazny/users/` after confirming they map to no live user.
- **P1 architectural:**
  - **`uninstall` path — MVP SHIPPED (2026-07-19).** `tasks/uninstall.yml` +
    `main.yml` wiring (now the `remove` ladder: `nos --remove=all` → dry-run report;
    `nos --remove=all --confirm --leave` → execute, then `meta: end_play` — no
    reinstall; the legacy `-e uninstall=…` form is shimmed, deprecated —
    `docs/nos-cli.md`). Removes the DERIVED state (reuses
    the blank teardown, DRY) + the SOURCE (`nos_data_root` in full + `~/.nos` + registry).
    Dry-run default + two confirm gates (destructive-op safety). Live-verified dry-run
    (`changed=0`, source intact); pinned by `tests/anatomy/test_uninstall_scope.py`.
    KNOWN MVP gap: a DISABLED service's stale `$HOME/<svc>` dir isn't in `_blank_dirs`
    so it's not removed (its `nos_data_root/platform` half is) — the record-at-install
    manifest (below) closes it.
  - **Managed-resource manifest (P1.5, next):** record everything nOS creates on
    install; uninstall walks the manifest so pre-existing paths are provably untouched
    and disabled-service dirs are still removed.

- **First live uninstall (2026-07-19) — `failed=0`, 57 data dirs + source + anatomy
  removed.** Two self-recreation findings (things reappearing AFTER the wipe):
  - **openclaw gateway daemon — FIXED.** `ai.openclaw.gateway.plist` (created by
    `openclaw gateway install`; nOS provisions openclaw via `npm install -g openclaw`)
    was NOT in the blank plist-removal list, so it kept running and re-created
    `~/.openclaw` right after the data-dir wipe. Added to `blank-reset.yml` (unloaded
    + removed like the eu.thisisait.nos.* plists); exempted in
    `test_blank_reset_plist_discovery` as a runtime-provisioned (non-template) plist.
  - **callback self-recreation of `~/.nos` — cosmetic, P1.5.** The `wing_telemetry`
    Ansible callback fires on every task event; with Bone down it writes an
    `events-fallback.db` under `~/.nos`, RE-CREATING the dir the source-removal task
    just deleted (the tool logs into what it deletes). Harmless (empty telemetry
    fallback, overwritten next run) but means uninstall can't leave `~/.nos` absent.
    Fix (P1.5): a `NOS_UNINSTALL` env the callback checks to skip fallback writes, or
    treat `~/.nos` as pure derived state that the next run always owns.
  - Reconciliation everywhere (seeders declare canonical sets, prune orphans).
  - uid consistency: **nOS-side SHIPPED** (2026-07-19, commit `7236b513`) —
    `canonicalUid()` in the face BFF keys the user tree on the stable username
    (then email), not Authentik's churning uid; live-verified (`username=verifyuser`
    + random uid → `users/verifyuser/`). **KEAP-side pending:** KEAP keys its
    per-user ROWS on the raw `X-Authentik-uid` (header_oidc) — align it to username
    so file-mirror owner (path = username) and row owner agree. Still open: a
    uid→tree reconcile that prunes trees mapping to no live user; decide whether
    KEAP should mirror only live-uid trees.
  - Idempotence acceptance test (install→uninstall leaves nothing; →install bit-identical)
    + post-uninstall KEAP `/agent/v1/fs/status` "0 objects" check.
