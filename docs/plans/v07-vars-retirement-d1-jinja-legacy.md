# Plan — D1 `{{ vars }}` retirement (Jinja-legacy flip)

**Status:** PLAN (not implemented). Branch: `feat/v0.7-overnight`.
**Owner:** pazny. **Confirmed item:** `v07-vars-retirement-d1-jinja-legacy`.
**Class:** ansible-core forward-compat — retire the deprecated `{{ vars }}` magic
variable that hard-breaks on ansible-core 2.24, replacing the wholesale-pass with a
GENERATED explicit namespace (design LOCKED in roadmap **O25**, 2026-06-11).

> **Scoping caveat up front:** the *full flip* (regenerating the namespace + swapping
> every call site + a full blank wet-test) is explicitly a **dedicated pre-2.24
> wet-test lane**, NOT an unsupervised overnight repo edit — see `docs/active-work.md`
> "D1 `{{ vars }}` retirement flip" and roadmap O25. This plan therefore splits into
> two phases: **Phase 1 (ship tonight, repo-only, fully gated)** lands the
> generated-namespace artifact + the drift gate + a stock-Jinja-safe seam, with the
> live call sites UNCHANGED. **Phase 2 (deferred, supervised)** is the one-by-one call-
> site flip behind a blank wet-test. Phase 1 is the durable safety net; Phase 2 is the
> cutover. This split keeps the overnight run inside the no-live-mutation, must-gate,
> trivially-reversible envelope.

---

## 1. Problem / why

ansible-core's post-2.19 templating engine eagerly resolves the **entire** play-var
namespace when a task argument is `"{{ vars }}"`. nOS leans on that in **7 live call
sites** that hand the whole `vars` dict to a custom module so it can render plugin /
manifest / state Jinja with the operator's full configuration:

| # | File:line | Arg | Module | Purpose |
|---|---|---|---|---|
| 1 | `tasks/stacks/core-up.yml:38` | `template_vars: "{{ vars }}"` | `nos_plugin_loader` (pre_render) | aggregators + compose-extension render |
| 2 | `tasks/stacks/core-up.yml:390` | `template_vars: "{{ vars }}"` | `nos_plugin_loader` | post-DB / Authentik hook render |
| 3 | `tasks/stacks/core-up.yml:599` | `template_vars: "{{ vars }}"` | `nos_plugin_loader` | post-start hook render |
| 4 | `tasks/stacks/stack-up.yml:368` | `template_vars: "{{ vars }}"` | `nos_plugin_loader` | per-stack lifecycle render |
| 5 | `tasks/blank-reset.yml:70` | `template_vars: "{{ vars }}"` | `nos_plugin_loader` (post_blank) | plugin filesystem-state cleanup |
| 6 | `tasks/pre-migrate.yml:29` | `role_vars: "{{ vars }}"` | `nos_state` (introspect) | service introspection vs manifest |
| 7 | `roles/pazny.state_manager/tasks/introspect.yml:19` | `role_vars: "{{ vars }}"` | `nos_state` (introspect) | runtime state-file regen |

*(The report-tool docstring says "6"; it predates the state_manager introspect site —
this plan counts **7** live sites. Two further matches in `tasks/tofu-authentik.yml:67`
and `roles/pazny.traefik/tasks/main.yml:44` are **comments documenting the trap**, not
call sites — out of scope, but the plan must not touch them.)*

**Why it is debt, not a working feature:**

1. **Hard break on 2.24.** `{{ vars }}` is deprecated and **removed in ansible-core
   2.24** (CLAUDE.md "Known Tech Debt" + "Stock-Jinja trap" both flag this; the 2.24
   jump is otherwise a ~4h floor bump — this is the ONE structural blocker that turns
   it into a Track). When 2.24 lands, all 7 sites raise "vars is undefined" and the
   entire stack-bring-up + state framework + blank path die at once.
2. **It is the root of the recurring stock-Jinja trap.** Because `"{{ vars }}"`
   eager-finalizes the *whole* namespace in a **filter-less** context, every
   `default.config.yml` / `default.credentials.yml` value is walked at module-arg time
   — which is exactly why a non-stock filter or an undefined-but-`default()`-guarded var
   aborts the run (the 5 gates in `tests/anatomy/test_config_stock_jinja_only.py` exist
   *only* to police this). Narrowing the pass to an **explicit** namespace shrinks that
   blast radius from "every committed var" to "the ~200 vars plugins actually
   reference", and is the strategic fix CLAUDE.md names: *"the strategic fix is to stop
   passing `{{ vars }}` wholesale."*
3. **The design is already locked + scoped.** Roadmap O25 committed the approach
   (generated explicit namespace, drift-gated) and `tools/loader-vars-report.py` already
   prints the contract (**116 plugin files → 202 distinct var refs** as of tonight; the
   docstring's "~190" is itself now drifted — direct evidence the surface grows and
   needs a gate). A previously-disproven shortcut (`hostvars[inventory_hostname]`: 126
   keys vs `vars`' 891 — play vars_files absent) is documented so we don't retry it.

**Why now (overnight, Phase 1 only):** the artifact + gate are pure repo edits and
fully offline-gatable; landing them now means that when the supervised 2.24 lane opens,
the flip is a mechanical call-site swap against an already-pinned, already-tested
namespace — not a from-scratch design under time pressure.

---

## 2. Scope (explicit)

**In scope — Phase 1, ship tonight (repo edits only; live system READ-ONLY):**

- A **generator** `tools/gen-loader-vars.py` that emits a committed YAML map of the
  exact vars the loader/state path references — the explicit replacement for
  `"{{ vars }}"`. Built on the existing `tools/loader-vars-report.py` extractor (reuse,
  don't reinvent).
- The **committed generated artifact** it produces (e.g.
  `files/anatomy/generated/loader-vars.yml` — a `set_fact`-shaped map of
  `name: "{{ name | default(omit) }}"` entries) — the single source of truth the flip
  will consume.
- A **drift gate** `tests/anatomy/test_loader_vars_namespace.py`: re-runs the extractor
  and asserts the committed artifact covers **every** var the plugin/manifest/state
  surface references (a new plugin var ref fails CI until the artifact regenerates), AND
  that every name in the artifact resolves before stack-up (reuses the
  `_defined_before_core_up()` discipline from `test_config_stock_jinja_only.py` so the
  explicit namespace can't itself reintroduce the trap).
- A **wiring seam**: a single `set_fact` task (loaded from the generated artifact via
  `vars_files`/`include_vars`, NOT inline) named e.g. `nos_loader_vars`, defined early
  enough to be in scope at all 7 call sites — **wired but not yet consumed** (sites still
  pass `"{{ vars }}"` in Phase 1). This makes Phase 2 a one-token swap per site.
- Doc updates: flip the O25 entry / `active-work.md` line from "design LOCKED" to
  "Phase 1 landed — artifact + gate live; Phase 2 (call-site flip) awaits the 2.24
  wet-test lane"; refresh the `loader-vars-report.py` docstring's stale "6 sites / ~190
  vars" to the verified "7 sites / 202 vars".

**Out of scope — Phase 2, deferred + supervised (do NOT do tonight):**

- **Actually swapping any of the 7 `"{{ vars }}"` / `"{{ vars }}"` call sites** to the
  explicit namespace. That changes the render input of all 66 plugins + the state path +
  the blank path → it **requires a full blank wet-test** (O25: "the flip itself needs a
  full blank wet-test … a dedicated pre-2.24 lane"). A `--syntax-check` cannot prove the
  render is byte-identical; only a wet blank can. This is the explicit no-go for an
  unsupervised run.
- The ansible-core 2.24 floor bump itself (`requirements.yml` / CI matrix / 66×
  `meta/main.yml`) — separate item, only after 2.24 ships stable.
- Touching the two **comment** references (`tofu-authentik.yml:67`,
  `traefik/tasks/main.yml:44`) — they document the trap; leave them.
- Removing any of the 5 `test_config_stock_jinja_only.py` gates — they stay as
  defense-in-depth until Phase 2 proves the narrowed namespace holds on a wet blank.

---

## 3. Approach (exact files + edits)

### 3.1 Generator — `tools/gen-loader-vars.py` (NEW)

Thin wrapper over the **existing** `tools/loader-vars-report.py::referenced_vars()`
(import it, don't fork the regex). It:

1. Calls `referenced_vars()` → the `set[str]` of names + file count.
2. Cross-references each name against the keys that resolve **before stack-up** (reuse
   the discovery in `test_config_stock_jinja_only.py::_defined_before_core_up()` —
   factor that helper into a shared `tests/anatomy/_vars_scope.py` or duplicate the
   ~10-line key-scan; prefer factoring). A referenced name that is **not** defined in
   `default.config.yml`/`default.credentials.yml`/`main.yml`/`tests/config.yml` is
   either an Ansible fact (`ansible_*`), a loop-local (`item`/`namespace`/…), or a true
   gap — the generator classifies and **omit-guards** every entry so an unset var
   renders as `omit`, never aborts.
3. Emits `files/anatomy/generated/loader-vars.yml`:

   ```yaml
   # GENERATED by tools/gen-loader-vars.py — DO NOT EDIT BY HAND.
   # Explicit replacement for the deprecated `{{ vars }}` wholesale pass
   # (D1 / O25). Regenerate after adding a plugin var ref; the
   # test_loader_vars_namespace gate fails until this matches the surface.
   nos_loader_vars:
     authentik_version: "{{ authentik_version | default(omit) }}"
     install_grafana: "{{ install_grafana | default(omit) }}"
     # … 200 entries, sorted, one per referenced var …
   ```

   `default(omit)` is a **stock Ansible filter** and this file is consumed via
   `include_vars`/`vars_files` then referenced through a NORMAL task `set_fact` — it is
   **not** itself fed to the `"{{ vars }}"` loader, so the stock-Jinja eager-resolve trap
   does **not** apply to its own values (verified against the gate's own scope rules in
   §4). The artifact deliberately uses `omit` (not a literal default) so a var the
   operator never set stays absent rather than forced to a wrong literal.

4. `--check` mode: print a diff and exit non-zero if the on-disk artifact is stale (the
   gate calls this; CI uses it).

### 3.2 The committed artifact — `files/anatomy/generated/loader-vars.yml` (NEW)

The generator's output, committed. Lives under `files/anatomy/generated/` (new dir;
add a `README.md` stub naming the generator so a future archaeologist knows it's
machine-authored). It is the single source of truth the Phase-2 flip consumes.

### 3.3 Wiring seam — one `set_fact`, wired-not-consumed (edit `main.yml`)

Add, in `main.yml`'s `vars_files:` (or an early `tasks:` `include_vars`), a load of the
generated artifact, then a `set_fact` materializing `nos_loader_vars` **before**
`tasks/stacks/core-up.yml` runs (so it is in scope at every call site). In Phase 1 the
fact is **defined but unreferenced** — the 7 sites still pass `"{{ vars }}"`. This is
the seam: Phase 2 changes each `template_vars: "{{ vars }}"` →
`template_vars: "{{ nos_loader_vars }}"` (and `role_vars` likewise) one site at a time
under the wet-test.

> **No behaviour change in Phase 1.** Adding an unreferenced fact cannot alter any
> render (nothing reads it yet). `--syntax-check` + the existing anatomy suite prove the
> seam is inert. This is what keeps Phase 1 inside the overnight safety envelope.

### 3.4 Doc reconciliation

- `docs/roadmap-2026q2.md` O25 block + `docs/active-work.md` D1 line: "design LOCKED" →
  "Phase 1 landed (artifact + drift gate + inert seam); Phase 2 call-site flip awaits
  the supervised 2.24 wet-test lane."
- `tools/loader-vars-report.py` docstring: "6 sites … ~190 vars" → "7 sites … 202 vars
  (regenerate the contract with `tools/gen-loader-vars.py`)".

### 3.5 No live mutation

Nothing here renders a compose file, recreates a container, or touches `~/.nos/`. The
generated artifact is inert until Phase 2 wires it into the actual `template_vars` arg —
which is the supervised lane. Overnight stays repo-only.

---

## 4. The gate (NON-NEGOTIABLE — every fix ships a gate)

New file: **`tests/anatomy/test_loader_vars_namespace.py`** (offline, fast, no network,
no live system). Source-of-truth driven so the next plugin var ref fails CI until the
artifact regenerates.

Tests:

1. **`test_artifact_covers_referenced_surface`** — re-run
   `loader-vars-report.referenced_vars()`; assert **every** referenced name (minus
   facts/loop-locals) has a key in `loader-vars.yml`. Fails when a new plugin var ref is
   added without regenerating → the drift gate O25 specifies.
2. **`test_artifact_is_in_sync_with_generator`** — call `gen-loader-vars.py --check`;
   assert exit 0 (the committed file equals fresh generation — no hand-edit drift).
3. **`test_every_artifact_entry_resolves_before_stack_up`** — every `nos_loader_vars`
   key resolves from something loaded before stack-up (reuse
   `_defined_before_core_up()`), OR is an `ansible_*` fact, OR is `omit`-guarded. This is
   the **anti-recursion** check: the explicit namespace must not reintroduce the very
   trap it retires.
4. **`test_artifact_values_use_stock_jinja_only`** — apply the
   `test_config_stock_jinja_only.py` STOCK-filter rule to `loader-vars.yml` values
   (`omit`/`default` only). Belt-and-suspenders: even though the artifact is not fed to
   the `"{{ vars }}"` loader, keeping it stock-Jinja-clean means a future maintainer
   can't make it unsafe if the consumption path ever changes.
5. **`test_seam_fact_defined_before_core_up`** — assert `main.yml` defines
   `nos_loader_vars` (via the artifact load) ahead of the first `core-up.yml` include,
   so Phase 2's swap has it in scope. (Static parse of `main.yml` task order — same
   technique as the existing config gates.)
6. **`test_no_live_callsite_flipped_yet`** *(Phase-1 guard, removed in Phase 2)* —
   assert all 7 sites still read `"{{ vars }}"`, i.e. Phase 1 did NOT accidentally flip a
   call site overnight. This is the explicit tripwire that the overnight run stayed
   inside scope; Phase 2's commit deletes this test as it flips the sites.

Plus keep the **existing** `tests/anatomy/test_config_stock_jinja_only.py` green
(unchanged) — proves Phase 1 introduced no new var trap.

**Why a gate and not just the artifact:** O25 names the drift gate as load-bearing — a
new plugin var ref must fail CI until the namespace regenerates, else Phase 2's
narrowed namespace silently goes stale and the 2.24 flip ships an incomplete map →
"undefined" at render time on the supervised blank. The gate IS the contract.

---

## 5. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Extractor misses a var ref form (e.g. `{{ vars['dynamic_' ~ x] }}`, attribute access, a var only used in a `lookup('template')` provisioning file) → artifact incomplete → Phase 2 render gets `undefined` | medium | Phase 1 does NOT consume the artifact, so an incomplete map cannot break tonight's run. The gate widens coverage to `provisioning/**/*.j2` (already in `referenced_vars()`). Phase 2's **wet blank** is the true completeness proof — that's precisely why the flip is gated behind a supervised lane, not done here. Dynamic `vars[...]` indexing (if any) is flagged by the gate as "un-extractable" and listed for manual review before Phase 2. |
| Someone runs Phase 2 (the flip) thinking this plan authorized it overnight | low | Plan + `test_no_live_callsite_flipped_yet` + the §2 out-of-scope list all hard-state Phase 2 is supervised-only. The tripwire test fails the instant a site is flipped without removing it. |
| Generated artifact churns every run (non-deterministic ordering) → noisy diffs / idempotence noise | low | Generator emits **sorted** keys; `--check` is exact-match. Deterministic output = idempotent commit. |
| The new `set_fact` collides with an existing var name | very low | `nos_loader_vars` is grepped repo-wide first (currently zero hits — confirmed: `loader_vars` / `nos_loader_namespace` not present). |
| Stock-Jinja vars trap (new var introduced) | controlled | `nos_loader_vars` is NOT added to `default.config.yml`/`default.credentials.yml` (it's a `set_fact` from a generated artifact loaded via `include_vars`), so the `test_config_stock_jinja_only.py` VARS_FILES rule doesn't gate it — but gate test #4 applies the same stock-filter rule to the artifact anyway, and #3 proves every entry resolves before stack-up. Belt + suspenders. |
| `omit` in the artifact behaves differently than the operator's actual `vars` value when a var IS set | n/a in Phase 1 | Only matters at Phase-2 consumption; the wet blank validates it. `omit` only fires for genuinely-unset vars, where `{{ vars }}` would have carried Undefined anyway. |

---

## 6. Deferred (explicitly NOT this item / Phase 2+)

- **The call-site flip itself** (7 sites → `nos_loader_vars`) + its full blank wet-test —
  the supervised pre-2.24 lane (O25). This is the actual cutover; Phase 1 only builds the
  safety net under it.
- **ansible-core 2.24 floor bump** — `requirements.yml` + CI matrix + 66× `meta/main.yml`
  `"2.20"`→`"2.24"`, one blank. Only after upstream ships 2.24 stable (CLAUDE.md: ~4h
  follow-up). The D1 flip is the precondition that turns that 4h into a clean bump.
- **Retiring the 5 `test_config_stock_jinja_only.py` gates** once the narrowed namespace
  is proven on a wet blank — they're kept as defensive hardening through Phase 2.
- **Removing the `nos_state` `role_vars` path** if state introspection turns out not to
  need the full namespace — an audit for Phase 2 (the two state sites #6/#7 may need a
  smaller map than the plugin sites; the gate can emit two namespaces if so). Not
  decided tonight.

---

## 7. Verification recipe

All offline, no live system, no network, no container mutation — safe unsupervised:

```bash
cd /Users/pazny/projects/nOS

# 1. The new drift gate passes (run BEFORE wiring to confirm it RED-flags a
#    deliberately-removed artifact key, then GREEN after — proves it catches drift).
python3 -m pytest tests/anatomy/test_loader_vars_namespace.py -v

# 2. Generator is deterministic + in sync with its committed output.
python3 tools/gen-loader-vars.py --check        # exit 0, no diff
python3 tools/gen-loader-vars.py | diff - files/anatomy/generated/loader-vars.yml

# 3. The contract count matches the artifact (sanity: 202 today, will grow).
python3 tools/loader-vars-report.py             # distinct var refs == artifact keys
python3 -c "import yaml; print(len(yaml.safe_load(open('files/anatomy/generated/loader-vars.yml'))['nos_loader_vars']))"

# 4. The Phase-1 tripwire confirms NO call site was flipped (scope held).
python3 -m pytest tests/anatomy/test_loader_vars_namespace.py::test_no_live_callsite_flipped_yet -v
grep -rn 'template_vars: "{{ vars }}"\|role_vars: "{{ vars }}"' tasks/ roles/ main.yml | grep -v '#'
#   → still exactly 7 live sites, unchanged.

# 5. The existing stock-Jinja gates stay green (no new var trap).
python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py -q

# 6. Full anatomy suite stays green (no regression from the inert seam).
python3 -m pytest tests/anatomy/ -q

# 7. Playbook still parses with the new set_fact seam wired but unconsumed.
ansible-playbook main.yml --syntax-check
```

Expected: #1 RED on a tampered artifact (proves it catches drift), GREEN after; #2/#3
deterministic + counts agree; #4 shows exactly 7 unchanged live sites; #5/#6/#7 GREEN
throughout — the inert seam changes no render.

> **NOT run tonight (Phase 2, supervised lane):** `ansible-playbook main.yml -e blank=true`
> with the flipped `nos_loader_vars` consumption — the only thing that proves the
> narrowed namespace renders byte-identical to `{{ vars }}` across all 66 plugins. That
> wet blank is destructive and supervised; this plan stops at the gated seam.

---

## 8. Commit shape (Phase 1 — when implemented, separate from this plan commit)

```
feat(anatomy): generated loader-vars namespace + drift gate (D1)

- {{ vars }} wholesale-pass (7 loader/state sites) breaks on
  ansible-core 2.24; O25 locks an explicit generated namespace.
- add tools/gen-loader-vars.py over loader-vars-report's extractor;
  commit files/anatomy/generated/loader-vars.yml (202 omit-guarded refs).
- wire nos_loader_vars set_fact before core-up — defined, NOT yet
  consumed (sites still pass {{ vars }}); the inert seam for the flip.
- gate: test_loader_vars_namespace pins coverage + sync + before-core-up
  resolution + a tripwire that no call site flipped this pass.
```

(Conventional Commits, subject ≤50 chars, surgeon-tone body ≤6 bullets, no
Co-Authored-By, no `--author`, branch-only — never pushed. The Phase-2 flip is a
separate commit on the supervised 2.24 wet-test lane.)
