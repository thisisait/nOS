# v0.7 plan — Tier-2 apps_runner: no gate for update semantics

> Status: **PLAN, not implemented.** Branch `feat/v0.7-overnight`.
> Scope: the Tier-2 `apps_runner` re-deploy ("update") path. The Tier-1 stack
> parallel is documented as a risk + follow-up, deliberately out of this plan's
> change set.

## Problem / why

The wet-test runbook
([`docs/tier2-wet-test-checklist.md`](../tier2-wet-test-checklist.md) §12,
lines 320-327) tells the operator that a manifest fix re-applied **without a
blank** converges in place:

> *"Re-run WITHOUT a blank … The runner re-renders + `docker compose up apps`
> brings the fixed container up without touching the healthy ones. Re-running
> `--tags apps` is safe — idempotent across the existing two pilots, only the
> broken one transitions state."*

That promise is **not enforced and, for a class of manifest changes, not
true.** The apps stack is brought up by a bare:

```yaml
# tasks/stacks/apps-up.yml — "[Apps] Start APPS stack (docker compose up -d)"
{{ docker_bin }} compose -f .../docker-compose.yml {{ overrides }} -p apps
  up -d --build --remove-orphans
```

There is **no `--force-recreate`**. Docker Compose recreates a container only
when its computed config hash diff is detected; a healthy container whose
override changed in a way Compose does not always hash into a recreate (env
value change, label change, command/healthcheck tweak, or an image-tag bump on
a tag that is **already pulled locally** so `--build`/pull is a no-op) can stay
**Up with stale config** while the runner's post-hooks
(`roles/pazny.apps_runner/tasks/post.yml`: service-registry append, Wing systems
ingest, Bone `app.deployed` event, GDPR `upsertProcessing`, smoke catalog)
record the deploy as **successful and current**. The state surfaces (Wing,
registry, GDPR Art-30 register) then assert a configuration the live container
does not actually run — a silent truthfulness gap, exactly the class Track W6
(Wing UI truthfulness) is closing elsewhere.

This is **not a hypothesis** — the upgrade engine already learned it the hard
way and guards against it. `files/anatomy/module_utils/nos_upgrade_actions/compose_ops.py`
(lines 178-183):

> *"`--force-recreate` + `--pull always`: a bare `up -d` sometimes leaves a
> healthy container untouched even after the override's image tag changed
> (observed: bookstack override bumped to v26.04.0 but the v26.03.3 container
> stayed Up, "ok" with drift). Be explicit."*

The upgrade-engine apply path is explicit (`--force-recreate` + a post-up
live-tag verify that turns silent drift into a loud failure). The **normal
Tier-2 converge path is not**, and nothing in `tests/anatomy/` pins the
converge-on-manifest-change behaviour. Per the standing rule (*every code fix
ships a pytest anatomy gate*), the gap is twofold: a **behaviour gap** (bare
`up -d` may not converge) and a **gate gap** (no test asserts the converge
contract). This plan closes both for Tier-2.

### Why scope to Tier-2 only (not Tier-1 core-up/stack-up)

The same bare `up -d --build --remove-orphans` (no `--force-recreate`) is used
in **all four** bring-up paths:

| File | Task | Command |
|---|---|---|
| `tasks/stacks/core-up.yml` (L426, L488) | infra + observability up | `up -d --build --remove-orphans` |
| `tasks/stacks/stack-up.yml` (L189 parallel, L261 sequential) | Tier-1 stacks up | `up -d --build --remove-orphans` |
| `tasks/stacks/apps-up.yml` | apps stack up | `up -d --build --remove-orphans` |

For **Tier-1** the drift is mitigated by the role-default version-pin doctrine
(a version bump changes the override image tag → Compose recreates on image
diff; pure-env churn is rarer and usually rides a handler/notify). Blanket
`--force-recreate` on Tier-1 would also **recreate ~50 healthy containers on
every routine `ansible-playbook main.yml` run** — a large, slow, churny
regression with real blast radius (stateful DB restarts, brief downtime, log
noise). That is its own design decision and deserves its own plan + a
cold-blank wet-test. **This plan deliberately does not touch Tier-1**; it adds a
documented risk note + a one-line follow-up pointer so the parallel is on the
record. Tier-2 is the right first cut: it is the path the runbook explicitly
promises in-place update for, the container count is tiny (the apps pilots),
and the override file is regenerated wholesale every run (`auto.yml`) so a
recreate is cheap and expected.

## Files / roles to touch

| File | Change |
|---|---|
| `tasks/stacks/apps-up.yml` | Add `--force-recreate` to the `[Apps] Start APPS stack` `up -d` command; add a post-up **converge-verify** task that fails loud when the live container config-hash still does not reflect the rendered override (mirrors `compose_ops.py`'s post-condition philosophy). Gate the force-recreate behind `apps_force_recreate` (default `true`) so an operator can opt out for a pure health re-poll. |
| `default.config.yml` | New var `apps_force_recreate: true` (stock-Jinja, real default — satisfies `test_config_stock_jinja_only.py`). Document it next to the existing `apps_*` toggles. |
| `roles/pazny.apps_runner/defaults/main.yml` | Mirror `apps_force_recreate` default (role-local fallback) — note: the **authoritative** default must live in `default.config.yml`, not only here (the version-pin-shadow / before-core-up-resolve trap; a role default alone does not load before the var is referenced in `apps-up.yml`). |
| `docs/tier2-wet-test-checklist.md` | §12 step 5: replace the "bare `up` is idempotent, only the broken one transitions" claim with the accurate contract (force-recreate converges the changed app in place; the converge-verify catches drift). Keep it honest — no overclaim. |
| `tests/anatomy/test_apps_runner_update_semantics.py` | **NEW gate** (see Gates). |
| `docs/active-work.md` | Add the Tier-1 `--force-recreate` parallel as a one-line follow-up under "Open follow-ups" (≤150-line ceiling — `test_active_work_slim.py`; trim only if needed). |
| `CLAUDE.md` "Recently shipped doctrine" | One-line pointer once shipped (do **not** add in this plan-only commit; this row is a reminder for the implementation commit). |

## Approach

1. **Force-recreate the apps stack up.** Change the `[Apps] Start APPS stack`
   command to:
   ```yaml
   up -d --build --remove-orphans {{ '--force-recreate' if (apps_force_recreate | default(true) | bool) else '' }}
   ```
   `--force-recreate` recreates every apps container from the freshly rendered
   `auto.yml` override regardless of Compose's hash heuristic, so any manifest
   change (image, env, label, command, healthcheck) takes effect on a
   `--tags apps` re-run. The apps container count is small and `auto.yml` is
   regenerated wholesale each run, so this is cheap. Keep `--remove-orphans`
   (drops a container whose manifest was deleted). Keep `--build` (Tier-2 can
   carry build contexts).

2. **Post-up converge-verify (read-only, fails loud).** After the health-wait,
   add a task that, for each rendered app's primary service, reads back the
   live container's effective image ref + the Compose config-hash label
   (`com.docker.compose.config-hash`) via `docker inspect` and compares the
   running image to the image the render emitted into `auto.yml`. Mismatch ⇒
   `fail` with the offending app id + expected/actual (same spirit as
   `compose_ops.py`'s `_verify_running_tags` post-condition — silent drift
   becomes a loud failure instead of a false "deployed"). Read-only on the live
   system (`docker inspect`); no mutation. Gate it on
   `apps_stack_result.rc == 0` so it only runs when the up succeeded.

3. **Idempotence honesty.** `--force-recreate` makes the up task inherently
   "changed" semantics, but the existing task already sets
   `changed_when: false` (the runner reports change via the health-wait +
   post-hooks, not the raw up). No idempotence-recap regression: the macOS
   `changed=0` re-run gate keys off real state, not this task. Confirm the
   `changed=0` story still holds in the verification recipe.

4. **Docs truthfulness.** Rewrite the §12 claim. The accurate statement:
   *"`--tags apps` force-recreates every apps container from the freshly
   rendered override, so a manifest change converges in place; the converge-
   verify step fails the run if any container still runs a stale image."* Drop
   the "only the broken one transitions state" sentence (false under
   force-recreate, and it was the source of the overclaim).

## Risks

- **Brief downtime on every `--tags apps` run.** Force-recreate restarts apps
  containers even when nothing changed. Mitigation: scoped to Tier-2 (tiny
  count), opt-out via `apps_force_recreate: false`, and Tier-2 apps are
  stateless-front / data-on-volume by manifest contract (DB volumes survive a
  recreate). Acceptable for the "I just changed a manifest, re-apply it" path
  the runbook is about.
- **Stateful Tier-2 apps with a DB sidecar** (e.g. a pilot's `_db`): recreate
  restarts the DB container too. Volumes persist, so data is safe, but there's
  a few-seconds connection blip. Documented in the §12 note. If this proves
  disruptive, a future refinement scopes force-recreate to non-`*_db` services
  via explicit service args — noted as a follow-up, not built now.
- **Converge-verify false positives** on multi-arch / digest-pinned images
  where the inspected `Image` is a sha256 digest but the override carries a tag.
  Mitigation: compare the **repo:tag** the override emitted against the
  container's `Config.Image` (the tag form Compose stores), and fall back to a
  digest-resolve only when the override itself is digest-pinned. Keep the verify
  **best-effort + loud**: on an inspect/parse error, warn (don't fail) so a
  Docker quirk never blocks an otherwise-good deploy — mirrors
  `compose_ops.py`'s "real runs only" guard.
- **Var trap.** `apps_force_recreate` is referenced in `apps-up.yml` which runs
  after core-up; its authoritative default **must** be in `default.config.yml`
  (a role default alone slips the before-core-up eager-resolve — the documented
  `app_secrets` failure mode). Pinned by the stock-Jinja gate.

## Gates it needs

New file `tests/anatomy/test_apps_runner_update_semantics.py` (offline, fast,
source-text + render assertions — no live Docker, consistent with the existing
`test_apps_runner_aggregator_cutover.py` / `test_app_wiring.py` style):

1. `test_apps_stackup_force_recreates` — `tasks/stacks/apps-up.yml`'s
   `[Apps] Start APPS stack` command contains `--force-recreate` (gated on
   `apps_force_recreate`), so a manifest change converges in place. **This is
   the gate that would have caught the bug.**
2. `test_apps_up_has_converge_verify` — apps-up.yml declares a post-up task
   that inspects the live container image and `fail`s on stale-image drift
   (asserts the task name + `docker inspect` + a `fail`/mismatch shape exist).
3. `test_apps_force_recreate_default_in_config` — `apps_force_recreate` is
   defined in `default.config.yml` with a real `true` default (not only in the
   role default), guarding the before-core-up resolve trap.
4. `test_force_recreate_opt_out_wired` — the command uses the
   `apps_force_recreate | default(true) | bool` conditional (opt-out path
   exists), so an operator can disable it for a pure health re-poll.
5. `test_runbook_no_stale_idempotence_overclaim` — `docs/tier2-wet-test-checklist.md`
   no longer contains the "only the broken one transitions state" overclaim
   string, and **does** mention force-recreate (docs truthfulness pinned).

Plus the standing suite stays green and `--syntax-check` clean:
- `python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py` (new var).
- `python3 -m pytest tests/anatomy/` (full anatomy suite).
- `ansible-playbook main.yml --syntax-check`.

## Verification recipe

```bash
# 0. Frozen-env nicety (matches CI integration); optional for offline gates.
#    tools/ci-local.sh

# 1. New + adjacent gates (offline, fast).
python3 -m pytest tests/anatomy/test_apps_runner_update_semantics.py \
                  tests/anatomy/test_apps_runner_aggregator_cutover.py \
                  tests/anatomy/test_config_stock_jinja_only.py \
                  tests/anatomy/test_active_work_slim.py -q

# 2. Full anatomy suite stays green.
python3 -m pytest tests/anatomy/ -q

# 3. Syntax clean.
ansible-playbook main.yml --syntax-check

# 4. (Operator, supervised — NOT overnight) live converge proof, read-mostly:
#    - edit an apps/<pilot>.yml env value (no image change),
#    - re-run the Tier-2 path:
#        ansible-playbook main.yml -K --tags apps,tier2,apps-runner
#    - confirm the live container picked up the new env (read-only):
#        docker inspect apps-<pilot>-1 --format '{{json .Config.Env}}' | tr ',' '\n' | grep <KEY>
#    - bare-up regression check: BEFORE the fix the same edit would leave the
#      container Up with the OLD env; AFTER, force-recreate converges it.
#    - re-run once more unchanged → confirm PLAY RECAP changed=0 (no churn).
```

## Acceptance

- [ ] `--force-recreate` wired into apps-up (behind `apps_force_recreate`).
- [ ] Post-up converge-verify fails loud on stale-image drift (read-only).
- [ ] `apps_force_recreate: true` in `default.config.yml` (+ role-default mirror).
- [ ] `docs/tier2-wet-test-checklist.md` §12 overclaim removed, contract honest.
- [ ] `tests/anatomy/test_apps_runner_update_semantics.py` (5 gates) green.
- [ ] Full anatomy suite green; `--syntax-check` clean.
- [ ] Tier-1 `--force-recreate` parallel logged as a one-line follow-up in
      `docs/active-work.md` (own plan + cold-blank wet-test required).
