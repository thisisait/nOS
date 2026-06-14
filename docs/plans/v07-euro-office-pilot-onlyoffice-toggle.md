# v0.7 — Euro-office pilot: a first-class `onlyoffice` image toggle

- **Branch:** `feat/v0.7-overnight`
- **Item:** `v0.7 / euro-office-pilot / onlyoffice-toggle`
- **Status:** PLAN (do not implement) — review-ready
- **Author actor:** claude (overnight, unsupervised)
- **Related:** devlog `docs/devlog/nos-core/2026/2026-06-13-euro-office-pilot.md`;
  active-work line "Euro-office: full role swap after first stable"; ADR n/a.

---

## 1. Problem / why

[euro-office](https://github.com/euro-office) is the Nextcloud/IONOS/Proton/XWiki/
OpenProject consortium fork of ONLYOFFICE DocumentServer — AGPLv3, multi-arch
(arm64 verified), and JWT-contract-compatible with `onlyoffice/documentserver`.
nOS already pilots it: the role's compose template renders
`{{ onlyoffice_image }}:{{ onlyoffice_version }}` (defaulting to the stock image),
the connector internal-URLs are wired, the service-name is a rename-safe var, and a
blank-safe DB seed is in place. All of that is **already shipped** and gated
(`tests/anatomy/test_onlyoffice_connector_urls.py`,
`test_wordpress_rbac_mirror.py::test_onlyoffice_image_is_flippable_var`).

What is NOT shipped — and what this item closes — is the **operator ergonomics +
safety of actually flipping the pilot on an existing install**:

1. **The flip is a raw, undiscoverable two-line `config.yml` edit.** There is no
   single semantic toggle (`onlyoffice_flavor: euro-office`), no profile, and no
   place a reviewer/operator can see "this install runs the fork." The image +
   version are coupled in the operator's head only (the devlog warns "keep
   image/version flips separate" — but nothing *enforces* the version is re-pinned
   away from `9.3.1.2`, which **does not exist** on the euro-office ghcr registry →
   a silent `manifest unknown` pull failure at the b2b health-wait).

2. **The existing-install switch is a manual, documented-only `docker run … cp -a`
   DB-reseed dance.** The role auto-seeds the embedded postgres cluster **only when
   `onlyoffice_db_dir` is empty/fresh** (blank path). On a *live* OnlyOffice→
   euro-office switch the dir is NOT empty — it carries the stock image's cluster
   with the `onlyoffice` DB user, but euro-office authenticates as `eurooffice`, so
   docservice hangs and the healthcheck 502s while supervisor reports RUNNING. The
   operator must today run the 4-step `stop / mv-aside / cp-a-from-image / start`
   procedure **by hand** from a comment block in `defaults/main.yml`. That is
   exactly the class of un-gated, easy-to-fat-finger live mutation nOS doctrine
   wants behind a dry-run-default, audited path — and it must **never auto-destroy**
   the existing cluster (the reseed moves it aside, it does not `rm`).

3. **No profile + no wait-timeout headroom for the cold fork pull.** `all-on.yml`
   enables `install_onlyoffice` against the stock image only. The euro-office image
   is a separate cold pull at the b2b health-wait; without a pilot profile that sets
   the flavor AND a generous `stack_up_wait_timeout`, a first euro-office converge
   races the 540 s default and rc=124s (the same failure mode `all-on` already
   documents for gitlab/b2b).

**Why now (v0.7, not "after first stable"):** the role-rename to `pazny.eurooffice`
correctly waits for the first euro-office *stable* (summer 2026) — preview builds
don't own a role name. But the *toggle ergonomics + the existing-install switch
safety* are independent of the rename and are what make the pilot actually usable
overnight without a manual `docker run`. This item ships the **operator-safe
toggle**, not the rename.

---

## 2. Exact files / roles to touch

All edits are **repo-only**; no live-system writes. Nothing destructive.

### 2.1 `roles/pazny.onlyoffice/defaults/main.yml`
- Add a single semantic toggle `onlyoffice_flavor` (enum `stock` | `euro-office`,
  default `stock`) as the operator-facing source of truth.
- **Derive** `onlyoffice_image` + `onlyoffice_version` + `onlyoffice_service_name`
  from `onlyoffice_flavor` via a stock-Jinja ternary, so flipping ONE var moves the
  image, the correct default tag (`latest` for the fork — it has no semver image
  tags yet — vs the pinned CE tag for stock), and the connector alias in lockstep.
  Keep the explicit `onlyoffice_image`/`onlyoffice_version` overrides as
  higher-precedence escape hatches (var-files outrank role defaults) so an operator
  can still pin a specific fork CI tag.
- Keep the existing migration-trap comment block; trim the manual `docker run`
  steps to a pointer to the new task (§2.3) once it exists.

> **Stock-Jinja trap guard:** `onlyoffice_flavor` and the derived vars live in a
> **role** default (`roles/pazny.onlyoffice/defaults/`), which is in scope only
> during stack-up (after core-up) — so they may use ansible filters freely and are
> NOT subject to the `{{ vars }}` eager-resolve trap. The toggle is deliberately
> NOT added to `default.config.yml` for that reason (and to avoid a global). If a
> reviewer insists on a `default.config.yml` toggle, it MUST use stock filters +
> a real default and be added to `test_config_stock_jinja_only.py`'s allow path —
> default plan keeps it role-local.

### 2.2 `roles/pazny.onlyoffice/templates/compose.yml.j2`
- No structural change required — it already renders from the vars. Confirm the
  derived `onlyoffice_version` flows through (it does, line 17). If the derivation
  lands in defaults, the template is untouched. (Listed so the reviewer knows it was
  considered, not skipped.)

### 2.3 `roles/pazny.onlyoffice/tasks/main.yml` — existing-install switch detection + GUARD
- Add a **dry-run-default, non-destructive** pre-flight that detects the
  OnlyOffice→euro-office mismatch on an existing (non-empty) `onlyoffice_db_dir`:
  - When `onlyoffice_flavor == 'euro-office'` AND `onlyoffice_db_dir` is non-empty
    AND a marker file (see below) says the dir was last seeded by the *stock*
    cluster → the cluster is incompatible.
  - **Default behavior = LOUD FAIL with the exact remediation**, not auto-mutate:
    `fail:` with the 4-step procedure + the one-flag opt-in
    (`-e onlyoffice_switch_reseed=true`) to authorize the supervised reseed. This
    keeps the destructive-adjacent step operator-gated (matches the FreePBX/ERPNext
    risk-accept precedent and the destructive-op safety memory).
  - When `onlyoffice_switch_reseed=true` is explicitly passed: perform the
    **non-destructive** reseed = `mv <db_dir> <db_dir>.stock-backup-<ISO8601>` (move
    aside, never `rm`) → recreate dir → run the existing `cp -a` image-seed task.
    The existing blank-safe seed task already does the `cp -a`; this just makes the
    "dir is non-empty but wrong-flavor" case reachable behind the opt-in flag.
- Write/refresh a **flavor marker** (`{{ onlyoffice_db_dir }}/.nos-oo-flavor`)
  recording which flavor last seeded the cluster, so the mismatch is detectable
  idempotently and the guard does not fire on a healthy already-euro-office dir.
- All new tasks carry correct `changed_when` / `when` gates and `check_mode`-safe
  shape (the detection `find` is `changed_when: false`).

### 2.4 `profiles/euro-office-pilot.yml` (NEW)
- A committed opt-in profile mirroring the `all-on.yml` pattern:
  ```yaml
  install_nextcloud: true
  install_onlyoffice: true
  onlyoffice_flavor: euro-office
  stack_up_parallel: false
  stack_up_wait_timeout: 900   # cold fork-image pull headroom at the b2b health-wait
  ```
  Run with `ansible-playbook main.yml -e @profiles/euro-office-pilot.yml`. Documents
  the cold-pull timeout reason inline (same rationale block style as `all-on.yml`).

### 2.5 `roles/pazny.onlyoffice/README.md` + devlog cross-ref
- Replace the "flip two lines in config.yml" prose with the `onlyoffice_flavor`
  toggle + the existing-install switch procedure (now `-e onlyoffice_switch_reseed=
  true`, one supervised command). Add a one-line "v0.7" note to the devlog's "what
  pins it" tail so the narrative stays honest (devlog is append-context only).

### 2.6 `tests/anatomy/test_euro_office_toggle.py` (NEW gate) — see §4.

**Explicitly NOT touched (out of scope, deferred to "first stable"):**
- Role rename `pazny.onlyoffice` → `pazny.eurooffice`, the plugin manifest dir
  rename, the `state/manifest.yml` row id, the service registry. (active-work item;
  preview builds don't own a role name.)
- `default.config.yml` install flag rename. `install_onlyoffice` stays the toggle.
- Documenso — untouched; euro-office has no e-signing (`test_claude_md_documenso_
  independence.py` already pins this).

---

## 3. Approach (ordering + idempotency)

1. **Toggle derivation in defaults** — `onlyoffice_flavor` is the single knob; image/
   version/service-name derive from it with explicit-override precedence. A stock
   run is byte-identical to today (default `stock` → same image + `9.3.1.2` tag).
2. **Marker-based flavor detection** — the role writes `.nos-oo-flavor` after a seed
   so the existing-install guard is idempotent and only fires on a true mismatch.
   No marker (legacy dir) + euro-office flavor + non-empty dir = treat as stock →
   guard fires (conservative).
3. **Guard-then-opt-in for the live switch** — default = fail-with-instructions
   (zero live mutation); `-e onlyoffice_switch_reseed=true` = supervised,
   non-destructive move-aside + image-seed. Blank path is unchanged (empty dir →
   existing seed task runs, no guard, no opt-in needed).
4. **Profile** makes the pilot a one-flag converge with the right timeout.
5. **Gate** pins the toggle shape, the override precedence, the non-destructive
   move-aside (asserts `rm`-of-the-db-dir is absent), and the profile contents.

This keeps the **blank path identical**, makes the **stock path identical**, and
puts the **only risky transition (live cluster swap) behind an explicit, audited,
non-destructive, operator-typed flag** — satisfying the unsupervised-overnight rules.

---

## 4. Gates it needs (the fix is not a fix without these)

New file `tests/anatomy/test_euro_office_toggle.py` (offline, fast, no live system):

- `test_flavor_toggle_exists_and_defaults_stock` — `onlyoffice_flavor` declared in
  role defaults, default `stock`; a stock render still resolves to
  `onlyoffice/documentserver` + the pinned CE tag (no behavior change).
- `test_euro_office_flavor_derives_fork_image_and_latest_tag` — flavor
  `euro-office` derives `ghcr.io/euro-office/documentserver` and `latest` (NOT the
  non-existent `9.3.1.2` fork tag — the exact silent-pull-fail this guards).
- `test_explicit_image_override_outranks_flavor` — a hand-set `onlyoffice_image`
  still wins (escape hatch preserved); asserts the derivation uses
  `| default(...)`-style precedence, not an unconditional set.
- `test_existing_install_switch_is_guarded_not_auto` — `tasks/main.yml` contains the
  mismatch `fail:` guard AND the `onlyoffice_switch_reseed` opt-in gate; the live
  reseed task is `when: onlyoffice_switch_reseed | default(false)`.
- `test_switch_reseed_is_non_destructive` — the switch path MOVES the dir aside
  (`mv … .stock-backup-`) and there is **no `rm`/`absent`/`state: absent` on
  `onlyoffice_db_dir`** anywhere in the role (regex assert) — the doctrine line.
- `test_flavor_marker_written` — `.nos-oo-flavor` marker write present (idempotent
  detection contract).
- `test_pilot_profile_shape` — `profiles/euro-office-pilot.yml` exists, sets
  `onlyoffice_flavor: euro-office`, `install_onlyoffice: true`,
  `install_nextcloud: true`, sequential bring-up, and a `stack_up_wait_timeout`
  ≥ the 540 default.

**Suite + syntax invariants (must stay green, per the hard rules):**
- `python3 -m pytest tests/anatomy/ -q` — full anatomy suite green (1225+ today).
- The pre-existing `test_onlyoffice_connector_urls.py` +
  `test_wordpress_rbac_mirror.py::test_onlyoffice_image_is_flippable_var` keep
  passing unchanged (the derivation must not break the `{{ onlyoffice_image |
  default('onlyoffice/documentserver') }}` literal those assert on — keep that exact
  default string in the template).
- `ansible-playbook main.yml --syntax-check` — clean.
- `ansible-lint` production profile — clean (the new tasks follow the role's
  existing `changed_when`/`when` conventions).

---

## 5. Risks

- **R1 — the connector-URL gate asserts a literal default string.**
  `test_onlyoffice_connector_urls.py` and the flippable-var gate assert the exact
  text `{{ onlyoffice_image | default('onlyoffice/documentserver') }}` in the
  template and `'onlyoffice_service_name: "onlyoffice"'` in defaults. The derivation
  must therefore live in **defaults** (computing the value behind those same var
  names) and leave the template literals untouched. *Mitigation:* derive into the
  existing var names; do not rename or move the template expressions. The new gate
  + the old gate both run = drift caught either direction.

- **R2 — stock-Jinja `{{ vars }}` eager-resolve trap.** Only bites vars in scope
  *before* core-up. `onlyoffice_flavor` + derivations are **role defaults**
  (stack-up scope), so they are safe to use ansible filters. *Mitigation:* keep the
  toggle role-local (NOT in `default.config.yml`); if a reviewer moves it global, it
  must use stock filters + a real default and be added to
  `test_config_stock_jinja_only.py`. Plan default avoids the trap entirely.

- **R3 — operator runs the pilot with the stale `9.3.1.2` tag and gets a silent
  `manifest unknown`.** Exactly why the derivation forces `latest` for the fork and
  a gate asserts it. *Mitigation:* covered by
  `test_euro_office_flavor_derives_fork_image_and_latest_tag`.

- **R4 — the live switch is destructive-adjacent.** Mitigated by design: default =
  fail-with-instructions (no mutation), opt-in = **move-aside not delete**, and a
  gate forbids any `rm`/`absent` on the db dir. The operator's existing cluster is
  always recoverable (`.stock-backup-<date>`). No auto-scheduled path.

- **R5 — euro-office is a preview (no semver image tags).** Accepted, scoped: the
  pilot intentionally tracks `latest`; the role rename + tag-pin wait for stable.
  This item does not change that posture — it just makes the preview toggle safe.

- **R6 — `find` over a large `onlyoffice_db_dir` on every run.** The detection
  `find` is `file_type: any` but can be scoped to a shallow `recurse: false` /
  marker-file existence check to stay cheap and `changed_when: false`. *Mitigation:*
  prefer a `stat` on the `.nos-oo-flavor` marker over a full `find` where possible.

---

## 6. Verification recipe (repo-only; live system READ-ONLY)

```bash
# 0. On the right branch
git -C /Users/pazny/projects/nOS branch --show-current        # feat/v0.7-overnight

# 1. New + pre-existing gates green
python3 -m pytest tests/anatomy/test_euro_office_toggle.py \
                  tests/anatomy/test_onlyoffice_connector_urls.py \
                  tests/anatomy/test_wordpress_rbac_mirror.py -q

# 2. Full anatomy suite still green (no regression)
python3 -m pytest tests/anatomy/ -q

# 3. Syntax clean
ansible-playbook main.yml --syntax-check

# 4. ansible-lint clean (production profile, as CI runs it)
ansible-lint roles/pazny.onlyoffice profiles/euro-office-pilot.yml

# 5. Render-only proof the toggle derives correctly (NO live mutation):
#    stock flavor → stock image + pinned tag; euro-office flavor → fork + latest.
#    Use a check-mode render of the compose override into a tmp stacks_dir, or a
#    standalone debug play that imports the role defaults and prints the derived
#    onlyoffice_image / onlyoffice_version / onlyoffice_service_name for each flavor.
ansible-playbook main.yml --tags onlyoffice --check --diff \
  -e onlyoffice_flavor=euro-office -e stacks_dir=/tmp/nos-render-check \
  | grep -E 'onlyoffice_image|onlyoffice_version|euro-office'   # expect fork + latest

# 6. READ-ONLY live spot-check (only if the operator already runs the pilot):
docker ps --filter name=b2b-onlyoffice --format '{{.Image}} {{.Status}}'   # healthy
docker exec b2b-nextcloud-1 sh -c \
  'php occ onlyoffice:documentserver --check' 2>/dev/null || true          # "successfully connected"
#   ^ READ-ONLY occ check; never write to the live system.
```

A full wet-test of the *euro-office* converge (cold fork pull + blank-safe seed) is
an **operator-gated** step (`ansible-playbook main.yml -e @profiles/euro-office-pilot.yml`
on a scratch host) — NOT run overnight, per the no-live-mutation rule. The plan
ships the toggle + gates; the wet converge is left to the operator.

---

## 7. Commit (plan doc only — implementation lands separately)

Single commit on `feat/v0.7-overnight`, Conventional Commits, subject ≤50 chars,
surgeon-tone body ≤6 bullets, no Co-Authored-By, no `--author`, **no push**:

```
docs(plan): euro-office onlyoffice flavor toggle

- pilot flip is a raw 2-line config edit + manual DB reseed
- add onlyoffice_flavor toggle; derive image/tag/alias in defaults
- existing-install switch = guarded opt-in, move-aside not delete
- profiles/euro-office-pilot.yml + cold-pull wait headroom
- gated by tests/anatomy/test_euro_office_toggle.py
```
