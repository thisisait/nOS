# Handoff — next big parallel session

> **Status (refreshed 2026-05-16): SESSION COMPLETED.** The work scoped
> in this handoff has shipped:
> * **Track A (Q3–Q7 Tier-1 plugin refactor)** — DONE 2026-05-07.
>   Loader now discovers 63 plugins (12 new base manifests + D2 batch).
> * **Track B (AgentKit follow-ups)** — DONE.
> * **Track C (Phase 5 ceremony)** — IN-FLIGHT, awaits operator-driven run.
>
> See [`docs/active-work.md`](active-work.md) for the current pointer.
> This file is kept as the as-shipped record of the session's intent.

**Read this first. Then load `CLAUDE.md` and `docs/multi-agent-batch.md` before spawning workers.**

This document hands off the nOS roadmap to the next session. It assumes you (the next Claude) start fresh and need the full context to pick up cleanly. Date written: 2026-05-07 evening, after A14.2.

---

## Where we are

**Commit head:** `37384bd` (master, **26 commits ahead of origin/master**, push paused).

```
37384bd chore(security): A14.2 — defense-in-depth hardenings from review
4d4ca60 fix(security): A14.1 — close 2 HIGH from post-A14 security review
99659c0 feat(ait): A14 — AgentKit runtime (self-hosted, platform-agnostic)
b14af88 fix(security): A13.7 — RBAC gate + POST-only on privileged presenters
c318f48 feat(e2e): A13.6 — ephemeral SSO tester identity layer
70290de feat(e2e): A13.5 — 3 real journeys (plugin_contract, halt_resume, approval_flow)
1e87470 feat(alloy): A13.4 — scrape Wing /api/v1/metrics into Prometheus
b6e53eb feat(grafana): A13.3 — E2E Journeys dashboard provisioned
d2fc86a feat(wing): A13.2 — /api/v1/metrics Prometheus exposition
ac2a4d2 feat(e2e): A13.1 — telemetry foundation
... (16 more commits back to eac1892)
```

**Tests:** 113 anatomy gates green. Wing PHP lint clean.

**What landed in this session (top-down):**
- **A13.x** — full E2E journey suite (smoke, plugin_contract, halt_resume, approval_flow) + ephemeral SSO tester identity + Grafana E2E dashboard wired through Alloy.
- **A14** — AgentKit runtime (self-hosted, platform-agnostic agent runtime). Read `docs/ait-runtime-architecture.md` first; it's the canonical guide.
- **A13.7 / A14.1 / A14.2** — three security review rounds, all HIGH findings closed, defense-in-depth hardenings for sqlite3/proc_open env applied.

**Unblocked / waiting on operator:**
- Blank run was crashing because Docker Desktop's `~/.docker/cli-plugins/docker-compose` symlink pointed into `com.docker.install/in_progress/Docker.app/...` (mid-upgrade staging dir). Already fixed in this session — operator can re-run playbook or `--tags stacks`. Verify before assuming anything is live: `docker compose version` should return a number, not "unknown command".

**Ready to push but paused:** 26 commits to origin. Operator's choice when to push (next milestone gate).

---

## What this session should accomplish

Two parallel tracks. Pick whichever the operator scopes; ideally both.

### Track A — Tier-1 plugin refactor: Q3 / Q4 / Q5 / Q6 / Q7

Current state of the **Track Q autowiring** work:
- **Q1 + Q2 done** in earlier D-series (33 plugins shipped, central `authentik_oidc_apps` retired).
- **Q3 (Storage + DB)** — TODO. Targets: PostgreSQL, MariaDB, Redis, RustFS, Bluesky PDS storage, Infisical-storage. Most are Tier-1 substrates that other plugins depend on.
- **Q4 (Comms)** — TODO. Targets: ntfy, mailpit, FreePBX, Hermes, Bluesky PDS, Bluesky bridge.
- **Q5 (Content)** — TODO. Targets: Jellyfin, Kiwix, Calibre-Web, Tile-server, QGIS Server, Open WebUI, MCP Gateway, Outline, HedgeDoc, BookStack, WordPress, Nextcloud, Miniflux, Vaultwarden, Home Assistant.
- **Q6 (Dev/CI)** — TODO. Targets: Gitea, GitLab, Woodpecker, code-server, Paperclip.
- **Q7 (Misc)** — TODO. Targets: Uptime Kuma, Watchtower, Authentik (server + worker), Traefik, Portainer, OnlyOffice, Puter, Superset, Metabase, ERPNext, FreeScout, Firefly III, n8n, Node-RED, Mailpit, twofauth, OpenClaw, InfluxDB.

**Same plugin shape as Q2** (proven, no new architecture). Per plugin:
1. Create `files/anatomy/plugins/<name>-base/{plugin.yml, README.md}` mirroring an existing Q2 sibling (e.g., `files/anatomy/plugins/grafana-base/plugin.yml`).
2. Migrate the `authentik:` block from the legacy role's `authentik_oidc_apps` entry (if any).
3. Migrate the compose-template (or compose-extension fragment) into `files/anatomy/plugins/<name>-base/templates/<name>-base.compose.yml.j2`. Keep the role's existing template intact for now — both can coexist via the loader.
4. Drop the corresponding entry from `default.config.yml::authentik_oidc_apps` (if migrating). The list is already empty post-D1.3 except for the apps_runner stub; this step is mostly verification.
5. Run `tests/anatomy/test_native_oidc_no_authentik_middleware.py` + `tests/anatomy/test_plugin_loader.py` per touched plugin.
6. **No live verification per plugin** — wait for the batch-end syntax-check + a single `--tags <stack>` blank run.

**Verification recipe per plugin (worker autonomous):**
```bash
ansible-playbook main.yml --syntax-check --tags <plugin>
python3 -m pytest tests/anatomy/test_plugin_loader.py tests/anatomy/test_native_oidc_no_authentik_middleware.py
```

Both must pass before the worker commits.

**Parallelism:** spawn 5–8 workers (per `docs/multi-agent-batch.md` doctrine — never more than that until a 3-worker trial succeeds, and **mandate relative paths in the worker prompt** to avoid the cross-leak surfaced in the Phase 1 retro). Group plugins by quadrant (Q3 / Q4 / Q5 / Q6 / Q7), one worker per quadrant. Each worker handles ~3–5 plugins.

**Worker prompt template (use verbatim, paths relative):**

> You are working in a fresh git worktree. **Do not use absolute paths starting with `/Users/pazny/projects/nOS/...`** — the worktree is filesystem-isolated; any absolute reference to the parent breaks isolation. Use relative paths only (`files/anatomy/plugins/...`, `default.config.yml`).
>
> **CWD pre-flight:** before any file write, run `pwd` and confirm you're inside the worktree. If you're not, abort.
>
> Migrate <N> plugins (<list>) from the legacy role-only path to the AgentKit-era plugin base shape. Per plugin, mirror the structure of `files/anatomy/plugins/grafana-base/plugin.yml` (Q1 reference shape). The roles stay intact; the new plugin manifests are additive.
>
> Verify with: `ansible-playbook main.yml --syntax-check --tags <plugin>` + `python3 -m pytest tests/anatomy/test_plugin_loader.py`. Both must pass before commit.
>
> One commit per quadrant, message: `feat(plugins): Q<N> — <quadrant-name> base manifests`.

### Track B — AgentKit follow-ups

**Five items deferred from A14**, ranked by impact:

1. **Multi-agent process pool** (~3 days). Today `Coordinator` runs sub-agents sequentially. Next: spawn parallel processes (cap at `max_concurrent_threads`) with primary-thread event proxy. Mirrors Anthropic's full multi-agent surface. Touches `App\AgentKit\Coordinator` + `Runner` + new `agent_threads` query path. Anatomy gate: parallel sub-agent invocation produces ≥2 `agent_threads` rows with `parent_thread_uuid` set + spans nested under coordinator's trace.

2. **Operator-trigger UI** (~2 days). `POST /api/v1/agents/<name>/sessions` lands the runner via child process; UI polls `/api/v1/agent-sessions/<uuid>` for status. **MUST** derive `actor_id` from the validated bearer token's `name` field (`$this->getActorId()`); do **not** accept a client-supplied `actor_id`. The pattern is documented in `Api/AgentsPresenter.php`'s docblock.

3. **Vault refresh from Infisical** (~2 days). Wire `infisical:/path` secret_ref scheme. `App\AgentKit\Vault\CredentialResolver::dereference()` currently returns null for `infisical:` and logs to stderr. Connect to the Infisical CLI (already on the host per the playbook) and resolve at session-open time. Cache the resolved value for the session lifetime only — never write back.

4. **Dreams** (~3 days). Async memory-consolidation job. Reads recent `agent_sessions` + an existing memory store (new table `agent_memory_stores`), runs the agent against a "dreaming" tool roster + system prompt, produces a deduplicated output store. New CLI: `bin/dream-agent.php`. Same Runner + Telemetry path; no new abstractions.

5. **Per-agent webhook auto-fan-out** (~1 day). Agents declare a `subscribe:` block in `agent.yml` registering as a webhook receiver for events they care about. Enables event-driven loops (e.g., gitleaks-finding webhook triggers a remediation agent run). Touches `App\AgentKit\Webhook\WebhookDispatcher` + new dispatch-to-self path.

**Parallelism:** these are mostly independent; can run 2-3 in parallel with separate worktrees. (1) and (4) share `Runner.php` so coordinate.

### Track C — Phase 5 ceremony (the milestone)

After A or B (or alongside, if A finishes fast), the **first conductor self-test under claude identity** is the milestone gate. Operator-side checklist:

1. `ansible-playbook main.yml -K -e blank=true` — green.
2. `python3 tools/nos-smoke.py --tier 1 --tier 2` — green.
3. `php files/anatomy/wing/bin/run-agent.php --agent=conductor` — exits 0, conductor report rendered.
4. Verify in `wing.db`: 1 `agent_sessions` row, ≥3 `events` rows with `actor_id='agent:conductor'` and shared `actor_action_id`, conductor's report visible in `result_json`.
5. Tempo trace exists for the session's `trace_id`, with spans for `agent.session`, `llm.call.*`, `tool.use`, `grader.iteration`.
6. CI `contracts-drift` job — green.
7. Operator: `git push origin master` (~26+ commits since `eac1892`).

Required env for conductor:
- `ANTHROPIC_API_KEY` — set explicitly or via `~/.nos/secrets.yml::anthropic_api_key`
- `WING_API_TOKEN` — playbook writes this to `~/wing/.env` automatically
- `WING_EVENTS_HMAC_SECRET` — same as `bone_secret`, in launchd plist for daemon, in `~/.nos/secrets.yml` for CLI

Pass = first non-operator-identity end-to-end write to `wing.db`. Track P / Track Q / A-spine doctrine all proved at runtime.

---

## Critical context (read these before workers)

1. **`CLAUDE.md`** — full project doctrine. Pay attention to:
   - "Lockfile discipline" — composer.json ⇄ composer.lock always in sync; CI gate enforces.
   - The "Known Tech Debt" section ends at A14.2 — append your new entries here when you commit.
   - "Apple Silicon Constraints" — ARM64 only.

2. **`docs/multi-agent-batch.md`** — multi-agent batch doctrine pinned after the cross-leak retro. **Mandatory worker-prompt template** + relative-paths rule. **DO NOT skip this.**

3. **`docs/anatomy-runtime-flow.md`** — Bone/Wing/Pulse/Conductor data-flow diagram. Helps reason about which surface a fix touches.

4. **`docs/ait-runtime-architecture.md`** — AgentKit canonical architecture. 350 lines, dense, but the "How to add an agent / tool / LLM provider" sections at the bottom are exactly what Track B workers need.

5. **`docs/e2e-tester-identity.md`** — ephemeral SSO tester identity layer. Includes the `AUTHENTIK_API_TOKEN` bootstrap recipe (needed by anyone running the E2E suite live).

6. **`tests/anatomy/`** — 113 gates pin the contracts. Three are most relevant to the next session:
   - `test_security_agentkit_a141.py` — 8 tests pinning the security-review fixes. **Don't relax these.**
   - `test_security_presenter_gates.py` — 10 tests pinning the A13.7 RBAC + POST-only contract.
   - `test_agent_schema.py` + `test_agentkit_naming.py` — 14 tests pinning AgentKit conventions.

---

## Open / known issues to be aware of

1. **Docker Desktop mid-upgrade trap.** Twice this session a blank run failed with `docker compose: unknown command` because `~/.docker/cli-plugins/docker-compose` was symlinked to `com.docker.install/in_progress/Docker.app/...`. Always run `docker compose version` before assuming docker is healthy. Fix: `ln -sf /Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose ~/.docker/cli-plugins/docker-compose`.

2. **Authentik dev-instance flakiness.** Repeated test-run hammering can drive Authentik into 100s+ response latency. Give it 60–90s between back-to-back full E2E runs. Tracked in `docs/e2e-tester-identity.md`.

3. **GitLab is heavy** (3GB / 4GB cap, ~1.7% CPU stable). Operator may want `install_gitlab: false` for faster blank runs. Gitea handles 90% of CI use cases at 1/75 RAM.

4. **A13.6 incident (already fixed).** `sweep_orphans` once deleted 8 unrelated Authentik users because the API silently ignored an unknown filter. The fix: client-side prefix re-check at every dangerous call site, atexit handler refuses to call `sweep_orphans` (only operator CLI invokes it). **Anatomy gate `test_atexit_does_not_call_orphan_sweep` locks this — don't relax.**

5. **A14.1 incident (already fixed).** `BashReadOnlyTool` originally used `proc_open($command, ...)` (string form → `/bin/sh -c`), allowing `awk 'BEGIN{system("...")}'` payloads. Now array form + structured input + verb denylist + git/sqlite3 argv guards. **Anatomy gate `test_bash_tool_uses_array_form_proc_open` locks this — don't relax.**

---

## Spawning workers — checklist

When you're ready:

1. Pick the track (A or B) and the quadrants/items in scope for this session.
2. Read `docs/multi-agent-batch.md` end-to-end.
3. Decide how many workers (≤8; ≤5 until you have a 3-worker trial pass).
4. Write each worker's prompt using the template in §Track A or §Track B above. **Relative paths only.** **CWD pre-flight assertion in every prompt.**
5. Spawn all workers in a single `Agent` tool-call message (multiple tool_use blocks in one assistant turn).
6. As each worker reports, parse its `PR: <url>` line and update the status table.
7. After all workers complete, run the merge gate: `python3 -m pytest tests/anatomy/` + `ansible-playbook main.yml --syntax-check`. If green, merge sequentially.
8. Final commit message: `feat(plugins): batch <track-letter> — <N> plugins migrated` or analogous.
9. Update CLAUDE.md "Known Tech Debt" section with what's now done + what's still deferred.
10. Don't push — leave that for the operator's milestone gate.

---

## When in doubt

- **Check the anatomy tests first.** If you're tempted to "fix" something that an anatomy gate references, the gate is almost certainly right and your fix is almost certainly wrong.
- **Don't add hardening that isn't in scope.** If you find a bug while doing Q3 plugins, file it in CLAUDE.md tech-debt notes — don't tangle it into the plugin commits.
- **Conductor is the milestone, not a goal in itself.** Track A and Track B are independent; you can ship either and the conductor ceremony still works.
- **Push is operator's call.** When the work is green, summarize and stop.

Good luck. The plumbing is sound — A1–A14 prove it. Now it's just delivering the breadth.
