# v0.7 TOFU — No auto-adopt: a gated, dry-run tenant-reconcile preflight

Status: PLAN (do not implement from this doc without operator review)
Branch: `feat/v0.7-overnight`
Source item: `tools/workflows/v07-overnight-review.mjs` → `tofu` dimension —
"tofu has NO automatic adopt/reconcile for an existing tenant" (gap #1 of the
two named gaps).
Related: ADR-0001, `docs/opentofu-authentik-cutover.md`, `tasks/tofu-authentik.yml`,
`tools/tofu-authentik-adopt.sh`, memory `tofu-authentik-cutover-state`,
`feedback-destructive-op-safety` (manual-over-auto, dry-run default).

> **Scope note — the OTHER named gap is already closed.** The review prompt
> bundles two gaps: (1) no automatic adopt/reconcile, and (2) the destroy guard
> does not catch dangerous UPDATEs to wrong pks. Gap (2) **shipped and is gated**
> — `filter_plugins/nos_tofu_guard.py::nos_tofu_immutable_field_updates` +
> the `[tofu-authentik] REFUSE apply — in-place change to an immutable field`
> task block (`tasks/tofu-authentik.yml:184`) + `tests/anatomy/test_tofu_destroy_guard.py`
> already refuse an in-place `client_id`/`external_host`/`slug` flip. This plan
> covers **only gap (1)**, and does NOT re-open gap (2).

---

## 1. Problem / why

`authentik_engine: tofu` is the live authority (cutover complete 2026-06-12).
The steady-state flow assumes the OpenTofu state already mirrors the live
Authentik tenant. That assumption holds **on a blank** (tofu provisions the whole
graph from scratch). It does **NOT** hold for an **existing tenant** that was
provisioned imperatively (blueprint engine) and now wants to flip to `tofu`, nor
for a tenant whose state was lost / reset out from under a live deployment.

Today the only bridge for an existing tenant is `tools/tofu-authentik-adopt.sh`:
a one-time `import {} + tofu plan -generate-config-out` tool. It works, but the
adopt path has four concrete weaknesses that make it fragile and easy to get
wrong — the literal meaning of "tofu has NO automatic adopt/reconcile":

1. **No readiness preflight.** Nothing tells an operator *before* they flip
   `authentik_engine: tofu` whether the live tenant and the OpenTofu state are
   already in sync. The first signal you get is the destroy guard firing mid-run
   (`REFUSE apply — plan would destroy N resource(s)`) — a hard playbook FAIL on
   a converge, not a calm advisory. The guard is correct (it prevents the SSO
   outage) but it surfaces the drift at the worst possible moment.

2. **The adopt artifacts are gitignored and never round-trip.** `.gitignore:61-62`
   ignores `generated.tf` + `imports.generated.tf`. The adopt script writes them,
   the operator is told to "review + refactor + commit," but there is no gate
   proving the committed state is consistent with the registry — so an adopt that
   was done half-way (imports landed, refactor skipped) leaves a tenant that
   plans dirty forever with nothing flagging it.

3. **The adopt tool is undiscoverable and unpinned.** It is a bash script with
   embedded Python heredocs, no test, and is referenced only in two prose
   sentences (`tasks/tofu-authentik.yml:176`, the cutover doc). The import-id
   format (`<outpost_uuid>:<provider_pk>` for attachments) is load-bearing and
   already bit the cutover (trap #3 lineage); a typo there silently produces an
   adopt that imports nothing and plans every attachment as a create. Only
   `test_tofu_registry_bridge.py::test_adopt_emits_attachment_imports` touches
   it today, and that gate asserts the *generator emits* the block — not that the
   script's enumeration logic stays correct.

4. **No "reconcile-readiness" verb.** There is `tofu plan` (raw drift, exits 2 on
   any diff) and the daily drift Pulse job (`authentik-tofu-drift-base`, medium
   A9 on drift). Neither distinguishes the two operationally different drifts:
   (a) **benign drift** — a registry edit that adds/changes a service, expected,
   converges on the next apply; vs (b) **adopt-required drift** — the state does
   not know about live objects, so a converge would plan them as create/destroy.
   An operator staring at `Plan: 12 to add, 0 to change, 9 to destroy` cannot
   tell "I forgot to regenerate the registry" from "this tenant was never
   adopted" without hand-parsing JSON.

**The deliberate design decision — and the reason the filename is `no-auto-adopt`:**
adoption MUST stay **manual, supervised, dry-run-by-default**. Per the operator's
destructive-op safety doctrine (memory `feedback-destructive-op-safety`:
*dry-run default + explicit confirm gate, manual over auto-scheduled*), we do NOT
make the converge silently `tofu import` live objects into state. That would be a
live mutation of the OpenTofu state (and, on a wrong import id, of the tenant) on
an unattended overnight run — exactly the class of thing this branch is forbidden
from doing. **An auto-adopt is a footgun, not a feature.**

So the deliverable is NOT "make adopt automatic." It is:

1. A **read-only reconcile-readiness preflight** that runs (advisory, never
   failing) and classifies the current plan into *no-op* / *benign-converge-drift*
   / *adopt-required*, naming exactly which live objects are unknown to state, so
   the operator knows whether they need to run the adopt tool — surfaced calmly
   instead of via a mid-converge guard FAIL.
2. **Hardening + gating the adopt tool itself** so its import-id enumeration and
   coverage stay correct, and a half-finished adopt is detectable.
3. **A documented, discoverable reconcile runbook** so the manual path is a known
   ceremony, not tribal knowledge in two prose sentences.

This converts an undiscoverable, unpinned, surfaces-as-a-FAIL gap into an
explicit, test-pinned, operator-gated preflight — without ever crossing the
manual-over-auto line.

---

## 2. Exact files / roles to touch

### New: reconcile-readiness preflight (advisory, read-only)
- `tasks/tofu-authentik.yml` — add, **inside the existing drift-check block**,
  after the destroy-guard fact-computation (after `_tofu_bad_updates` is set,
  before the APPLY tasks), a **classifier + advisory debug** that NEVER fails:
  - Compute `_tofu_creates` (resource_changes with `change.actions` contains
    `create`) the same way `_tofu_destroys` is computed.
  - A plan is **adopt-required** when it would CREATE a provider/application/
    attachment whose `address` is in the registry-derived `for_each` keyspace —
    i.e. the registry already declares the service, but state has no instance, so
    tofu wants to create what is *already live in the tenant*. (Distinguish from
    "operator genuinely added a new service": that is benign — state correctly
    has no instance because the object does not exist live yet. The signal that
    separates them is whether the object exists **live**, which the plan JSON
    alone cannot tell us — see Risk #2 for how we resolve it without an extra API
    round-trip becoming load-bearing.)
  - Emit a single, calm `ansible.builtin.debug` advisory: `RECONCILE STATUS:
    no-op | converge-drift (N create / M change, applies cleanly) | ADOPT-REQUIRED
    (state missing K live objects: <addresses> — run tools/tofu-authentik-adopt.sh
    before flipping engine=tofu)`.
  - **This task must carry `failed_when: false` semantics — it is advisory ONLY.**
    The existing destroy guard remains the hard rail; the preflight is the
    *early-warning* that explains the guard before it fires.
- The preflight must run for **both engines** (it is a `debug`, harmless under
  `blueprint`), so the operator can check readiness *before* flipping the switch —
  remove the `engine=tofu` `when:` for the advisory (it stays on the destroy/apply
  tasks).

### New: adopt-script hardening
- `tools/tofu-authentik-adopt.sh` — three robustness fixes (see §3):
  - Add a `--check` / default dry-run posture banner reaffirming "import + plan
    only, never applies" (it already is read-only — make it loud).
  - Resolve `PORT` robustly: the current `grep '^authentik_port' default.config.yml`
    hard-codes the *default* port and ignores a `config.yml` override; read from
    `~/.nos/secrets.yml` / state if present, fall back to default. (The live
    tenant the operator is adopting may be on the overridden port.)
  - Emit a **coverage summary** at the end: count of live providers/apps vs count
    of import blocks written, and a non-zero-but-warn line if any live proxy/oauth2
    provider was skipped (e.g. a provider whose name has chars the slugifier
    dropped to an empty/colliding `adopt_` suffix). A silent skip is how an adopt
    "succeeds" but leaves objects unimported.

### New: reconcile runbook + state-consistency
- `docs/opentofu-authentik-cutover.md` — promote the "Adopt-path" archaeology
  bullet into a first-class **"Reconciling an existing tenant"** section: when
  you need it, the preflight signal, the exact `adopt.sh` ceremony, how to read
  `RECONCILE STATUS`, and the explicit statement that adopt is operator-only and
  never auto-run.
- `docs/active-work.md` — one-line pointer (respect the ≤150-line ceiling; if it
  is at the cap, fold an already-closed line out first — do NOT exceed it).

### New gates (mandatory — load-bearing deliverable)
- `tests/anatomy/test_tofu_reconcile_preflight.py` — NEW. Pins both the filter
  logic (if extracted) and the task wiring (advisory present, never-fails,
  classifier emits the three states). See §4.
- Extend `tests/anatomy/test_tofu_registry_bridge.py` OR a small new
  `test_tofu_adopt_tool.py` — pin the adopt script's import-id format + coverage
  banner (offline shell-parse / scripted-Python harness; no live tenant). See §4.

### Possibly extracted helper (keeps the task thin + testable)
- `filter_plugins/nos_tofu_guard.py` — if the create-classification needs more
  than a one-line `selectattr`, add a sibling pure-Python filter
  `nos_tofu_reconcile_status(resource_changes, registry_addresses)` returning
  `{status, missing: [...], creates: N, changes: M}`. Mirrors the existing
  `nos_tofu_immutable_field_updates` pattern (pure Python, normal play context,
  fully unit-testable). Prefer this over fragile inline Jinja.

### Do NOT touch
- The destroy guard, the immutable-field guard, the `-parallelism=1` apply, the
  registry generator's emit logic — all shipped + gated. The preflight reads the
  same `_tofu_changes` fact; it adds an advisory, it does not change the rails.

---

## 3. Approach (step order)

1. **Write the gates FIRST (red).** Author `test_tofu_reconcile_preflight.py`
   driving the classifier with synthetic plan JSON (no-op / converge-drift /
   adopt-required) + a task-wiring assertion. Author the adopt-tool gate. Both
   fail against today's tree (no preflight task, no coverage banner). This is the
   TDD ratchet.
2. **Add the classifier helper** (`nos_tofu_reconcile_status` in
   `nos_tofu_guard.py`) — pure Python, unit-tested by step 1's logic layer. Green
   the logic gate.
3. **Wire the advisory into `tasks/tofu-authentik.yml`** — `set_fact` →
   `debug`, `failed_when` absent (debug never fails), runs both engines, sits
   after the guard facts and before the apply. Green the wiring gate.
4. **Harden `adopt.sh`** — loud dry-run banner, robust port resolution, coverage
   summary. Green the adopt-tool gate.
5. **Document** — the reconcile section in the cutover doc + active-work pointer.
6. **Run the full anatomy suite + `--syntax-check`** (§6). Iterate to green.
7. **Commit** to `feat/v0.7-overnight` (Conventional Commit, surgeon tone). No push.

The change is **task-advisory + script-hardening + a new filter + new gates** —
**zero live mutation, zero new apply path.** The preflight is a `debug`; the
adopt tool stays import+plan-only. Nothing here runs unattended that mutates the
tenant or the state. Per machinery doctrine the behaviour takes effect only on
the next operator-run converge.

---

## 4. Gates it needs

All offline, fast, no Docker / no live tenant. Pattern mirrors
`test_tofu_destroy_guard.py` (logic layer driven by synthetic plan JSON + wiring
layer asserting the task computes-and-uses the fact).

### `tests/anatomy/test_tofu_reconcile_preflight.py`

**Logic layer** (drive `nos_tofu_reconcile_status` with synthetic plans):
- `test_no_op_plan_is_no_op` — empty `resource_changes` → `status == "no-op"`.
- `test_benign_converge_drift` — a CREATE whose address is NOT in the registry
  keyspace (operator added a genuinely-new service) → `status ==
  "converge-drift"`, `missing == []`.
- `test_adopt_required_when_registry_object_planned_as_create` — a CREATE whose
  address IS in the registry keyspace (state missing a live object) → `status ==
  "adopt-required"`, the address listed in `missing`.
- `test_destroy_only_is_not_adopt` — a DELETE-only plan is the destroy guard's
  job, classifier reports it but does not mislabel it adopt-required.

**Wiring layer** (offline parse of `tasks/tofu-authentik.yml`):
- `test_preflight_advisory_present_and_never_fails` — the advisory debug task
  exists, references `RECONCILE STATUS`, and carries NO `failed_when` that could
  abort (it must be a pure `debug`).
- `test_preflight_runs_both_engines` — the advisory's `when:` does NOT gate on
  `authentik_engine == 'tofu'` (so blueprint-engine operators can preflight
  before flipping).
- `test_destroy_guard_still_hard_fails` — REGRESSION: the existing
  `fail` on `_tofu_destroys > 0` is unchanged (preflight did not soften the rail).

### `tests/anatomy/test_tofu_adopt_tool.py` (or extend `test_tofu_registry_bridge.py`)
- `test_adopt_emits_attachment_import_id_format` — the script emits
  `<outpost_uuid>:<provider_pk>` for `authentik_outpost_provider_attachment`
  (pin the load-bearing import-id shape against a string/AST scan of the script).
- `test_adopt_resolves_port_from_state_not_just_default` — the port-resolution
  line reads `~/.nos/secrets.yml` / state with a default fallback, not ONLY the
  hard-coded `default.config.yml` grep.
- `test_adopt_emits_coverage_summary` — the script prints a live-vs-imported
  count line (the silent-skip detector).
- `test_adopt_never_applies` — REGRESSION: the script contains no `tofu apply`
  (grep-assert; the whole point is import+plan-only). Pins the no-auto-adopt
  invariant at the tool level.

Also keep green (regression): `test_tofu_destroy_guard.py`,
`test_tofu_registry_bridge.py`, `test_tofu_authentik_conformance.py`,
`test_tofu_engine_blueprint_noop.py`, `test_tofu_drift_pulse_job.py`,
`test_tofu_no_double_providers_on_forward_auth.py`,
`test_config_stock_jinja_only.py` (if any var touches `default.config.yml` —
none planned; the preflight uses task-scoped facts + a filter, no new config var).

---

## 5. Risks

1. **Over-engineering toward auto-adopt.** The temptation is to make the converge
   `tofu import` automatically. **Hard NO** — that is a live state (and on a wrong
   import id, tenant) mutation on an unattended run, violating both the branch
   rules and `feedback-destructive-op-safety`. The deliverable is an *advisory* +
   a *hardened manual tool*. The gate `test_adopt_never_applies` pins this.

2. **Classifier false positives — "adopt-required" vs "operator added a service."**
   Both look like a CREATE in the plan JSON. The honest discriminator is whether
   the object exists **live**, which the plan JSON alone does not carry. Two
   options, pick during implementation: (a) the classifier stays advisory and
   labels any registry-keyed CREATE as "possibly-adopt — verify live" (no extra
   API call, never wrong-in-a-dangerous-direction since it only ever *advises*);
   or (b) the preflight does ONE read-only API GET (`/providers/*`,
   `/core/applications/`) to confirm liveness — but that adds an API dependency to
   the advisory and can flake on a cold tenant. **Prefer (a)** — the advisory does
   not need to be precise, only loud and directionally right; precision lives in
   the operator running `adopt.sh --plan`. Document the imprecision in the debug
   message itself ("verify these are live before adopting").

3. **Advisory noise on every benign converge.** A normal registry edit produces
   `converge-drift` — we do NOT want the operator to learn to ignore the line.
   **Mitigation:** the advisory is a single line, only escalates wording to
   `ADOPT-REQUIRED` when a registry-keyed CREATE appears; a plain
   add/change/no-op stays terse. It is `debug`, not a notification — no A9 fanout
   (the existing daily drift Pulse job already owns the notification channel; do
   NOT duplicate it).

4. **Adopt-tool port resolution regression.** Changing the `PORT` grep could break
   the existing working path. **Mitigation:** keep the `default.config.yml` grep
   as the fallback; only prepend a state/secrets read. Gate
   `test_adopt_resolves_port_from_state_not_just_default` asserts both the new
   source and the fallback survive.

5. **`when:` removal on the advisory accidentally loosens the apply gate.** The
   advisory must run both engines, but the destroy/apply tasks must KEEP their
   `engine == 'tofu'` + `_tofu_destroys == 0` guards. **Mitigation:** the wiring
   gate `test_destroy_guard_still_hard_fails` is a regression pin on the apply
   gate; only the new debug task drops the engine `when:`.

6. **Filter-plugin load context.** `nos_tofu_reconcile_status` runs in normal play
   context (a `set_fact` in a task), NOT the `{{ vars }}` plugin-loader namespace,
   so a custom filter loads fine (same as `nos_tofu_immutable_field_updates`
   already does at line 134). No stock-Jinja-only constraint applies here.
   **Do NOT** reference the new filter from `default.config.yml`/`default.credentials.yml`
   (that namespace forbids custom filters).

7. **Adopt artifacts staying gitignored.** This plan does NOT un-gitignore
   `generated.tf` — adoption is per-tenant and those files are operator-local. The
   coverage banner + reconcile preflight are the durable, committed parts; the
   generated HCL stays a working-file the operator reviews then optionally commits.
   (Left as-is by design; called out so a reviewer does not flag it as an omission.)

---

## 6. Verification recipe (all read-only / offline)

```bash
cd /Users/pazny/projects/nOS

# 1. New gates + full anatomy suite green
python3 -m pytest tests/anatomy/test_tofu_reconcile_preflight.py -q
python3 -m pytest tests/anatomy/test_tofu_adopt_tool.py -q          # (or test_tofu_registry_bridge.py)
python3 -m pytest tests/anatomy/ -q

# 2. The whole tofu-guard family stays green (regression — rails unchanged)
python3 -m pytest tests/anatomy/ -q -k tofu

# 3. Stock-Jinja gate green (no new config var planned, but prove it)
python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py -q

# 4. Playbook still parses
ansible-playbook main.yml --syntax-check

# 5. Filter loads + classifier behaves (offline unit smoke):
python3 - <<'PY'
import importlib.util, pathlib
m = pathlib.Path("filter_plugins/nos_tofu_guard.py")
spec = importlib.util.spec_from_file_location("g", m); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
rc = lambda t, acts, addr: {"address": addr, "type": t, "change": {"actions": acts}}
plan = [rc("authentik_provider_oauth2", ["create"], "module.s[\"grafana\"].authentik_provider_oauth2.this")]
print(g.nos_tofu_reconcile_status(plan, registry_addresses={"module.s[\"grafana\"].authentik_provider_oauth2.this"}))
# expect status == "adopt-required", missing == [<that address>]
PY

# 6. Adopt tool is still import+plan-only (no apply ever):
grep -n "tofu apply" tools/tofu-authentik-adopt.sh && echo "FAIL: apply present" || echo "OK: import+plan only"

# 7. (Operator, optional, READ-ONLY live) run the preflight against the live
#    tenant WITHOUT applying — drift-check block is plan-only under blueprint:
#    ansible-playbook main.yml --tags tofu-authentik -e manage_authentik_with_tofu=true --check
#    → expect a single `RECONCILE STATUS: ...` advisory line, no apply, no FAIL.

# 8. (Operator, optional, READ-ONLY live) the adopt tool dry-run:
#    tools/tofu-authentik-adopt.sh --plan   # writes generated.tf + prints coverage summary; never applies
```

Expected end state: gate suite green, `--syntax-check` clean, a calm
`RECONCILE STATUS` advisory surfaces adopt-required drift BEFORE the destroy
guard would fire, the adopt tool prints a coverage summary + resolves the live
port + is gate-proven to never apply, and the reconcile ceremony is documented.
The destroy guard and immutable-field guard are untouched. No auto-adopt exists,
by design and by gate.

---

## 7. Definition of done

- [ ] `tests/anatomy/test_tofu_reconcile_preflight.py` lands; logic + wiring green.
- [ ] `nos_tofu_reconcile_status` filter added (pure Python, unit-tested), OR the
      classification proven trivially-inline if it really is a one-liner.
- [ ] `tasks/tofu-authentik.yml` carries the advisory `RECONCILE STATUS` debug
      (never-fails, both engines, after the guard facts, before apply).
- [ ] `tools/tofu-authentik-adopt.sh` hardened: loud dry-run banner, robust port
      resolution, coverage summary; gate-proven to never `tofu apply`.
- [ ] Destroy guard + immutable-field guard regression gates still green
      (rails unchanged — verified by `-k tofu`).
- [ ] Reconcile section added to `docs/opentofu-authentik-cutover.md`;
      `docs/active-work.md` pointer (≤150-line ceiling respected).
- [ ] `ansible-playbook main.yml --syntax-check` clean; full anatomy suite green.
- [ ] Commit on `feat/v0.7-overnight`, Conventional Commit, surgeon-tone body,
      no push. No live mutation anywhere in the change.

---

## LIVE ROOT-CAUSE & PROOF (2026-06-15) — the gap is WORSE than "existing tenant"

The wet-test validation runs proved this is not just an existing-tenant-migration
edge case — **the tofu state desyncs on EVERY non-blank converge**, so the steady-
state `tofu` engine is not idempotent across re-runs:

```
non-blank #1 (17:22) → guard REFUSE (18 immutable in-place flips)
blank        (17:54) → tofu apply PASSED (fresh DB+state, no-op)
non-blank #2 (18:39) → guard REFUSE again — same 18, deterministic shift
```

**Mechanism (proven, not theorised):**
- tofu tracks each provider by its Authentik **integer PK** (the resource `id`).
- Live providers get **recreated at new PKs during core-up** — proven:
  `nos-bookstack` moved PK **53 → 86**; its old PK 53 is now empty; the drift
  maps every service slug onto another entity's value (agent clients / other
  hosts) = a whole-table PK shift.
- tofu's state still holds the old PKs → refresh reads whatever now occupies
  them → "dangerous in-place client_id/external_host flip" → guard refuses
  (correctly — applying would rename 18 live providers and break SSO silently).
- **`10-oidc-apps.yaml` is NOT the churner** — its rendered form carries 0
  oauth2/proxy provider entries (only the embedded-outpost ref), so the
  "no-op render" cutover trap really is closed. **The exact step that recreates
  the providers during core-up is STILL OPEN** and is the first task of the
  durable fix (suspects: Authentik container recreate → blueprint re-bootstrap;
  the agent-clients blueprint apply; an outpost/RBAC blueprint).

**Stopgap shipped:** `tools/tofu-authentik-reconcile.sh` (commit `b365ca2f`)
re-imports every `module.service[*]` provider + proxy attachment + application at
its CURRENT live PK. Source of truth = **live `application.slug → application.provider`**
(applications import by slug, which never desyncs — this is the stable bridge a
durable fix should lean on). Verified: 40 services → `tofu plan -detailed-exitcode`=0.
It is a STOPGAP — a full converge re-churns and undoes it.

**Durable fix directions (pick during implementation):**
1. **Stop the churn** — find the core-up step that recreates providers and make it
   idempotent under `engine=tofu` (don't recreate tofu-owned objects).
2. **Track by stable key** — have the preflight auto-reconcile `module.service[*]`
   to the live PK via the `application.slug → provider` bridge *before* plan
   (essentially fold `tofu-authentik-reconcile.sh` into `tasks/tofu-authentik.yml`
   as a gated, dry-run-first preflight — exactly this plan's §-design, now with a
   working reference implementation).
- Validation that the fix works: blank, then **two** consecutive non-blank
  converges must both read `tofu plan` no-op (today the 2nd always refuses).
