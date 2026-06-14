# v0.7 — Gate the euro-office OnlyOffice blank-safe DB seed

- **Branch:** `feat/v0.7-overnight`
- **Item:** `v0.7 / test / onlyoffice-euro-office-db-seed`
- **Status:** PLAN (do not implement) — review-ready
- **Author actor:** claude (overnight, unsupervised)
- **Kind:** TEST-ONLY (gate an already-shipped behavior) + one honesty correction.
- **Related:** sibling plan `docs/plans/v07-euro-office-pilot-onlyoffice-toggle.md`
  (the *toggle ergonomics* item — disjoint from this one); devlog
  `docs/devlog/nos-core/2026/2026-06-13-euro-office-pilot.md`; existing gates
  `tests/anatomy/test_onlyoffice_connector_urls.py`,
  `test_wordpress_rbac_mirror.py::test_onlyoffice_image_is_flippable_var`.

---

## 1. Problem / why

The euro-office pilot (2026-06-13) added a **blank-safe embedded-postgres DB seed**
to the OnlyOffice role. It lives **today, shipped**, in
`roles/pazny.onlyoffice/tasks/main.yml` (lines 26–58): two tasks that, *only for the
euro-office fork image*, detect a fresh/empty `onlyoffice_db_dir` and `cp -a` the
postgres cluster out of the image layers into the bind mount — because the
euro-office entrypoint **cannot `initdb` an empty PGDATA** (the cluster is baked into
the image), so an empty bind mount shadows it and the container restart-loops on
`16/main not accessible`, failing a blank at the b2b health-wait. The stock
`onlyoffice/documentserver` image *does* `initdb` an empty dir, so the seed is
correctly gated to fire **only** when the image string matches `euro-office`.

**This load-bearing, blank-or-bust behavior is completely UNGATED.** Grep over
`tests/anatomy/` proves it:

```
$ grep -rln 'seed-target\|_oo_seed\|_oo_db_contents' tests/
# → only test_onlyoffice_connector_urls.py mentions onlyoffice at all,
#   and it gates the CONNECTOR URLs, NOT the DB seed.
```

The only OnlyOffice gates that exist pin (a) the Nextcloud↔docserver connector URLs
and (b) the *flippable image var*. **Nothing pins the seed.** That is a real risk for
an item whose whole point is "a blank with the fork doesn't restart-loop":

1. **Silent regression surface.** A future role-thinning / refactor / the sibling
   `onlyoffice_flavor` toggle item can easily:
   - drop or reorder the `cp -a` seed task,
   - weaken the `is search('euro-office')` guard so the seed fires for the **stock**
     image too (it would clobber stock's own `initdb` path, or no-op harmlessly —
     either way undocumented drift),
   - flip the freshness check (`matched == 0`) so the seed runs on a **populated**
     dir and overwrites a live cluster,
   - turn the non-destructive `cp -a` into a `rm -rf`-then-copy "cleanup."
   None of these is caught by any test, syntax-check, or lint. A blank-only failure
   surfaces ~12 minutes into a cold b2b converge — the most expensive possible place
   to learn the seed broke.

2. **A doctrine-honesty defect in the sibling plan.** The toggle plan
   (`v07-euro-office-pilot-onlyoffice-toggle.md`, §1) asserts the seed is *"already
   shipped **and gated**"* and §4 lists the seed among invariants "kept passing
   unchanged." **It is shipped but NOT gated.** This item makes that sentence true by
   actually shipping the gate, and corrects the one phrase so the plan record is
   honest (machinery doctrine: the claim and the code must agree).

3. **The seed touches the embedded cluster — exactly the class nOS wants pinned as
   non-destructive.** The destructive-op safety memory wants destructive-adjacent
   paths to be auditable and provably move-aside / copy, never delete. A gate that
   *forbids* `rm`/`state: absent`/`absent`/`rm -rf` anywhere near `onlyoffice_db_dir`
   in the role is the cheapest durable enforcement of that line for this surface.

**Why now (v0.7):** the seed is live in the tree and the sibling toggle item is
queued on the same branch — it *will* edit `tasks/main.yml`. Landing this gate
**first** means the toggle work converges against a pinned contract instead of
silently reshaping an untested behavior. This is a pure test add: zero behavior
change, zero live mutation, fully reversible.

---

## 2. Exact files / roles to touch

All edits are **repo-only**; no live-system writes; nothing destructive.

### 2.1 `tests/anatomy/test_onlyoffice_euro_office_db_seed.py` (NEW — the gate)
The whole deliverable. Offline, fast, string/structure assertions over the role's
`tasks/main.yml` (+ a light parse). Follows the exact style of
`test_onlyoffice_connector_urls.py` (read the file text, assert literals/shape;
optionally `yaml.safe_load` the task list for the structural asserts). See §4 for the
test bodies.

### 2.2 `roles/pazny.onlyoffice/tasks/main.yml` — (NO behavior change; ONLY if §4 reveals a gap)
The plan's **default posture is: do not touch the task file at all** — the seed is
already correct and the gate simply pins it. The only sanctioned edit here is if
writing the gate surfaces a *genuine* contract weakness the test must assert against
but the code doesn't yet satisfy (e.g. a missing flavor-agnostic comment anchor the
test keys on). In that case the edit is the minimal anchor/comment to make the
behavior assertable, never a logic change. **If the seed logic itself needs changing,
that is a different item, not this one.** (Listed so the reviewer knows the file was
considered; expected diff = none.)

### 2.3 `docs/plans/v07-euro-office-pilot-onlyoffice-toggle.md` — one-line honesty fix
Change the §1 claim *"All of that is already shipped **and gated**"* → *"already
shipped; the DB seed is gated by `test_onlyoffice_euro_office_db_seed.py` (this
branch)"* and adjust the §4 invariant line that currently implies the seed gate
already exists. **Optional / reviewer's call** — it's a sibling plan doc, not code.
If the reviewer prefers to leave the sibling plan untouched, drop this sub-item; the
gate stands on its own. (Kept here because doctrine says the record shouldn't lie.)

**Explicitly NOT touched:**
- `roles/pazny.onlyoffice/defaults/main.yml`, `compose.yml.j2` — no change; the
  `onlyoffice_flavor` toggle + image/version derivation belong to the **sibling**
  item, not this test item. This gate asserts the seed against the *current* var
  shape (`onlyoffice_image`/`onlyoffice_version`), so it stays green before AND after
  the sibling lands (it keys on `is search('euro-office')`, not on a specific var
  name spelling).
- No `default.config.yml` / `default.credentials.yml` edits → the stock-Jinja
  `{{ vars }}` trap is **not in play** for this item (no new vars at all).
- No profile, no role rename, no Documenso — all sibling/deferred scope.

---

## 3. Approach (what the gate pins, and why each assertion)

The gate encodes the seed's **five load-bearing invariants** as independent tests, so
a regression names *which* property broke:

1. **The seed exists and copies, not deletes.** Assert the `cp -a /var/lib/postgresql/.
   /seed-target/` command (or its `argv` equivalent) is present in the task file. The
   seed is a *copy out of the image*, never a wipe.

2. **It is euro-office-ONLY.** Both the detect task and the seed task carry
   `when: onlyoffice_image ... is search('euro-office')`. Assert both `when` guards
   reference `euro-office` so the stock image never enters the seed path (stock
   `initdb`s its own empty dir; seeding it would be wrong).

3. **It is blank-safe / fire-once (idempotent).** The seed task's `when` requires the
   freshness predicate `(_oo_db_contents.matched | default(0)) == 0` — it runs **only
   on an empty dir**, so a re-run over a populated cluster is a no-op. Assert the
   `matched == 0` freshness gate is present and wired to the detect task's register
   (`_oo_db_contents`).

4. **It NEVER destroys the db dir (the doctrine line).** Regex-assert that **nowhere**
   in `roles/pazny.onlyoffice/tasks/main.yml` is there a `state: absent` /
   `file: ... absent` / `rm -rf` / `rm ` targeting `onlyoffice_db_dir` (or the
   `/seed-target` mount, or the `db` dir). The only mutation of that dir is the
   `cp -a` copy. This is the cheapest enforcement of "move-aside/copy, never delete."

5. **The detect task is side-effect-free.** Assert the `find` detect task is
   `changed_when: false` (a read), and the seed task's `changed_when` keys off the
   command rc (`_oo_seed.rc == 0`) — a clean idempotency contract, not a blanket
   `changed`.

**Ordering / robustness of the gate itself:**
- Prefer `yaml.safe_load(tasks_main)` and walk the task dicts for the structural
  asserts (2,3,5) so trivial whitespace/reflow doesn't false-fail; fall back to
  substring asserts for the literals (1,4) the way `test_onlyoffice_connector_urls.py`
  does. This makes the gate resilient to the sibling toggle's reformatting while still
  catching real logic drift.
- Each assertion carries a message naming the invariant and *why it matters*
  (blank-loop / clobber / destroy), so a future failure is self-explaining.

**Why a gate and not a wet-test:** the seed only manifests on a *cold euro-office
blank* (12-min b2b converge, cold fork pull) — far too expensive and live-mutating to
run overnight. A static gate over the task file catches every regression of the five
invariants in milliseconds, offline, with zero live touch. The wet converge stays an
operator-gated step (see §6).

---

## 4. Gates it needs (this item IS the gate)

New file `tests/anatomy/test_onlyoffice_euro_office_db_seed.py` (offline, fast, no
live system, no network). Concrete test set:

- `test_seed_task_copies_cluster_out_of_image` — the `cp -a /var/lib/postgresql/.
  /seed-target/` copy is present (string assert over the `argv`).
- `test_seed_is_euro_office_only` — both the detect and the seed task `when` guards
  contain `is search('euro-office')`; assert the stock image string cannot reach the
  seed (no seed task without the euro-office guard).
- `test_seed_is_blank_safe_fire_once` — the seed task `when` includes the
  `(_oo_db_contents.matched | default(0)) == 0` freshness predicate, and it registers
  off the `find` detect task (`_oo_db_contents`) — runs only on an empty dir.
- `test_seed_never_destroys_db_dir` — **the doctrine line.** Regex over the whole
  `tasks/main.yml`: no `state: absent`, no `rm -rf`, no `rm ` / `unlink` /
  `file:.*absent` touching `onlyoffice_db_dir`, `/var/lib/postgresql`, `/seed-target`,
  or the literal `db` dir. The ONLY write to that dir is the `cp -a`.
- `test_detect_task_is_read_only` — the `find` detect task is `changed_when: false`.
- `test_seed_changed_when_keys_off_rc` — the seed task is
  `changed_when: _oo_seed.rc == 0` (clean idempotency, not blanket-changed).
- `test_seed_survives_sibling_toggle_shape` — the gate keys on `is search('euro-office')`
  / `_oo_db_contents` / `_oo_seed`, **not** on a specific `onlyoffice_image` literal,
  so it stays green before AND after the sibling `onlyoffice_flavor` derivation lands
  (forward-compat assertion: assert the guard is image-string-content based).

**Suite + syntax invariants (must stay green, per the hard rules):**
- `python3 -m pytest tests/anatomy/ -q` — full anatomy suite green (167 test files
  today; this adds 1). No existing gate changes behavior.
- `test_onlyoffice_connector_urls.py` and
  `test_wordpress_rbac_mirror.py::test_onlyoffice_image_is_flippable_var` keep passing
  **unchanged** (this item edits no role var/template they assert on).
- `ansible-playbook main.yml --syntax-check` — clean (no playbook edit; only a new
  test file + an optional plan-doc line).
- `ansible-lint` production profile — clean (test files aren't linted; no role logic
  change).

---

## 5. Risks

- **R1 — gate over-fits the current literal phrasing and false-fails the sibling
  toggle reformat.** The sibling item *will* reshape `tasks/main.yml`. *Mitigation:*
  key the structural asserts on `yaml.safe_load`'d task fields (register names,
  `when` predicates, `changed_when`) and on the **content** of the guard
  (`euro-office`, `matched`, `cp -a`), never on exact line text or task ordering.
  `test_seed_survives_sibling_toggle_shape` explicitly pins image-string-content over
  literal var spelling. Net: the gate catches logic drift, tolerates cosmetic drift.

- **R2 — the negative `rm`/`absent` regex is too broad and trips on an unrelated,
  legitimate cleanup elsewhere in the role.** *Mitigation:* scope the destructive-op
  regex to lines that *also* reference the db-dir/PGDATA/seed-target tokens, not a
  blanket "`rm` appears anywhere." Today the role has no such cleanup, so the assert
  is currently vacuously safe; the scoping keeps it from blocking an unrelated future
  task.

- **R3 — the gate documents a behavior that itself has a latent bug (false sense of
  security).** Pinning a wrong behavior is worse than no gate. *Mitigation:* §3 only
  pins invariants that are *correct by the euro-office image's documented constraint*
  (entrypoint can't `initdb` empty PGDATA → must seed; stock can → must NOT seed).
  These match the role comment block (lines 25–41) and the live switch procedure. If
  the gate-writing surfaces a real seed bug, that becomes its **own** item (this one
  stays test-only).

- **R4 — `is search` vs a future `onlyoffice_flavor`-derived image.** If the sibling
  derives `onlyoffice_image` from a flavor enum, `is search('euro-office')` still
  holds (the derived value is `ghcr.io/euro-office/documentserver`). *Mitigation:* the
  gate asserts the *guard mechanism* (image-string contains `euro-office`), which the
  sibling derivation preserves by construction. Cross-checked against the sibling
  plan's §3.1 ("default `stock` → same image"; euro-office → fork image string).

- **R5 — touching the sibling plan doc (§2.3) creates a merge dependency.** *Mitigation:*
  §2.3 is explicitly optional; if it risks churn, drop it and ship the gate alone. The
  honesty correction can ride the sibling item's own commit instead.

---

## 6. Verification recipe (repo-only; live system READ-ONLY)

```bash
# 0. On the right branch
git -C /Users/pazny/projects/nOS branch --show-current        # feat/v0.7-overnight

# 1. The new gate passes, and it actually BITES — prove it fails if the seed
#    or a guard is removed (mutation sanity), then restore:
python3 -m pytest tests/anatomy/test_onlyoffice_euro_office_db_seed.py -q
#   (manual mutation check, NOT committed: temporarily delete the `cp -a` argv
#    line in roles/pazny.onlyoffice/tasks/main.yml → re-run → expect RED →
#    `git checkout` to restore. A green-no-matter-what gate is not a gate.)

# 2. The pre-existing OnlyOffice gates still pass unchanged
python3 -m pytest tests/anatomy/test_onlyoffice_connector_urls.py \
                  tests/anatomy/test_wordpress_rbac_mirror.py -q

# 3. Full anatomy suite green (no regression from the new file)
python3 -m pytest tests/anatomy/ -q

# 4. Syntax + lint clean (no role logic changed)
ansible-playbook main.yml --syntax-check
ansible-lint roles/pazny.onlyoffice

# 5. READ-ONLY live spot-check (ONLY if the operator already runs the fork —
#    proves the gated behavior matches reality; never writes):
docker ps --filter name=b2b-onlyoffice --format '{{.Image}} {{.Status}}'
#   euro-office image + (healthy) → the seed worked on the live install.
ls -la ~/onlyoffice/db/ 2>/dev/null | head        # cluster present, dir non-empty
#   ^ READ-ONLY; never mutate the live db dir.
```

A full *wet* euro-office blank (cold fork pull → empty db_dir → seed fires → b2b
health-wait green) is an **operator-gated** step on a scratch host
(`ansible-playbook main.yml -e @profiles/euro-office-pilot.yml -e blank=true`, once
the sibling profile lands) — **NOT run overnight**, per the no-live-mutation /
no-`blank=true` rule. This item ships the gate; the wet proof is the operator's.

---

## 7. Commit (plan doc only — implementation lands separately)

Single commit on `feat/v0.7-overnight`, Conventional Commits, subject ≤50 chars,
surgeon-tone body ≤6 bullets, no Co-Authored-By, no `--author`, **no push**:

```
docs(plan): gate euro-office onlyoffice DB seed

- shipped blank-safe seed (tasks/main.yml 26-58) is UNGATED
- a refactor can silently break the no-initdb fork seed
- plan test_onlyoffice_euro_office_db_seed.py: 7 invariants
- pins cp-a copy, euro-office-only, fire-once, never-rm db dir
- corrects sibling plan's "already gated" claim to true
- test-only, zero behavior change, zero live mutation
```
