# Q3-Q7 plugin batch — multi-agent run prep

> **Status:** ready to launch. Pin `docs/multi-agent-batch.md` doctrine
> first. This file is the per-batch scope + worker prompt template +
> e2e recipe.
>
> Last updated: 2026-05-07 — after Phase 5 ceremony, A11 /approvals,
> U11-U13 alloy compositions all landed.

## Scope (what's actually left)

The original plan called Q3-Q7 "more of the same shape, no new
architecture". Phase 1+2 absorbed most of the surface; the residue today
is **11 plugin manifests across 5 roles** that still lack a base plugin:

| Quarter | Role(s) lacking a plugin | Priority | Shape |
|---|---|---|---|
| **Q3 Storage+DB** | `pazny.mariadb`, `pazny.postgresql`, `pazny.redis`, `pazny.rustfs` | P0 — every B2B/IIAB role transitively depends on these | service (Docker, native Authentik integration only for rustfs admin UI) |
| **Q4 Comms** | `pazny.smtp_stalwart` | P1 | service |
| **Q7 Misc** | `pazny.bluesky_pds`, `pazny.freepbx`, `pazny.mcp_gateway`, `pazny.offline_maps`, `pazny.qgis_server`, `pazny.watchtower` | P2 | mixed (bluesky_pds = service+OIDC bridge; freepbx = no SSO; qgis = no SSO; mcp_gateway = composition over openclaw+gateway) |

Out of scope for this batch:

- `pazny.acme` — TLS-cert helper, not a "service" by manifest definition
- `pazny.linux.*` — Linux-port roles (separate sprint per `docs/linux-port.md`)

**Total target:** 11 plugin manifests, ~5,500 LOC (incl. compose-extension
templates + GDPR rows + READMEs). Roughly 1.5× the size of the Q2 batch.

## Recommended grouping (per worker)

Each worker takes one Q-batch. Workers are independent — no cross-edits.
PRs target master sequentially.

| Worker | Plugins | Est. LOC | Critical files |
|---|---|---|---|
| **Q3-A** | mariadb-base, postgresql-base | ~1200 | `roles/pazny.{mariadb,postgresql}/templates/compose.yml.j2` (extract OIDC/Authentik admin-UI bits if any), new plugin manifests, GDPR Article 30 |
| **Q3-B** | redis-base, rustfs-base | ~900 | rustfs has admin UI — needs `authentik:` block (forward_auth) |
| **Q4** | smtp-stalwart-base | ~400 | new role's compose-extension; no SSO (operator-only ops surface) |
| **Q7-A** | bluesky-pds-base, mcp-gateway-base | ~800 | bluesky-pds is composition (depends on Authentik for the auto-account-bridge), mcp-gateway depends on openclaw |
| **Q7-B** | freepbx-base, qgis-server-base, offline-maps-base, watchtower-base | ~1200 | mostly pure-service shape, no Authentik (per CLAUDE.md "No SSO" services) |

5 workers, 11 plugins, 2-3 hours wall clock if launched in parallel.

## Per-worker prompt template

Copy the doctrine envelope from `docs/multi-agent-batch.md` then append
this body. Each worker gets the same envelope; only the GOAL section
changes.

```text
You are worker {WORKER-ID} in the nOS Q3-Q7 plugin batch. Plan:
docs/q3-q7-multi-agent-batch-prep.md (open this first).

WORKTREE — CRITICAL:
{copy verbatim from docs/multi-agent-batch.md "Worker-prompt doctrine"}

GOAL:
Create plugin manifests for these roles: {ROLE-LIST}. For each one:

1. Read the role's existing files:
   - roles/pazny.{role}/defaults/main.yml
   - roles/pazny.{role}/templates/compose.yml.j2
   - roles/pazny.{role}/tasks/main.yml + tasks/post.yml (if present)

2. Create plugin dir at files/anatomy/plugins/{slug}-base/ with:
   - plugin.yml — name/version/description, type:[service], requires:
     {role: pazny.{role}, feature_flag: install_{role}, variables: ...},
     authentik: block IF the service has app-level OIDC OR an admin
     dashboard that should sit behind forward-auth (see CLAUDE.md
     "SSO trichotomy"), gdpr: block (mandatory — refuses load otherwise).
   - manifest.fragment.yml — the row this plugin contributes to
     state/manifest.yml (domain_var, port_var, tier).
   - README.md — what it owns vs. what stays in the role; activation
     gate; verification recipe.

3. If the plugin has an `authentik:` block, create
   templates/{slug}-base.compose.yml.j2 — a compose-extension fragment
   that adds OIDC env vars or labels to the role's compose service.
   Pattern: see files/anatomy/plugins/outline-base/templates/.

4. If the plugin moves any post-API setup out of the role, create
   lifecycle/post_compose.yml — the API-call sequence the plugin loader
   will replay (see files/anatomy/plugins/portainer-base/ for the shape).

5. DO NOT modify state/manifest.yml, default.config.yml,
   default.credentials.yml, or tasks/stacks/core-up.yml. Operator merges
   manifest.fragment.yml entries in a serial Phase-2-equivalent pass.

VERIFICATION (run before declaring done):
- `python3 -c 'from files.anatomy.module_utils.nos_app_parser import *'`
  is NOT what we run here (that's Tier-2 apps). For Tier-1 plugins,
  schema compliance lives in state/schema/plugin.schema.json — verify
  with: `python3 -c "import json,yaml; print(json.dumps(yaml.safe_load(
  open('files/anatomy/plugins/{slug}-base/plugin.yml')), default=str))"`
  produces parseable JSON.
- `python3 tools/aggregator-dry-run.py` exits 0 (no field-diffs).
- `ansible-playbook main.yml --syntax-check` clean.

E2E (skip if not feasible in worktree):
- Full e2e requires the operator's running stack. Workers should NOT
  attempt `ansible-playbook main.yml` runs. Verify shape only.

REPORT (final message must end with):
   PR: <url>   (or `PR: none — <reason>`)
```

## E2E test recipe (operator-side after merge)

Per plugin landed:

```bash
# Sanity: aggregator + tests
python3 tools/aggregator-dry-run.py        # expect: exit 0
ansible-playbook main.yml --syntax-check   # expect: clean
pytest tests/anatomy -q                    # expect: 68/68

# Activation: full blank or targeted run
ansible-playbook main.yml -K --tags "stacks,authentik,anatomy.plugins"
# Or for a fresh deployment:
ansible-playbook main.yml -K -e blank=true

# Verify in Wing:
curl -sk -H "Host: auth.<tld>" -H "Authorization: Bearer <admin-token>" \
  https://127.0.0.1/api/v3/core/applications/?slug=<plugin-slug>
# → app exists if the plugin had an authentik: block

# Verify Traefik file-provider routing (Tier-1):
grep "<service>:" /Volumes/SSD1TB/traefik/conf.d/services.yml
```

## Pre-flight checklist (operator)

Before launching the batch:

- [ ] Push current 75+ commits to origin
- [ ] Confirm `docs/multi-agent-batch.md` worker-prompt doctrine is the
      latest (no patches since 2026-05-04 retro)
- [ ] Pause both Pulse jobs (`gitleaks:nightly-scan`,
      `conductor:self-test-001`) to avoid spam during the batch
      (they're already paused as of 2026-05-07 Variant A partial)
- [ ] Snapshot wing.db (`cp ~/wing/app/data/wing.db /tmp/wing-pre-q3.db`)
- [ ] Worktree count: `git worktree list` — start clean

After the batch:

- [ ] Per-PR verification (each worker reports `PR: <url>` — operator
      reviews, runs sandbox stack-up smoke for the touched plugin)
- [ ] Operator-serial Phase-2-equivalent: merge `manifest.fragment.yml`
      entries into `state/manifest.yml`, register plugins in
      `tasks/stacks/core-up.yml` if needed
- [ ] Aggregator dry-run + drift CI green
- [ ] Optional: blank run to validate full integration

## Risk register

| Risk | Mitigation |
|---|---|
| Worker writes to parent worktree (Phase 1 incident) | Mandatory CWD check in prompt envelope; throttle parallelism to ≤5 first batch |
| Database plugins (Q3-A) touch shared compose templates | Hand Q3-A to a single worker (no parallel Q3-A workers); review carefully |
| smtp_stalwart has no upstream Authentik integration | Plugin marks SSO=none in `authentik:` (or omits the block); operator wires alias-based access if needed |
| bluesky_pds plugin needs the AT Protocol bridge logic | Role already implements bridge; plugin only owns `authentik:` block + compose extension. Bridge logic stays in role. |

## What this batch unlocks

Once Q3-Q7 lands, the **plugin shape coverage is complete**: every
Tier-1 service in nOS has a plugin manifest. The Track-Q autowiring
debt note in CLAUDE.md flips from "Q1+Q2 complete; Q3-Q7 deferred" to
"all quarters complete — plugin authority is canonical".

Three structural follow-ups become unblocked:

1. **state/manifest.yml retirement.** Once every service's row lives in
   a `manifest.fragment.yml`, the central manifest becomes derivable.
   Aggregator gains `from: manifest_fragment` source.
2. **default.config.yml `install_*` flag retirement.** Every plugin
   already declares `requires.feature_flag`; a follow-up makes the flag
   default-off in the schema and removes the central list.
3. **`tasks/stacks/core-up.yml` plugin-loader-only path.** Today the
   stack orchestrator double-dips: it calls the plugin loader AND
   `include_role` for every service. Once plugins own all wiring,
   `include_role` calls become declarative (loader emits them).

Three structural debts paid down. Then the platform is "plugin-native"
end-to-end.
