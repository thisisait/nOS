# v0.7 SEC — Docker log-rotation inconsistency

Status: PLAN (not implemented). Target branch: `feat/v0.7-overnight`.
Owner: overnight agent batch. Scope: repo edits only, no live mutation.

## Problem / why

Every Tier-1 service role renders a Docker `logging:` block into
`roles/pazny.<svc>/templates/compose.yml.j2`. All 63 blocks (across 51 roles)
use `driver: "json-file"`, but the rotation knobs are **hardcoded literals with
no central default and no consistent value**:

| key       | observed values (count)                         |
|-----------|-------------------------------------------------|
| `max-size`| `"5m"` (1), `"10m"` (23), `"20m"` (38), `"50m"` (1) |
| `max-file`| `"2"` (1), `"3"` (23), `"5"` (39)               |

Why this matters for a security/compliance posture (the v0.7 SEC track):

1. **Unbounded-ish + non-deterministic disk retention.** A `10m × 3` service
   keeps ~30 MB of stdout/stderr; a `20m × 5` keeps ~100 MB; the `50m`
   (mcp_gateway) keeps up to 250 MB. On a cold blank with ~50 services the
   total json-file footprint is unpredictable and untunable as one number — an
   operator cannot answer "how much log disk does nOS hold?" or cap it.
2. **GDPR Art-5(1)(e) storage-limitation / retention story is incoherent.**
   nOS ships an Art-30 register and audit hash-chain, but container stdout
   (which can carry request paths, usernames, IPs) rotates on a *per-role
   whim*. A single auditable retention knob is the defensible shape.
3. **Drift magnet.** New roles copy whatever neighbor they cloned, so the
   spread widens every release. There is no gate pinning the convention, so it
   silently rots — exactly the failure mode `mem_limit`/`cpus` already solved.

This is the same class of issue the REM-006 mem/cpu sweep fixed: `mem_limit`
and `cpus` were unified onto central `docker_mem_limit_*` / `docker_cpus_*`
vars with a per-role override (`{{ <svc>_mem_limit | default(docker_mem_limit_standard) }}`).
The logging block is the one Docker-resource knob that **missed that sweep**.

### Explicitly out of scope (so the gate doesn't over-reach)

- **GitLab Omnibus internal logrotate** — `roles/pazny.gitlab/tasks/main.yml`
  sets `logging['svlogd_size']` / `logging['logrotate_frequency']` /
  `logging['logrotate_rotate']` inside the **container's** `GITLAB_OMNIBUS_CONFIG`.
  That is GitLab's *application-internal* log management, a different layer from
  the Docker `json-file` driver. **Leave it untouched.** The gate must not match
  `tasks/main.yml`.
- **Host-side log files** (Nginx/PHP/agent logs tailed by Alloy) — out of scope;
  this plan is strictly the Docker daemon `json-file` rotation driver.
- **Tier-2 apps_runner manifests** — `nos_apps_render.py` does **not** emit a
  `logging:` block today (verified: no `max-size`/`logging` in the render path
  or `apps/_template.yml`). Adding logging defaults to the Tier-2 render is a
  *separate, optional* follow-up noted at the end; this plan does not touch it
  (keeps the diff reviewable and the gate scoped to Tier-1 role templates).
- **Plugin compose-extensions** — none carry a `logging:` block today
  (verified). No change.

## Approach

Mirror the proven `docker_mem_limit_*` pattern exactly: one central default
tier, optional per-role override, and a pytest gate that pins the convention.

### 1. Central vars (`default.config.yml`)

Add a `Docker Logging` sub-block immediately under the existing
`Docker Resource Limits` block (around L259–267):

```yaml
# ── Docker Logging (json-file rotation) ───────────────────────────────────────
# Per-service stdout/stderr retention for the Docker json-file driver.
# Override per service: {service}_log_max_size / {service}_log_max_file
docker_log_max_size: "20m"        # per-file cap before rotation
docker_log_max_file: "5"          # rotated files kept (≈ max-size × max-file disk)
```

**Stock-Jinja trap compliance (NON-NEGOTIABLE):** both values are plain
quoted-string literals — no filters, no late-resolved refs. They are defined in
`default.config.yml` (loads before core-up), satisfying both variants of
`test_config_stock_jinja_only.py`. Keep them strings (`"5"`, not `5`) so the
rendered compose YAML matches Docker's expected string-typed option values and
the existing literals byte-for-byte where unchanged.

Value choice = the current **majority/dominant** values (`20m` / `5`) so the
sweep is the *least-surprising* convergence and most roles' rendered output is
unchanged or grows slightly (never shrinks retention silently for the common
case). The `10m/3` cohort grows to `20m/5` (more retention, safe); the outliers
collapse to the standard (see §3 for the two intentional carve-outs).

### 2. Per-role template edit (all 51 `compose.yml.j2`)

Replace every hardcoded block of the shape:

```jinja
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

with the override-aware form (using the role's own `<svc>_` prefix, matching
how `mem_limit` already reads `{{ <svc>_mem_limit | default(...) }}` in the
same file):

```jinja
    logging:
      driver: "json-file"
      options:
        max-size: "{{ <svc>_log_max_size | default(docker_log_max_size | default('20m')) }}"
        max-file: "{{ <svc>_log_max_file | default(docker_log_max_file | default('5')) }}"
```

The inner `| default('20m')` / `| default('5')` is belt-and-suspenders so a
role rendered in isolation (or a Tier-2 reuse) never throws on an undefined
central var — same defensive style as the `traefik_mem_limit | default(docker_mem_limit_standard | default('1g'))` line already in the tree.

Roles with **multiple** logging blocks (erpnext ×5, woodpecker ×2) get every
block converted; their per-service tuning, if any is wanted, uses distinct
prefixes (e.g. keep them all on the central default unless a specific service
needs more — see §3).

### 3. Two intentional carve-outs (preserve behavior, make it explicit)

These two roles deliberately diverge; keep the divergence but make it a named
override var, not a buried literal:

- **`pazny.gitlab`** (`50m`) — GitLab is the loudest container (cold-init spew).
  Render `{{ gitlab_log_max_size | default('50m') }}` /
  `{{ gitlab_log_max_file | default(docker_log_max_file | default('5')) }}`.
  Document `gitlab_log_max_size: "50m"` is intentional (heavy logger).
- **`pazny.mcp_gateway`** (`5m` / `2`) — tiny gateway, low-value chatter.
  Render `{{ mcp_gateway_log_max_size | default('5m') }}` /
  `{{ mcp_gateway_log_max_file | default('2') }}`.

The gate (§gates) treats these two as *allowed overrides* by asserting the
**template uses the override-var form**, not by asserting a specific literal —
so divergence is permitted only when it flows through a named, greppable var.

## Files to touch

- `default.config.yml` — add `docker_log_max_size` + `docker_log_max_file`
  (≈4 new lines under the Docker Resource Limits block).
- `roles/pazny.<svc>/templates/compose.yml.j2` — **51 files**, every
  `logging:` block converted to the override-aware form. Mechanical;
  the two carve-out roles (gitlab, mcp_gateway) keep their value as the
  override default.
- `tests/anatomy/test_docker_log_rotation_convention.py` — **new gate** (below).
- `docs/security-baseline.md` — one short paragraph: "Docker container
  stdout/stderr retention is centrally capped via `docker_log_max_size` ×
  `docker_log_max_file` (default 20m × 5 ≈ 100 MB/service); per-service
  overrides via `<svc>_log_max_*`." (Ties the knob to the compliance story.)
- (Optional, defer) `profiles/all-on.yml` / `profiles/gov-local.yml` — a
  tighter gov retention value could be set here later; **not** in this plan.

## Gates it needs

New file `tests/anatomy/test_docker_log_rotation_convention.py`, an **offline,
source-level** gate (no playbook run, no Docker), mirroring the glob style of
`test_each_autologin_plugin_renders_correct_env.py`:

1. **`test_central_log_vars_declared`** — `default.config.yml` declares
   `docker_log_max_size` and `docker_log_max_file` as quoted-string scalars
   (parse the YAML, assert presence + `isinstance(..., str)`).
2. **`test_every_logging_block_is_var_driven`** — for every
   `roles/pazny.*/templates/compose.yml.j2`, every `max-size:` / `max-file:`
   line inside a `logging:` block MUST be a `{{ ... }}` expression (regex:
   no bare-literal `max-size:\s*"\d+[mМk]"`). This is the anti-drift pin: a new
   role cannot reintroduce a hardcoded value.
3. **`test_override_form_references_central_default`** — each var-driven line
   chains to `docker_log_max_size` / `docker_log_max_file` **or** is one of the
   two whitelisted carve-out vars (`gitlab_log_max_*`, `mcp_gateway_log_max_*`).
   Pins the "divergence only through a named var" rule.
4. **`test_gitlab_omnibus_logrotate_untouched`** — assert
   `roles/pazny.gitlab/tasks/main.yml` still contains `logging['logrotate_rotate']`
   (guards the out-of-scope boundary — proves we didn't blast the GitLab
   internal logrotate while sweeping).
5. **`test_stock_jinja_only`** (covered by existing
   `test_config_stock_jinja_only.py`, not duplicated) — the two new vars use no
   non-stock filter. Run that existing gate as part of verification.

The suite must stay green and `ansible-playbook main.yml --syntax-check` must
pass (the var-driven `logging:` block is valid YAML/Jinja and renders to the
same string-typed options Docker expects).

## Risks

- **Retention *increases* for the `10m/3` cohort (23 roles → `20m/5`).** This
  raises per-service log disk from ~30 MB to ~100 MB. On a 50-service blank
  that's a few extra GB worst-case. **Mitigation:** it's a deliberate, single,
  tunable number now — an operator who wants the old footprint sets
  `docker_log_max_size: "10m"` / `docker_log_max_file: "3"` once. Document this
  trade in the commit body + security-baseline note. (We chose *up* to the
  majority `20m/5` rather than *down* to avoid silently shrinking retention for
  the 39 roles already at `5` files — shrinking retention is the riskier
  default for a security track.)
- **Type drift (string vs int).** Docker wants string option values. Keeping
  `max-file` as `"5"` (quoted) preserves byte-identical rendered output for the
  39 roles already at `"5"`. Gate #1 enforces string type to prevent an int
  sneaking in.
- **Idempotence churn.** Converting a literal to a var that resolves to the
  *same* value yields byte-identical rendered compose overrides → no container
  recreate for unchanged roles → no `changed=1` churn on the macOS idempotence
  re-run. The `10m/3` cohort's override file content *does* change → those
  containers recreate once on next converge (expected, one-time).
- **Eager-resolve `{{ vars }}` trap.** Because both vars live in
  `default.config.yml` (before core-up) and use stock `default()` only, they
  cannot trip the core-up loader eager-resolution trap. Verified by reusing
  `test_config_stock_jinja_only.py` (do not skip it in verification).
- **Mechanical-edit blast radius (51 files).** Risk of a typo'd prefix.
  Mitigation: gate #2/#3 fail loudly on any block that isn't the exact
  override form; run the full `--syntax-check` after the sweep.

## Verification recipe

```bash
# 0. On the right branch
git switch feat/v0.7-overnight

# 1. The new gate + the stock-Jinja gate (offline, fast)
python3 -m pytest tests/anatomy/test_docker_log_rotation_convention.py \
                  tests/anatomy/test_config_stock_jinja_only.py -q

# 2. Full anatomy suite stays green
python3 -m pytest tests/anatomy/ -q

# 3. Syntax-check clean (var-driven logging block renders)
ansible-playbook main.yml --syntax-check

# 4. Prove zero hardcoded rotation literals survive (should print nothing)
grep -rhnE 'max-(size|file):\s*"[0-9]' roles/pazny.*/templates/compose.yml.j2 || echo "OK: all var-driven"

# 5. Spot-render a sample override to confirm values resolve (READ-ONLY,
#    no compose up). Uses the sudo-free stacks helper in render-only mode —
#    do NOT run a bring-up; --skip-tags stacks keeps it render-only:
ansible-playbook main.yml --tags traefik --skip-tags stacks --syntax-check
#    then eyeball roles/.../overrides if a local render is wired, OR trust the
#    gate — the gate is the load-bearing contract.

# 6. Frozen 1:1 pre-release probe (optional, before any eventual release push)
tools/ci-local.sh
```

Acceptance: gates #1–#4 green, full suite green, syntax-check clean, step-4
grep prints nothing (or "OK"), no `changed=1` for roles whose value is
unchanged.

## Follow-ups (NOT this plan)

- Emit a `logging:` block from `nos_apps_render.py` so Tier-2 apps inherit the
  same `docker_log_max_*` cap (separate diff + its own gate).
- A `profiles/gov-local.yml` retention override if the gov track wants a
  tighter or longer auditable retention horizon (coordinate with the Art-5
  storage-limitation control).
