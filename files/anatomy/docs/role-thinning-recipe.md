# Role-thinning recipe — deterministic 6-step process

> **Status:** v0.1, derived from Grafana A6.5 PoC inventory 2026-05-03.
> Subject to revision after the first 2-3 Q-batches reveal real patterns.
>
> **Audience:** any agent (human or claude) running a Track Q batch.
> Doctrine source: `docs/bones-and-wings-refactor.md` §1.1.

## When to use this recipe

You're migrating one Tier-1 role (`roles/pazny.<service>/`) to thin shape:

- **In:** today's role — defaults + tasks/main.yml + tasks/post.yml + templates/compose.yml.j2 + handlers + meta — possibly hundreds of lines, probably ~70% wiring.
- **Out:**
  - Thinned role — defaults + tasks/main.yml (data dir + compose render) + templates/compose.yml.j2 (ZERO cross-service env) + handlers + meta. ~50-150 lines.
  - New plugin — `files/anatomy/plugins/<service>-base/plugin.yml` + templates + provisioning files + tests. ~200-600 lines depending on wiring density.

The thinned role + plugin together produce **byte-identical functional behavior** to the unthinned role. If they don't, the recipe failed; revise before continuing.

## Pre-flight checklist

- [ ] `git status` clean
- [ ] Branch from `master`: `git switch -c feat/q-thin-<service>`
- [ ] Plugin loader (Phase A6) is operator-validated and live
- [ ] At least one prior thin-role pilot exists for reference (after A6.5: grafana-base)
- [ ] Last successful blank within 7 days (proves the unthinned role is green; otherwise you're chasing two bugs at once)

## The 6 steps

### Step 1: Inventory the wiring

Goal: enumerate every place the role's wiring leaks outside its directory.

```bash
SVC=<service-name>            # e.g. authentik
ROLE_DIR=roles/pazny.${SVC}

echo "=== Role internals ==="
find ${ROLE_DIR} -type f

echo "=== Wiring leak — top-level configs ==="
grep -rn "${SVC}" default.config.yml default.credentials.yml state/manifest.yml 2>/dev/null

echo "=== Wiring leak — global tasks ==="
grep -rln "${SVC}" tasks/ 2>/dev/null

echo "=== Wiring leak — files/ subtrees ==="
find files/ -path "*${SVC}*" -type f 2>/dev/null

echo "=== Wiring leak — other roles ==="
grep -rln "${SVC}" roles/ --exclude-dir=pazny.${SVC} 2>/dev/null | head -20

echo "=== Wiring leak — top-level templates ==="
grep -rln "${SVC}" templates/ 2>/dev/null
```

Capture the output to `files/anatomy/docs/${SVC}-wiring-inventory.md` (the
inventory IS a recipe deliverable). Categorize each hit as:

- **STAYS** (install-internal, role-only state)
- **MOVES to plugin** (cross-service wiring)
- **STAYS at top-level** (platform catalog, e.g. state/manifest.yml entries)
- **EDGE CASE** (needs operator decision — flag in inventory doc)

### Step 2: Draft the plugin manifest

Create `files/anatomy/plugins/${SVC}-base/plugin.yml`. Use
`grafana-base/plugin.yml` as the template. Required blocks for service plugins:

- `name`, `version`, `description`, `upstream`, `license`
- `type:` includes `service`
- `requires.role: pazny.${SVC}`
- `requires.feature_flag:` (whichever toggle gates the role)
- `requires.variables:` (every var the manifest's Jinja references)
- `authentik:` IF the service has OIDC (replaces default.config.yml entry)
- `compose_extension:` IF the role's compose.yml.j2 has cross-service env
- `provisioning:` IF the service has file-based provisioning
- `lifecycle:` declares hooks (pre_compose / post_compose / post_blank)
- `gdpr:` Article 30 row — MANDATORY (parser refuses without)
- `observability:` plugin-self-metrics (counter+gauge+histogram per the schema)

Optional blocks (use when relevant):
- `ui-extension.hub_card:` for Wing /hub deep-link
- `notification:` for plugin-emitted alerts
- `schema:` for wing.db tables the plugin owns

### Step 3: Move the files

Apply the inventory verdicts:

```bash
# Provisioning + dashboards + scrape configs MOVE
git mv files/observability/${SVC}/* files/anatomy/plugins/${SVC}-base/provisioning/
# (adjust paths per service)

# OIDC entries: cut from default.config.yml authentik_oidc_apps[],
# paste into plugin's authentik: block (already done in Step 2 conceptually,
# now physically remove from config)

# Compose env block (e.g. GF_AUTH_*): cut from role's compose.yml.j2,
# paste into plugin's templates/<svc>-base.compose.yml.j2

# tasks/post.yml: review case-by-case (EC2 in Grafana inventory)
#   - install-internal-state (admin password reset, schema bootstrap) → STAY in role
#   - cross-service API calls (POST OIDC config to service) → MOVE to plugin's lifecycle.post_compose
```

### Step 4: Strip the role

After moves, the role should be:

```
roles/pazny.${SVC}/
├── defaults/main.yml         # version, port, data_dir, mem_limit — install-internal only
├── handlers/main.yml         # restart handler
├── meta/main.yml
├── tasks/main.yml            # data dir + compose render — THE ONLY ACTION
├── tasks/post.yml            # OPTIONAL — only if install-internal post-step
└── templates/compose.yml.j2  # service definition with NO cross-service env
```

If the role still has more than this — it's not thinned.

Cross-check by `grep`:

```bash
# These should return ZERO matches in the thinned role:
grep -rn "GF_AUTH\|AUTHENTIK\|authentik_oidc\|grafana.com/api" roles/pazny.${SVC}/
grep -rn "include_role\|import_role" roles/pazny.${SVC}/  # except in your own tasks/main.yml meta
```

### Step 5: Smoke-test in isolation

**Before** running a full blank, verify the plugin manifest is valid and the
compose extension renders cleanly:

```bash
# Schema validation
python3 -m anatomy.scripts.validate_plugin files/anatomy/plugins/${SVC}-base/

# Render the compose extension to a tmpfile, diff against the OLD role's
# compose template's removed block — should be byte-equal modulo formatting:
ansible all -i localhost, -c local -m template \
  -a "src=files/anatomy/plugins/${SVC}-base/templates/${SVC}-base.compose.yml.j2 dest=/tmp/${SVC}-base-rendered.yml" \
  -e @default.config.yml -e @credentials.yml

git show HEAD~1:roles/pazny.${SVC}/templates/compose.yml.j2 \
  | extract-removed-block \
  | diff - /tmp/${SVC}-base-rendered.yml
# Expected: empty diff (or whitespace-only diff)
```

### Step 6: Wet-test parity (the real gate)

```bash
ansible-playbook main.yml -K -e blank=true
```

Expected after blank:

- Service comes up healthy (compose ps shows the container running)
- All wiring still works:
  - OIDC login round-trip succeeds
  - Dashboards visible (if Grafana-shaped service)
  - Datasources connect
  - Alerts fire on synthetic trigger
  - Cross-service deep links resolve
- `python3 tools/nos-smoke.py` shows green
- Wing /hub card for the service still appears
- `tail ~/.nos/events/playbook.jsonl | jq -c 'select(.type | startswith("plugin.${SVC}-base"))'` shows lifecycle events

If ANY of these red — the recipe failed for this service. Capture the failure
mode in the inventory doc as a new edge case; revise plugin manifest and retry.
**Do NOT merge a failed thinning** — better to skip the role this batch and
revisit than to leave a half-thinned role that future migrations have to special-case.

## Commit shape

One commit per role. Title:

```
feat(anatomy): thin pazny.<service> + extract <service>-base plugin (Q<N>)
```

Body:

```
Move all cross-service wiring from roles/pazny.<service>/ into
files/anatomy/plugins/<service>-base/. Role retains only install +
compose-render skeleton.

Inventory: files/anatomy/docs/<service>-wiring-inventory.md
Plugin: files/anatomy/plugins/<service>-base/plugin.yml
Edge cases: <count>, see inventory §"Edge cases discovered"

Verified byte-identical functional behavior on blank: <commit-of-blank-result>.

Per §1.1 doctrine, post-Q<N>: pazny.<service> defaults+tasks+template+meta only.
```

## Common pitfalls (catalog grows over time)

### P1: Forgetting `requires.variables`

Plugin's compose extension references `{{ tenant_domain }}` but plugin manifest
doesn't list it under `requires.variables`. Loader can't tell the plugin needs
that var. Render fails at lifecycle pre_compose. **Fix:** always grep your
manifest for `{{ ` and ensure every var is in `requires.variables`.

### P2: Compose-extension service name mismatch

Plugin extends `services.grafana:` but the role's compose template names the
service `services.grafana-oss:`. Docker Compose merges by key — silently
becomes a no-op AND a duplicate. **Fix:** always check `target_service` in
plugin matches the role's compose template.

### P3: Dashboards moved but provisioning provider not updated

Grafana's provisioning config points at `/var/lib/grafana/dashboards/` (in
container). Plugin moves dashboards to a new host path but doesn't update the
volume mount → Grafana sees empty dashboard dir. **Fix:** ensure plugin's
compose-extension also includes any volume mounts the wiring requires.

### P4: Authentik blueprint reconverge before plugin loader has registered the client

Plugin declares `authentik.client_id: nos-foo`. Authentik blueprint reconverge
(in `tasks/stacks/core-up.yml`) runs BEFORE plugin loader's pre-compose hook.
Result: blueprint fails because the client doesn't exist in plugin registry yet.
**Fix:** plugin loader's "register Authentik clients" step must run BEFORE the
blueprint reconverge — i.e. plugin loader's pre-compose hook is split into
"identity wiring" (runs before authentik blueprint apply) and "filesystem
wiring" (runs after). This is a **plugin loader implementation requirement**
and an A6 spec point.

### P5: Q1 batch regression — Alloy scrape gone

Q1 thins `pazny.alloy`. The OLD `templates/scrape-config.yml.j2` had hardcoded
`grafana:3000` scrape entry. After thinning, scrape config is loop over plugin
contributions — but `grafana-base` plugin (from A6.5) doesn't yet declare its
own scrape entry. Result: Grafana metrics gone. **Fix:** Q1 retroactively adds
`observability.scrape:` block to `grafana-base/plugin.yml`. Recipe step 6
catches this if smoke includes "Grafana shows up in Prometheus targets" check.

## Manifest fragment pattern (P0.5, 2026-05-04)

When 5+ workers create plugins in parallel worktrees, they all need to add a
row to `state/manifest.yml`. If they each commit a direct edit, the operator
faces 5+ merge conflicts on a single file. Use **manifest fragments** instead.

**Worker workflow** (this is what `scaffold-plugin.sh` produces by default):

1. Each plugin under `files/anatomy/plugins/<slug>/` ships a sibling file
   `manifest.fragment.yml` containing JUST the entry that should land in
   `state/manifest.yml`. Example (from a Q2 IAM plugin):

   ```yaml
   # state/manifest.yml fragment — operator merges in Phase 2 C2.
   - id: outline
     tier: 3
     feature_flag: install_outline
     domain_var: outline_domain
     port_var: outline_port
   ```

2. Workers NEVER edit `state/manifest.yml` directly. They commit only their
   fragment + plugin manifest + templates.

3. Operator (in Phase 2 C2 of the multi-agent batch) runs a single ordered
   commit that:
   - greps `files/anatomy/plugins/*/manifest.fragment.yml`
   - dedupes / reorders by tier
   - merges into `state/manifest.yml`
   - normalizes any slug mismatches (e.g. `home-assistant` vs `homeassistant`)

This way 10+ parallel PRs touch zero shared lines and Phase 2 C2 is one
commit, not 10 conflict resolutions.

**Forbidden writes for parallel workers** (operator-only in Phase 2):
- `default.config.yml` — central config (especially `authentik_oidc_apps`,
  deleted in Phase 2 C1)
- `state/manifest.yml` — see manifest fragment pattern above
- `tasks/stacks/core-up.yml` — plugin DAG ordering, registered in Phase 2 C3
- `files/anatomy/module_utils/load_plugins.py` — single file; loader changes
  serialize through Phase 0
- `files/anatomy/skills/contracts/*` — auto-generated by export scripts;
  never hand-edited. Regenerated in Phase 2 C4.

## Scaffolding helper (P0.5)

To produce a starting plugin in seconds and avoid 10 workers each inventing
their own shape:

```bash
files/anatomy/scripts/scaffold-plugin.sh \
    --name outline-base \
    --shape service \
    --sso oauth2 \
    --tier 3 \
    --target-stack b2b \
    --legal-basis contract
```

Generates:
- `files/anatomy/plugins/outline-base/plugin.yml` — manifest with TODOs
  marked clearly (description, license, variables, gdpr.data_categories,
  data_subjects)
- `files/anatomy/plugins/outline-base/manifest.fragment.yml` — entry for
  Phase 2 C2 merge
- `files/anatomy/plugins/outline-base/README.md` — placeholder

The scaffolded `plugin.yml` validates against `state/schema/plugin.schema.json`
out of the box. Worker fills in the TODOs, adds compose extension or
provisioning artifacts, runs `pytest tests/anatomy`, commits.

Supported shapes: `service` (Tier-1 docker), `composition` (cross-wires two
existing plugins), `skill` (scheduled-job). Supported SSO modes: `oauth2`,
`forward_auth`, `none`.

## Recipe versioning

This recipe is versioned independently of the plugins it produces. A breaking
change here (e.g. lifecycle hook rename) goes through a docs-RFC commit and
requires re-validating prior plugins against the new shape.

| Version | Date | Change |
|---|---|---|
| v0.1 | 2026-05-03 | Initial draft from Grafana A6.5 inventory |
| v0.2 | 2026-05-04 | + Manifest fragment pattern + scaffold-plugin.sh helper (P0.5) |
