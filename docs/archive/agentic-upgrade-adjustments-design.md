# Agentic Upgrade / Migration / Coexistence — Adjustments Design (round 2)

> **Lead-architect synthesis.** Merges the three adjustment-round design proposals (AgentKit write tool + button, manual copy-data + undo B5, TTL + rollback) into ONE buildable spec. Charter: `feat/migration-author-agentkit` (off `dev`). **EXTEND the overnight B-build — do not rewrite.** Review-gated MR only (local GitLab forge), no live apply, read-only against the host. Source of truth for the four deviations: `docs/archive/agentic-upgrade-migration-coexistence-design.md` §7-RESOLVED (operator decisions, 2026-06-16).

---

## 1. Overview — what changes vs the overnight build

The overnight build (`feat/agentic-upgrade-coexistence` → `dev` `d37c5f9f`) shipped the §7 **defaults**: migration-author runs via the `pulse-run-agent.sh` CLI; the migration data-transform runs **implicitly at cutover/promote** (the "B5 hook"); the secondary cooling TTL is a hardcoded 7 days; the promote toggle is symmetric (typed-`PRIMARY` in both directions). §7-RESOLVED reverses four of those defaults. This round **extends** the built code with four deviations:

| # | Deviation (§7-RESOLVED) | Net effect |
|---|---|---|
| **A1** | **Q8** — AgentKit gets a **gated file-write tool** | A new `migration-file-write` tool, path-allowlisted to exactly `files/anatomy/migrations/` + `default.config.yml`, so a writing agent can run natively in AgentKit. |
| **A2** | **Q8** — **migration-author runs natively in AgentKit** (was CLI) | The agent runs through `Runner::run` → `agent_sessions`/`threads`/`iterations` + OTel → Grafana `22-ai-agents` + Tempo. The CLI wrapper survives as a fallback. |
| **A3** | **Q5** — Wing **"Promote to migration" button** → AgentKit | A Tier-1 `/upgrades` button fires the native AgentKit migration-author via the existing operator-trigger surface. |
| **A4** | **Q3** — **manual, re-runnable "Copy data" action**; UNDO the B5 auto-at-cutover hook | The migration data-transform leaves cutover/promote; a new explicit `copy_data` verb runs it on demand, idempotently. Flow becomes `provision(empty) → [Copy data] → [Promote primary]`. |
| **A5** | **Q4** — **TTL `[3,60]` default 7** + **one-click rollback** | A validated `coexistence_secondary_ttl_days` config var; the rollback (re-promote the prior primary) is one-click while the forward promote keeps the typed-`PRIMARY` confirm. |

**As-built, no change (§7-RESOLVED):** Q1 pull-via-`migration-pr.sh --mark-merged`, Q2 declarative `nos:migration:write` audit identity, Q6 all coexistence controls Tier-1 admin, Q7 pg16→17 only on the first run.

**Cross-cutting doctrine every deviation honors:** agent-driven (operator supervises, never auto-scheduled); audit lineage (`actor_action_id`/`coexist_svc`-keyed, actor never body-supplied); the **event-twin rule** (any NEW event type lands in `files/anatomy/bone/events.py` `VALID_TYPES` **and** `files/anatomy/wing/app/Model/EventRepository.php` `VALID_TYPES` in the **same commit**); stock-Jinja + real defaults (the `{{ vars }}` eager-resolve trap); manual-over-auto; destructive-op safety (dry-run default + explicit confirm); a pinning anatomy pytest gate per new contract; the **SECURITY gate on the AgentKit write tool**.

**Grounding verified against the built tree (2026-06-16):** `bash-write` is a *forbidden* token in `tests/anatomy/test_agentkit_dreams.py` (L91, L202) → A1 uses `migration-file-write`, never `bash-write`. The migration-author dir profile already declares `nos.migration.write` in `audit.capability_scopes`. The B5 blocks sit at `action_cutover` L860 and `action_promote_track` L995. TTL hardcode `7 * 24 * 3600` at `coexistence-promote.yml` L51 + `coexistence-cutover.yml` L111. `spawnRunner` is `private` in `Api\AgentsPresenter` (array-form proc_open, `--trigger=operator`, actor-from-bearer). The demotion branch (`elif t.get("tag") == previous:`) is at `action_promote_track` L1041. Event-twin parity is pinned by `tests/anatomy/test_devlog_event_types.py`.

---

## 2. A1 — AgentKit gated file-write tool (`MigrationWriteTool`)

### 2.0 The single security invariant (state it first, pin it everywhere)

> **The write tool writes only into the working tree. It commits nothing, merges nothing, runs no `--tags`, touches no live cluster.** The write surface is exactly two targets — a new migration YAML under `files/anatomy/migrations/` and `default.config.yml` — and nothing else is writable, ever. The same review-MR-then-operator-merge gate (GATE 2) that governed the CLI path governs the AgentKit path **unchanged**. AgentKit gains *visibility* (sessions/spans/dashboard), not *reach*.

Every part below is built to make that sentence structurally true (gate-enforced), not merely documented.

### 2.1 Id — `migration-file-write`, NOT `bash-write`

`tests/anatomy/test_agentkit_dreams.py` uses the literal `bash-write` as a **negative/forbidden token** (L91, L202 — it asserts the Dreamer's memory-consolidation output does not leak tool ids). Registering a real `bash-write` tool would tangle that gate, and the name advertises a general shell-write capability this tool deliberately does not have. **Decision: `migration-file-write`.**

- **Tool id:** `migration-file-write`.
- **Schema enum:** add `migration-file-write` to `state/schema/agent.schema.yaml` `tools[].id` enum (L70–74). Leave `bash-write` in the enum (reserved-but-unimplemented placeholder; removing it would churn the dreams gate and is out of scope). `tests/anatomy/test_agent_schema.py` validates the agent.yml against the enum automatically.

```yaml
# state/schema/agent.schema.yaml  tools[].id enum (L70)
- bash-read-only
- bash-write            # reserved placeholder, no impl (kept)
- migration-file-write  # NEW — gated, path-allowlisted (Q8/A1)
- mcp-wing
- mcp-bone
- mcp-pulse
```

### 2.2 Class — `files/anatomy/wing/app/AgentKit/Tools/MigrationWriteTool.php`

`final class MigrationWriteTool implements ToolInterface`, mirroring `BashReadOnlyTool`'s defensive structure (structured input, fail-soft, metadata-rich, no shell). The four interface methods:

- `id(): string` → `'migration-file-write'`.
- `requiredScopes(): array` → `['nos.migration.write']` (already in the migration-author profile's `audit.capability_scopes`, so `ToolRegistry::forAgent` will not throw the missing-scope `RuntimeException` at session start — that scope-gate *is* the structural admission control).
- `schema(): ToolSchema` → structured `{path, content}` (§2.3), never free-form.
- `execute(array $input, ToolContext $ctx): ToolResult` → the allowlist + escape-refusal gate (§2.4).

**Constructor — inject the repo working-tree root.** The migration dir and `default.config.yml` live in the **nOS playbook checkout**, NOT inside the deployed Wing tree (`~/wing/app/...`). Do NOT `getcwd()` (daemon cwd is unstable). Inject `string $repoRoot` via a new neon parameter `%nosRepoRoot%` whose value is `::getenv(NOS_REPO_ROOT)`; the Wing daemon plist + the flat migration-author Pulse env export `NOS_REPO_ROOT={{ playbook_dir }}`. If `$repoRoot` is empty or not a directory, `execute()` fail-softs (`ToolResult::error`, reason `repo_root`) so a missing config never silently writes to the wrong place.

```php
final class MigrationWriteTool implements ToolInterface
{
    private const MIGRATIONS_SUBDIR = 'files/anatomy/migrations';
    private const CONFIG_BASENAME   = 'default.config.yml';
    private const MAX_CONTENT_BYTES = 256 * 1024;     // 256 KiB cap
    private const MIGRATION_NAME_RE = '/^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*\.yml$/';
    private string $repoRoot;

    public function __construct(string $repoRoot) { $this->repoRoot = $repoRoot; }
    public function id(): string { return 'migration-file-write'; }
    public function requiredScopes(): array { return ['nos.migration.write']; }
    public function schema(): ToolSchema { /* §2.3 */ }
    public function execute(array $input, ToolContext $context): ToolResult { /* §2.4 */ }
}
```

### 2.3 Schema — structured `{path, content}`

`ToolSchema(name: 'migration_file_write', description: ..., inputSchema: ...)` with `inputSchema` = `object`, `required: [path, content]`:
- `path` (string) — repo-relative; either `files/anatomy/migrations/<YYYY-MM-DD>-<slug>.yml` OR `default.config.yml`.
- `content` (string) — full file content (tool creates/overwrites atomically); max 256 KiB.

The description names the two allowlisted targets and states "writes to the working tree only — commits nothing, makes nothing live; a human reviews + merges the MR." Structured input is the A14.1 invariant: there is no shell to smuggle; the path is validated against a regex + realpath containment, not a command string.

### 2.4 `execute()` — the escape-refusal gate (load-bearing security logic)

Each step returns `ToolResult::error(<msg>, ['refused_reason' => <r>, 'attempted_path' => $path])` fail-soft (so the LLM self-corrects); every refusal reason lands verbatim in the `agent_tool_result` audit event. Order:

1. **Type / null-byte / size guards** (copy `BashReadOnlyTool`'s null-byte check, ~L143): `path` and `content` non-empty strings; reject `\0` in `path`; reject `content` > `MAX_CONTENT_BYTES`. Reasons `size`.
2. **Repo-root sanity:** `$root = realpath($this->repoRoot)`; `false`/not-a-dir → reason `repo_root`.
3. **No absolute input:** reject `str_starts_with($path, '/')`. Reason `absolute`.
4. **No traversal:** split `$path` on `/`; reject any segment `=== '..'` or `=== '.'`. Reason `traversal`. (Belt-and-suspenders with realpath below; gives a clear LLM-facing error first.)
5. **Classify against the allowlist (exactly two arms):**
   - **Arm (b) config:** `$path === 'default.config.yml'` → `$target = $root . '/default.config.yml'`, `$arm = 'config'`.
   - **Arm (a) migration:** `$path` starts with `files/anatomy/migrations/` AND basename matches `MIGRATION_NAME_RE` AND depth is exactly one (`files/anatomy/migrations/<name>.yml`, no nested subdir) → `$target = $root . '/' . $path`, `$arm = 'migration'`.
   - **else → REFUSE**, reason `allowlist` (message names the exact two allowed targets).
6. **Realpath containment (symlink-escape refusal).** The file may not exist yet → canonicalise the **parent dir** (the `BashReadOnlyTool` realpath idiom applied to the parent):
   - `$parentReal = realpath(dirname($target))`; `false` → refuse (reason `symlink_escape`).
   - Config arm: require `$parentReal === $root`.
   - Migration arm: `$migrationsReal = realpath($root . '/' . self::MIGRATIONS_SUBDIR)`; require `$migrationsReal !== false`, that `$migrationsReal` is itself inside `$root` (`str_starts_with($migrationsReal . '/', $root . '/')`), and `$parentReal === $migrationsReal` (catches a symlinked `migrations` dir pointing outside the tree). Reason `symlink_escape` on any mismatch.
   - If the **target file already exists**, additionally `realpath($target)` and re-assert it sits under the same allowed parent (catches a pre-existing symlink *file* whose target is elsewhere).
7. **Atomic write:** write to `$target . '.tmp.' . bin2hex(random_bytes(6))`, then `rename()` into place (atomic on POSIX — no half-written YAML). Any `file_put_contents`/`rename` failure → fail-soft error.
8. **Success result + metadata:**
   ```php
   return new ToolResult(
       content: "wrote {$relPath} ({$bytes} bytes)",
       isError: false,
       metadata: ['path_written' => $relPath, 'bytes' => $bytes,
                  'arm' => $arm, 'created' => !$existedBefore],
   );
   ```
   **Never put `$content` into metadata** (audit-leak guard — the gate asserts `'content' => $content` does not appear). The `agent_tool_use` event already echoes the input (path+content) — acceptable here because the agent.yml declares `pii_classification: none` and migration records carry no secrets (a DB name at most).

### 2.5 DI registration — `files/anatomy/wing/app/config/common.neon`

Two edits mirroring `BashReadOnlyTool` (the `ToolRegistry` factory setup block + the per-tool service list):

```neon
parameters:
    # NEW: repo working-tree root for MigrationWriteTool. Env-overridden by the
    # Wing daemon plist / Pulse env (NOS_REPO_ROOT={{ playbook_dir }}). Empty → the
    # tool fail-softs (reason repo_root), never writes to the wrong place.
    nosRepoRoot: ::getenv(NOS_REPO_ROOT)

services:
    - factory: App\AgentKit\Tools\ToolRegistry
      setup:
        - register(@App\AgentKit\Tools\BashReadOnlyTool)
        - register(@App\AgentKit\Tools\McpWingTool)
        - register(@App\AgentKit\Tools\McpBoneTool)
        - register(@App\AgentKit\Tools\MigrationWriteTool)   # NEW

    - App\AgentKit\Tools\BashReadOnlyTool
    - App\AgentKit\Tools\McpWingTool
    - App\AgentKit\Tools\McpBoneTool
    - App\AgentKit\Tools\MigrationWriteTool(%nosRepoRoot%)   # NEW
```

`run-agent.php` already RobotLoads `app/` in both repo + deployed trees, so the new class autoloads with no further change. **Env wiring:** add `NOS_REPO_ROOT: "{{ playbook_dir }}"` to (a) the Wing daemon plist env block (`roles/pazny.wing/templates/wing.plist.j2`) so the native spawn path inherits it, and (b) `files/anatomy/agents/migration-author.yml` `pulse.jobs[].env` so the CLI fallback has it too.

### 2.6 Audit — no new event type (reuse the twins)

The write reuses the existing `agent_tool_use` (input echo) + `agent_tool_result` (metadata: `path_written`/`bytes`/`arm`/`refused_reason`) emitted by `Runner::runToolUseLoop`. Both are already in **both** `events.py` and `EventRepository.php` `VALID_TYPES` → Bone accepts the audit traffic without a 400. **No twin edit for the write tool itself.** `actor_action_id == sessionUuid` groups every write under one `SELECT WHERE actor_action_id=?`.

### 2.7 OTel — automatic

`Runner::runToolUseLoop` already wraps each `execute()` in a `tool.use` span (parent = `llm.call`), attaches `$toolResult->metadata` as span attributes, `setError` on failure. `path_written`/`refused_reason` become span attributes for free; spans batch-POST to Alloy `:4318` → Tempo. **No telemetry code change.**

### 2.8 Security gate — `tests/anatomy/test_security_agentkit_filewrite.py` (NEW)

Modeled on `tests/anatomy/test_security_agentkit_a141.py`: **static source inspection (regex), no PHP interpreter**, runs in CI without PHP. Asserts the structural invariants of `MigrationWriteTool.php`:

- `test_tool_id_is_migration_file_write` — `'migration-file-write'` present, `'bash-write'` absent.
- `test_requires_migration_write_scope` — `requiredScopes()` returns `'nos.migration.write'`.
- `test_allowlist_is_exactly_two_targets` — `files/anatomy/migrations` + `default.config.yml` named; no other writable dir (`/etc`, `roles/`, `templates/`) named.
- `test_rejects_traversal` — `'..'` segment refusal present.
- `test_rejects_absolute_input` — `str_starts_with(..., '/')` refusal present.
- `test_uses_realpath_containment` — `realpath` + `dirname(` (parent-dir idiom) present.
- `test_migration_filename_pattern_enforced` — the `\d{4}-\d{2}-\d{2}` regex present.
- `test_content_size_capped` — `MAX_CONTENT_BYTES` present.
- `test_no_shell_no_exec` — none of `proc_open`, `exec(`, `shell_exec`, `system(`, `passthru`, `popen` appear (a pure file write, never a process spawn).
- `test_fail_soft` — `ToolResult::error` present.
- `test_metadata_carries_path_and_refusal` — `path_written` + `refused_reason` present.
- `test_never_writes_content_into_metadata` — `'content' => $content` does **not** appear (audit-leak guard).

---

## 3. A2 — migration-author runs natively in AgentKit

### 3.1 `files/anatomy/agents/migration-author/agent.yml` — tool roster

Add the write tool to the dir-profile (the AgentKit-native one — the L284 "NOT bash-write" artifact that Q8 reverses). The scope is already present, so `forAgent` passes with **no scope edit**:

```yaml
tools:
  - id: bash-read-only       # cat/grep upgrades/<svc>.yml, _template.yml, migration.schema.json, state/manifest.yml
  - id: mcp-wing             # GET /api/v1/upgrades, POST /migrations/authored, POST /events
  - id: migration-file-write # NEW — write migration YAML + bump default.config.yml
```

`audit.capability_scopes` already covers `mcp.tool_use`, `wing.read`, `wing.write`, `events.write`, `nos.migration.write`, `audit.read` → the new tool's `requiredScopes() = ['nos.migration.write']` ⊆ that set. **No scope edit needed** (the overnight build provisioned the scope in anticipation — this is the clean unblock).

### 3.2 The MR-open mechanism — a controlled post-step, NOT a tool

`tools/migration-pr.sh` does `git switch`/`commit`/`push` + forge API calls — a git+network side effect that `BashReadOnlyTool` forbids and that must stay **outside** the AgentKit tool sandbox (the "AgentKit writes only the working tree" invariant). **Decision: the MR-open is a deterministic post-step the trigger layer performs after the session ends, not an LLM tool call.**

- The AgentKit-native agent's job is exactly: **author the migration YAML + bump `default.config.yml`** (both via `migration-file-write`), then **report** under `## Migration author report`.
- The Q5 button's server side (§4), after spawning the AgentKit session and polling it to terminal (the UI already polls `/api/v1/agent-sessions/<uuid>`), reads the session's `agent_tool_result` rows for a `path_written` under `files/anatomy/migrations/`, then fires `tools/migration-pr.sh <service> <migration-id> --open-pr` as a **separate Bone-scoped step** (operator-identity-scoped, not an agent tool). `migration-pr.sh` is dry-run-by-default; `--open-pr` is the explicit, deliberate flag and never merges/force-pushes.
- **Skip-on-empty:** if the agent wrote no migration file (exit-0 "no recipe gap" path), there is no `path_written` migration metadata → the post-step is skipped → no empty MR.
- (Rejected alternative: a second gated `migration-forge-mr` tool that shells `migration-pr.sh` — reintroduces a shell-capable, network-reaching write surface inside AgentKit, exactly what the security model forbids.)

### 3.3 Validation moves to the MR-open post-step

`BashReadOnlyTool` forbids `python`/`python3` and has no `ansible-playbook` verb — the native agent **cannot** run `pytest tests/migrations/` or `--syntax-check` itself (the CLI `bypassPermissions` path could). Resolution: validation moves to `migration-pr.sh --open-pr`, which already "re-validates through the migration gates" and refuses to open the MR on failure. **Strictly safer** — the deterministic gate enforces validation, not the LLM remembering to run it.

### 3.4 `files/anatomy/agents/migration-author/system.md` — narrative update (extend, don't rewrite)

- Author/bump steps: replace `bypassPermissions`-filesystem-write prose with **"Use `migration_file_write` to write the migration YAML, then again for the updated `default.config.yml` (read current with `bash_read_only cat`, apply the `<service>_version` bump, write the full new content). The tool refuses any path outside `files/anatomy/migrations/` + `default.config.yml` — that refusal is by design."**
- Validate step: **"Validation runs in the MR-open post-step (pytest `tests/migrations/` + `ansible-playbook --syntax-check`); you do not run them yourself (the read-only tool forbids python/ansible)."**
- MR step: **"The MR is opened automatically by the trigger layer after your session ends, using the `path_written` from your write-tool calls. You have no forge/git tool; do not attempt to push."**
- Keep the exit-signal contract (`NOS_AGENT_EXIT: 0/1`), evidence discipline, and the `## Migration author report` output contract unchanged.

### 3.5 Lineage (the whole point of Q8)

Running through `Runner::run` automatically writes an `agent_sessions` row (`model_uri`, `trace_id`, `actor_id`, `trigger=operator`, token tallies, `result_json`) → visible in `/agents` + `/agents/migration-author/sessions/<uuid>`; emits `agent_session_start/end`, `agent_message`, `agent_tool_use`/`agent_tool_result`, `agent_grader_decision` (rubric present, `max_iterations: 3`); batch-POSTs OTel spans (`agent.session → agent.thread → llm.call → tool.use`) → Alloy `:4318` → Tempo. The **`22-ai-agents`** dashboard panels populate with **zero dashboard edits** (they query `agent_sessions` on the `wing_sqlite` datasource).

### 3.6 CLI fallback preserved

`tools/run-migration-author.sh` (→ `pulse-run-agent.sh` → `migration-pr.sh`) stays as the operator/CI fallback. The flat `migration-author.yml` profile (with the paused `promote-migration` Pulse job) is unchanged — flat = CLI runtime, dir = AgentKit runtime. **Both profiles coexist by design; delete neither.**

---

## 4. A3 — Wing "Promote to migration" button → AgentKit

### 4.1 The wire — reuse the built operator-trigger via a shared service

The cleanest wire reuses the existing AgentKit operator-trigger that `Api\AgentsPresenter::startSession` → `spawnRunner` implements (array-form proc_open, actor from bearer, 202 + poll_url). Since `spawnRunner` is `private`, **extract a shared service** `App\AgentKit\OperatorTrigger` (method `spawn(string $agent, string $actorId, ?string $prompt): array{session_uuid, pid}`) that BOTH `Api\AgentsPresenter::startSession` AND `UpgradesPresenter::actionPromoteToMigration` call — removing duplication and keeping the actor-from-identity guard in one audited place. The button does **not** need a new Bone route; the spawn is internal to the Wing daemon (which already runs the FrankenPHP process that spawns the runner). (Rejected alternative: button → JS fetch → new Bone route → Bone proc_opens `run-agent.php` — duplicates `spawnRunner` in Python and crosses a process boundary for no gain.)

**Actor identity:** the agent runs **AS ITSELF** — `actorId = 'nos-migration-author'` (its own Authentik client, `authentik_agent_clients[nos-migration-author]`, holding `nos:migration:write`). The operator who pressed the button is captured separately as `triggered_by` (in the prompt + the supervision event), never as the agent's `actor_id`. This matches the doctrine: the agent's audit identity is its scope; the operator is the supervisor.

### 4.2 Route — `files/anatomy/wing/app/Core/RouterFactory.php`

Add the browser route **before** the catch-all:

```php
// Promote a reviewed recipe → migration record (AgentKit migration-author).
// Tier-1; POST-only; spawns the native AgentKit session.
$router->addRoute('upgrades/<service>/<recipe>/promote-to-migration', 'Upgrades:promoteToMigration');
```

No new API route — the session is observed via the **existing** `/api/v1/agent-sessions/<uuid>` poll route.

### 4.3 Presenter — `UpgradesPresenter::actionPromoteToMigration`

Tier-1 inherited (`$minAccessTier = 1`, enforced in `BasePresenter::startup`). The action:
- `requirePostMethod()` (CSRF).
- `$plannedBy` from the `X-Authentik-Username` header (never body; default `'operator'`).
- **Guard** via a new `migrationGap($service, $recipe)` read helper — refuse with a flash if the recipe doesn't exist or the matrix shows no real gap (no empty session).
- Build `$prompt` injecting `NOS_MIGRATION_SERVICE=<service>`, `NOS_MIGRATION_RECIPE_ID=<recipe>`, `NOS_TRIGGERED_BY=<plannedBy>` (the flat profile already documents these env keys).
- `$res = $this->operatorTrigger->spawn(agent: 'migration-author', actorId: 'nos-migration-author', prompt: $prompt);`
- Audit the **operator's supervision action** (operator identity, NOT the agent's): emit `migration_promote_requested` (NEW event type, §4.5) with `actor_id => $plannedBy`, `result => {service, recipe_id, session_uuid, agent}`.
- Flash success with a link to `/agents/migration-author/sessions/<uuid>`; redirect to `Upgrades:service`.

### 4.4 Template — the button in `service.latte`

On each recipe card the matrix marks as an available gap, add a Tier-1 button reusing the existing hidden-CSRF-form + `data-action` pattern (the plan-choice modal already does this). `data-action="promote-to-migration"`, `data-service`, `data-recipe-id`; `onclick="return confirm('Promote <svc>/<recipe> to a migration record? This starts the migration-author agent (writes a migration YAML + version bump, opens a review MR). Nothing goes live.')"`. The `window.confirm` is the lightweight supervision gate — appropriate because this is **non-destructive** (working-tree write + MR, makes nothing live); a typed-`PRIMARY`-style modal is overkill. The button renders only for available recipes; the `$drafts` Proposals strip already on `service.latte` then surfaces the resulting MR link once the agent finishes (closing the loop visibly).

### 4.5 Event twin — `migration_promote_requested` (NEW, both files, one commit)

The operator's button press deserves its own audit type, distinct from the agent's tool events. Add `migration_promote_requested` to **both** twins in one commit:
- `files/anatomy/bone/events.py` `VALID_TYPES`
- `files/anatomy/wing/app/Model/EventRepository.php` `VALID_TYPES`

(The agent's own `agent_tool_*`/`agent_session_*` are already in both — no further twin edits.) Extend `tests/anatomy/test_devlog_event_types.py` to assert this type is in both sets.

---

## 5. A4 — manual re-runnable "Copy data" action + UNDO the B5 auto hook

### 5.0 The reversal in one sentence

B5 wired the migration's `pg_dumpall` data-transform to run **implicitly, fail-closed, inside `action_cutover`/`action_promote_track` right before the pointer flip**. Q3 rips that out (cutover/promote become dumb pointer flips) and adds a **new first-class `copy_data` verb** that runs the *same* `nos_migrate action=apply migration_id=<source_migration_id>` data-transform against the secondary's empty cluster, **idempotently and on operator demand**. The engine path (`_resolve_migrate_apply` → engine `apply`) is **kept and repurposed** — only its call site moves from "inside promote/cutover" to "inside copy_data". The invariant Q3 buys back: **promote is now non-destructive and instantaneous** — it never silently runs a 12-minute Postgres dump mid-toggle. Freshness is the operator's call: re-run "Copy data" immediately before promote.

```
provision(empty)  →  [operator: Copy data]  →  [operator: Promote primary]
  source_migration_id   re-runnable; idempotent     pointer flip ONLY
  recorded              pg_dumpall → restore into    (no migration apply)
                        the SECONDARY's cluster      role flip, prior→secondary
                        stamps data_copied_at
```

### 5.1 PART 1 — UNDO the B5 auto-at-cutover hook

**`files/anatomy/library/nos_coexistence.py`:**
- `action_cutover` (L860 block): delete the B5 "consumes-migration" block (the `source_migration_id`/`already_applied` resolve, `_resolve_migrate_apply` call, tokens, `migrate_apply(...)`, fail-closed refusals). Keep the pointer-flip body. Keep one read of `source_migration_id` to echo it in `result` (so `test_cutover_without_migration_flips_cleanly` keeps asserting the key); drop the `migration` result key (or always `None`).
- `action_promote_track` (L995 block): identical surgery — delete the B5 block, keep the `now = _now_iso()` state-write body. Promote = lifecycle/health guards → flip `active_track` + stamp role/read_only/promoted_at/ttl_until → write vhost. Echo `source_migration_id`, never apply it.
- `migration_applied` param → **kept** in `argument_spec` + `DOCUMENTATION` (so live tasks passing it don't error), but **no longer read by cutover/promote**. It finds its single correct home in `copy_data` (§5.2) as the "the task already ran the apply, just stamp" short-circuit. Rewrite its `DOCUMENTATION` accordingly.
- `_resolve_migrate_apply` (L764) body **untouched** — only its caller relocates to `action_copy_data`.

**`tasks/coexistence-cutover.yml`:** delete the `list_tracks` read + target resolve + debug, the `nos_migrate action=apply` pre-run task (L76–99), the `migration_applied:` arg (L112–115), and the migration line in Summary. Cutover becomes a plain pointer flip + vhost regen + nginx reload. Rewrite the header comment to point at `coexistence-copy-data.yml` for the data move.

**`tasks/coexistence-promote.yml`:** drop any inert `migration_applied` reference; add a header note that promote is pointer-flip-only and the data move is `coexist-copy-data`. (The L51 `ttl_seconds` hardcode is A5's concern, §6.)

**`tasks/coexistence-apply.yml`:** **no change.** G-PROVISION-MIGRATED still blocks a `coexist` track from provisioning until its migration is merged (GATE 2, orthogonal to Q3); provision still records `source_migration_id` so `copy_data` can read it back. Q3 only relocates *when the recorded migration is consumed*.

### 5.2 PART 2 — ADD the `copy_data` verb (mirror promote/deactivate plumbing)

**Module — `action_copy_data` (the only consumer of `_resolve_migrate_apply` now):**
- Reads the track's `source_migration_id`, builds the coexist tokens (`coexist_service`, `coexist_tag`, `coexist_port`, `coexist_data_path`, `coexist_version`), and calls `_resolve_migrate_apply(ctx)` → runs `nos_migrate apply` against the **secondary** cluster.
- **Guards:** `G-COPY-HAS-MIGRATION` (refuse a track with no `source_migration_id` — an empty provision has nothing to copy); `G-COPY-NOT-PRIMARY` (refuse copying INTO the active primary — never dump into the cluster serving live traffic); `G-COPY-ENGINE` (fail closed if no engine reachable — same contract B5 enforced, re-used).
- **`migration_applied=true` short-circuit:** if the live task already ran `nos_migrate apply` (§5.3), skip the in-module `_resolve_migrate_apply` and just stamp `data_copied_at`. (The in-process `_resolve_migrate_apply` path stays for the offline unit tests, which have no real `nos_migrate` task.)
- No pointer flip, no vhost regen, no nginx reload. Stamps `data_copied_at` on the track.
- Wire into `choices`, `DOCUMENTATION`, `run_action` dispatch, `argument_spec`. Re-uses the existing `tag` param (no new arg).
- **Idempotency** lives in the migration recipe: `upgrades/postgresql.yml`'s `pg_dumpall` step has a `creates`-style guard + `--clean --if-exists` restore, so a re-run re-dumps from the advancing live primary and re-restores into the secondary without erroring — precisely the "run right before promote" requirement.

**Task — `tasks/coexistence-copy-data.yml` (NEW),** tagged `['coexist-copy-data', 'never']`, `dry_run` default `true`:
1. Assert inputs (`coexist_service`, `coexist_tag`).
2. `nos_coexistence action=list_tracks` → resolve the target track + its `source_migration_id`.
3. Assert the target carries `source_migration_id` (`| default('') | length > 0`).
4. `nos_migrate action=apply migration_id=<source_migration_id>` with the coexist tokens lifted from the **deleted cutover pre-run** (that code was correct, it just lived in the wrong place); `dry_run: "{{ coexist_dry_run | default(true) | bool }}"`; `failed_when` self-ref-safe.
5. `nos_coexistence action=copy_data migration_applied={{ not (coexist_dry_run|default(true)|bool) }}` to stamp `data_copied_at` (the module's short-circuit skips re-apply).
6. Summary debug ("re-run before Promote to capture latest data").

**`main.yml`:** import `tasks/coexistence-copy-data.yml` after the `coexist-deactivate` import (~L1006), `tags: ['coexist-copy-data', 'never']`.

**Bone:** `files/anatomy/bone/coexistence.py::copy_data(service, tag, dry_run=True)` mirroring `promote()`/`deactivate()` (validates, sets `coexist_*` extra-vars, `invoke_playbook("coexist-copy-data", extra)`). `files/anatomy/bone/main.py`: `POST /api/coexistence/{service}/copy-data/{tag}`, scope `nos:coexistence:write` (existing — no new scope), `dry_run` default `True`.

**Wing:**
- `CoexistenceRepository::copyData($service, $tag, $dryRun=true)` → `POST /api/coexistence/<svc>/copy-data/<tag>`.
- Browser `CoexistencePresenter::actionCopyData($service)` — Tier-1 (inherited), `requirePostMethod`, reads `tag` from POST, calls `copyData($service, $tag, false)`, flash + redirect (mirrors `actionDeactivateSecondary`). `window.confirm`, no typed phrase (non-destructive — writes only into the secondary).
- Api `CoexistencePresenter::actionCopyData($service)` — anti-spoof (`reject body actor_id`), `dry_run` default `true`, emits `coexistence_copy_data` only on a committed move (`dry_run=false` AND Bone 2xx).

**Routes — `RouterFactory.php`:** API `api/v1/coexistence/<service>/copy-data` (tag in body, uniform with `actionDeactivate`/`actionPromote` signatures), before the cancel/cleanup specifics; browser `coexistence/<service>/copy-data`, before the catch-all. (The Bone route keeps `/copy-data/{tag}` in the URL because the repo passes the tag there.)

**UI — `Coexistence/default.latte` + `widget-cutover-confirm.js`:**
- A **Copy data** button on each secondary/provisioned card (in `coex-track-actions`, placed **before** "Toggle as primary" so the flow reads copy→promote), gated on `!empty($track['source_migration_id']) && ($track['role'] ?? '') !== 'primary'`. Shows `data_copied_at` recency (or "no data yet"). `data-action="copy-data"`, `data-service`, `data-tag`.
- Hidden CSRF form `#coex-copy-form` (with `#coex-copy-tag`).
- `source_migration_id` + `data_copied_at` round-trip from state via Bone `list_tracks` (`row = dict(t)`) → no presenter reshape needed beyond passing `$svc['secondaries']`.
- `widget-cutover-confirm.js`: `onCopyData(btn)` — `window.confirm` (non-destructive into the empty secondary), set the hidden form action to `/coexistence/<svc>/copy-data`, submit. Add the `copy-data` delegation case. Update the header doc-comment.
- Sub-header copy: the lifecycle is **provision → Copy data → Toggle as primary**; "Copy data" runs the migration's data move into the secondary's cluster (re-runnable; run right before promote for freshness).

### 5.3 The audit event for the copy

`coexistence_copy_data`, source `wing`, `coexist_svc=<service>`, `actor_id` = forward-auth/bearer identity (never body — the API presenter rejects a body `actor_id`, same anti-spoof gate as promote/deactivate). Emitted **only on a committed move** (`dry_run=false` AND Bone 2xx), so a dry-run plan or a guard refusal leaves no false "copied" row. `result_json`: `{coexistence_service, tag, source_migration_id, data_copied_at}`. `SELECT … WHERE coexist_svc=? AND type='coexistence_copy_data'` reconstructs every re-run with timestamps — the lineage the buried-inside-cutover B5 move never produced.

### 5.4 Event twin — `coexistence_copy_data` (NEW, both files, one commit)

- `files/anatomy/bone/events.py` `VALID_TYPES` (after `coexistence_cancel`).
- `files/anatomy/wing/app/Model/EventRepository.php` `VALID_TYPES` (after `coexistence_cancel`) + doc-comment.

The `coexist_svc` FK col already exists; `EventRepository::insert` already maps `payload['coexistence_service'] → coexist_svc`. No `events` schema change. Extend `tests/anatomy/test_devlog_event_types.py` to assert `coexistence_copy_data` in both sets.

### 5.5 Gate — `tests/anatomy/test_coexistence_state_machine.py`

**Delete** the 6 B5 auto-apply tests (`test_cutover_runs_migration_before_pointer_flip`, `..._fails_closed_on_migration_error`, `..._refuses_when_no_migration_engine_reachable`, `..._migration_applied_flag_skips_inmodule_apply`, `test_promote_runs_migration_before_pointer_flip`, `..._fails_closed_on_migration_error`). **Add** the inverse no-apply assertions (`test_cutover_with_source_migration_does_NOT_apply_it`, `test_promote_with_source_migration_does_NOT_apply_it` — spy `migrate_apply`, assert `calls == []`, assert the flip still happened) + the `copy_data` section: runs-migration-into-secondary (tokens target the secondary cluster; `data_copied_at` stamped; no pointer flip), is-rerunnable (engine called twice, no flip, no error), refuses-without-source-migration, refuses-copy-into-primary, fails-closed-on-error (not stamped on failure), refuses-when-no-engine, migration_applied-flag-just-stamps (engine NOT called). Keep one-primary / deactivate / cancel / G-PROVISION-MIGRATED untouched. Update the module docstring (B5 bullet → copy_data bullet).

### 5.6 Doc reconciliation

`docs/archive/agentic-upgrade-migration-coexistence-design.md` §8 pg16→17 walkthrough: split "Toggle v17 primary — cutover RUNS the migration" into step 6 = **Copy data** (operator clicks → pg_dumpall into v17's cluster → `data_copied_at` → `coexistence_copy_data`; re-runnable) + step 7 = **Toggle v17 primary** (pure pointer flip, `coexistence_promote`). Renumber downstream. Add the §2.5 state-machine diagram node `COPY-DATA (re-runnable)` between PROVISION and PROMOTE.

---

## 6. A5 — TTL `[3,60]` default 7 + rollback one-click / forward typed-confirm

Two independent halves sharing one new state field. **Grounding (load-bearing):** `ttl_seconds` already threads `CoexistenceRepository::promote(...,$ttlSeconds)` → Bone `POST /promote/<tag>` (validates `int ≥ 0`) → `bone/coexistence.py` → `coexistence-promote.yml` L51 → `nos_coexistence.action_promote_track` L1046. **Every layer is plumbed; the value is just never produced.** So A5 is small: a config var + a clamp + the task-fallback swap + the JS confirm split + the rollback stamp. No new routes, no new Bone endpoint, no new module action.

### 6.1 Config var (bare literal — `{{ vars }}` trap-safe)

Add to `default.config.yml` in the lifecycle-tuning region (near `stack_up_*`):

```yaml
# Coexistence cooling TTL. When a track is promoted, the prior primary becomes a
# read-only secondary with this cooling window (the one-click-rollback window).
# VALIDATED to [3,60] days by tasks/coexistence-ttl-validate.yml (the clamp lives
# in a TASK, not here — a vars-file value must stay a bare literal per the
# {{ vars }} eager-resolve trap). Default 7.
coexistence_secondary_ttl_days: 7
```

A **bare `7`** — no filter, no expression — so it passes both `tests/anatomy/test_config_stock_jinja_only.py` gates (filter gate + every-ref-resolves-before-core-up gate): the key is defined in `default.config.yml` (resolves before core-up) and carries no filter.

### 6.2 Validation + derivation — `tasks/coexistence-ttl-validate.yml` (NEW)

A preflight assert (mirrors the weak-prefix assert at `main.yml` L1194) — runs **before** Bone spawns the playbook, gives a clear CLI error, and is offline-testable. **Stock-Jinja only** (`int` is a core builtin and is allowed; `bool`/`regex_*` are not):

```yaml
- name: "[coexistence_ttl] Validate coexistence_secondary_ttl_days is in [3, 60]"
  ansible.builtin.assert:
    that:
      - coexistence_secondary_ttl_days is defined
      - (coexistence_secondary_ttl_days | int) == coexistence_secondary_ttl_days
      - (coexistence_secondary_ttl_days | int) >= 3
      - (coexistence_secondary_ttl_days | int) <= 60
    fail_msg: >-
      coexistence_secondary_ttl_days must be an integer in [3, 60] days
      (got: {{ coexistence_secondary_ttl_days | default('<undefined>') }}). Set it in config.yml.
    quiet: true
  tags: ['always', 'coexistence', 'coexist-promote', 'coexist-cutover']

- name: "[coexistence_ttl] Derive the cooling TTL in seconds"
  ansible.builtin.set_fact:
    coexist_secondary_ttl_seconds: "{{ (coexistence_secondary_ttl_days | int) * 24 * 3600 }}"
  tags: ['always', 'coexistence', 'coexist-promote', 'coexist-cutover']
```

`(x|int) == x` is the integer-ness check (float `7.5` fails `7 != 7.5`; non-numeric string `int`s to `0 != "abc"`). `import_tasks` in `main.yml` just above the coexistence-apply import (~L990), `tags: ['always', ...]` so it also fires on a Bone-spawned `--tags coexist-promote` run.

### 6.3 Thread the derived seconds into the tasks

Replace the hardcoded literal at `coexistence-promote.yml` L51 + `coexistence-cutover.yml` L111:

```yaml
ttl_seconds: "{{ coexist_ttl_seconds | default(coexist_secondary_ttl_seconds | default(7 * 24 * 3600)) }}"
```

Precedence: explicit `coexist_ttl_seconds` extra-var (Bone, per-promote override) → `coexist_secondary_ttl_seconds` (config-derived) → `7*24*3600` literal (last-ditch if the validate task was skipped). Update both task docstrings ("default: 7" → "default: `coexistence_secondary_ttl_days` (config; [3,60], default 7)").

### 6.4 Surface to Wing — **no new config reader** (the elegant part)

Today `CoexistencePresenter::actionTogglePrimary` calls `promote($svc, $tag, false)` → `ttlSeconds=null` → body omits `ttl_seconds` → `coexist_ttl_seconds` extra-var unset → `coexistence-promote.yml` falls through to `coexist_secondary_ttl_seconds` (the config-derived value, produced by the `always`-tagged validate task). **So the configured TTL is applied with zero Wing change** — the validate task is the single source of truth and Bone's playbook invocation picks it up. Wing keeps passing `ttlSeconds=null`; the §6.3 task-fallback swap alone makes the whole stack honor the config var. (The `$ttlSeconds` param on `promote` stays for a future per-promote-override caller.)

### 6.5 Rollback signal — stamp `demoted_from_primary_at`

To let the UI know which secondary is the rollback target (the just-demoted known-good older version), the module stamps it explicitly (far more robust than inferring from version strings or `source_migration_id` absence). In `nos_coexistence.action_promote_track` (the demotion branch, L1041):

```python
        elif t.get("tag") == previous:
            t["role"] = "secondary"; t["lifecycle"] = "secondary"; t["read_only"] = True
            t["demoted_from_primary_at"] = now           # NEW — one-click-rollback signal
            until = datetime.datetime.now(tz=datetime.timezone.utc) + \
                datetime.timedelta(seconds=int(ttl_seconds or 7 * 24 * 3600))
            t["ttl_until"] = until.strftime("%Y-%m-%dT%H:%M:%SZ")
```

And **clear** it on the new-primary branch (L1031) so re-promoting drops the marker: `t.pop("demoted_from_primary_at", None)`. Because the demotion branch only matches `t["tag"] == previous` (exactly one active primary before the flip), **at most one track ever carries the stamp** — the "exactly one rollback target" property the UI relies on. (A dedicated field, not overloading `ttl_until`/`promoted_at`, keeps the "is rollback target" concern self-documenting and decoupled from the cleanup-TTL concern.)

### 6.6 Wing — surface the flag + split the buttons + one-click JS

- `CoexistencePresenter::renderDefault` — when pushing a track to `$secondaries`, set `$t['is_rollback_target'] = !empty($t['demoted_from_primary_at'])` (the field round-trips via Bone `/api/coexistence`).
- `Coexistence/default.latte` — split the secondary-card action: `{if !empty($track['is_rollback_target'])}` → a `data-action="rollback-primary"` one-click button (`↩ Roll back to <tag>`); `{else}` → the existing `data-action="toggle-primary"` typed-confirm button. **Both POST the same hidden `coex-toggle-form` to the same `/coexistence/<svc>/toggle-primary` route** — the only difference is the confirm UX. Update the sub-header to mention the asymmetry.
- `widget-cutover-confirm.js` — add `onRollback(btn)`: a single `window.confirm` (no typed phrase), set the shared `coex-toggle-form` action + `#coex-toggle-target-tag`, submit. Add the `rollback-primary` delegation case. **The forward path keeps the typed-`PRIMARY` modal (`TOGGLE_PHRASE`).**

**Design property:** rollback and forward hit the identical server endpoint (`actionTogglePrimary` → `promote($svc,$tag,false)`) — the asymmetry is **purely client-side confirm friction**, correctly inverted to match risk: forward promotes a *less-proven new* version (typed friction), rollback returns to *known-good* (fast escape hatch). If the prior primary is already primary again (race), the module's `G-PROMOTE-NOOP` returns `changed=False` — harmless, no new guard.

### 6.7 Gates (extend two existing, no new file)

- `tests/anatomy/test_coexistence_state_machine.py` (offline module driver): `test_ttl_validate_task_pins_3_to_60_inclusive` (parse `coexistence-ttl-validate.yml`; assert `>= 3` + `<= 60`; assert no `| bool`/`regex_` in the bound), `test_ttl_default_is_seven_and_a_bare_literal` (parse `default.config.yml`; `== 7`), `test_promote_stamps_demoted_prior_primary` (prior primary stamped, new primary not, exactly one stamped), `test_rollback_clears_stamp_on_re_promote` (re-promote clears + re-stamps the other; exactly one), `test_configured_ttl_applied_on_demotion` (pass `ttl_seconds=3d`; assert demoted `ttl_until` ≈ 3d, not 7d).
- `tests/anatomy/test_coexistence_presenter_tier1.py` (regex, no PHP exec): `test_presenter_flags_rollback_target` (`is_rollback_target` derived from `demoted_from_primary_at`), `test_template_splits_forward_and_rollback_controls` (`rollback-primary` + `toggle-primary` data-actions; branch on `is_rollback_target`), `test_rollback_is_one_click_forward_is_typed` (`onRollback` uses `window.confirm` + `coex-toggle-form`, NOT `TOGGLE_PHRASE`; forward keeps `const TOGGLE_PHRASE = 'PRIMARY'`; `rollback-primary` delegated).

---

## 7. Build order A1 → A5 (sequenced; each with its gate + files)

A1 is the prerequisite that unblocks A2 (write tool before native run); A3 depends on A2 (button fires the native agent). A4 and A5 are independent of A1–A3 and of each other, but A5 touches the demotion branch A4 leaves intact, so A4 before A5 avoids a merge collision in `action_promote_track`.

| Step | What | Key files | Gate |
|---|---|---|---|
| **A1.1** | Schema enum `+ migration-file-write` | `state/schema/agent.schema.yaml` | `test_agent_schema.py` (auto) |
| **A1.2** | `MigrationWriteTool.php` (id, schema, scope, allowlist + escape-refusal, atomic write, metadata) | `files/anatomy/wing/app/AgentKit/Tools/MigrationWriteTool.php` | **NEW** `test_security_agentkit_filewrite.py` |
| **A1.3** | DI register + `%nosRepoRoot%` param + service-list entry; env `NOS_REPO_ROOT={{ playbook_dir }}` in Wing plist + flat profile pulse env | `files/anatomy/wing/app/config/common.neon`, `roles/pazny.wing/templates/wing.plist.j2`, `files/anatomy/agents/migration-author.yml` | extend `test_agentkit_naming.py` (registration triangle: enum ↔ impl ↔ DI) |
| **A2.1** | `migration-author/agent.yml` `+ migration-file-write` (scope already present) | `files/anatomy/agents/migration-author/agent.yml` | `test_agent_schema.py` |
| **A2.2** | `system.md` narrative (tool-write, validation-in-post-step, MR-auto) | `files/anatomy/agents/migration-author/system.md` | (narrative; covered by A2.1 schema + A3 flow) |
| **A3.1** | Extract `OperatorTrigger::spawn` from `spawnRunner`; both call sites use it | `files/anatomy/wing/app/AgentKit/OperatorTrigger.php` (NEW), `files/anatomy/wing/app/Presenters/Api/AgentsPresenter.php` | (regression: existing AgentsPresenter tests) |
| **A3.2** | `UpgradesPresenter::actionPromoteToMigration` + `migrationGap()` helper + button in `service.latte` + browser route (before catch-all) | `files/anatomy/wing/app/Presenters/UpgradesPresenter.php`, `Templates/Upgrades/service.latte`, `Core/RouterFactory.php` | `test_security_presenter_gates.py` (Tier-1 inherited) |
| **A3.3** | Session-finish post-step fires `migration-pr.sh --open-pr` from `path_written` | (trigger wrapper / UpgradesPresenter poll), `tools/migration-pr.sh` (consumer, unchanged) | — |
| **A3.4** | Event twin `migration_promote_requested` (both files, one commit) | `files/anatomy/bone/events.py`, `files/anatomy/wing/app/Model/EventRepository.php` | extend `test_devlog_event_types.py` |
| **A4.1** | UNDO B5: strip blocks from `action_cutover`/`action_promote_track`; gut cutover-task pre-run; `migration_applied` doc → copy_data-only | `files/anatomy/library/nos_coexistence.py`, `tasks/coexistence-cutover.yml`, `tasks/coexistence-promote.yml` | `test_coexistence_state_machine.py` (delete 6, add 2 inverse) |
| **A4.2** | ADD `copy_data`: module action + `coexistence-copy-data.yml` + `main.yml` import + Bone wrapper/route + Wing repo/presenters/routes + UI button/JS | `nos_coexistence.py`, `tasks/coexistence-copy-data.yml` (NEW), `main.yml`, `bone/coexistence.py`, `bone/main.py`, `CoexistenceRepository.php`, `CoexistencePresenter.php`, `Api/CoexistencePresenter.php`, `RouterFactory.php`, `Coexistence/default.latte`, `widget-cutover-confirm.js` | `test_coexistence_state_machine.py` (7 copy_data tests) |
| **A4.3** | Event twin `coexistence_copy_data` (both files, one commit) | `files/anatomy/bone/events.py`, `EventRepository.php` | extend `test_devlog_event_types.py` |
| **A5.1** | Config var (bare `7`) + `coexistence-ttl-validate.yml` (clamp + derive) + `main.yml` import | `default.config.yml`, `tasks/coexistence-ttl-validate.yml` (NEW), `main.yml` | `test_config_stock_jinja_only.py` (auto) + `test_coexistence_state_machine.py` (bound + default) |
| **A5.2** | Task fallback swap (promote L51 + cutover L111) | `tasks/coexistence-promote.yml`, `tasks/coexistence-cutover.yml` | `test_coexistence_state_machine.py` (configured-TTL-applied) |
| **A5.3** | Stamp/clear `demoted_from_primary_at` in `action_promote_track` | `files/anatomy/library/nos_coexistence.py` | `test_coexistence_state_machine.py` (stamp/clear) |
| **A5.4** | Presenter flag + template split + one-click `onRollback` JS | `CoexistencePresenter.php`, `Coexistence/default.latte`, `widget-cutover-confirm.js` (+ `coexistence.css` cosmetic) | `test_coexistence_presenter_tier1.py` (flag + split + one-click-vs-typed) |
| **A6** | Doc reconciliation (§8 walkthrough split, §2.5 diagram) | `docs/archive/agentic-upgrade-migration-coexistence-design.md` | — |
| **A7** | Validate (read-only): `python3 -m pytest tests/anatomy/test_security_agentkit_filewrite.py test_agentkit_naming.py test_agent_schema.py test_coexistence_state_machine.py test_coexistence_presenter_tier1.py test_devlog_event_types.py test_config_stock_jinja_only.py`; `ansible-playbook main.yml --syntax-check`. **No `--tags`, no docker, no live run.** | — | — |

---

## 8. Risks / the security invariant

**The security invariant (restated, and it is the wall):** the AgentKit write tool makes **NOTHING live** — it writes only a migration YAML under `files/anatomy/migrations/` + a `default.config.yml` version bump into the working tree. The review MR (`tools/migration-pr.sh` → local GitLab forge) + operator merge (GATE 2) remains the boundary, **unchanged** from the CLI path. AgentKit gains visibility (sessions/spans/dashboard), not reach. This is pinned structurally by `test_security_agentkit_filewrite.py` (allowlist = exactly two targets; `..`/absolute/symlink escape refused; realpath-prefix containment; no `proc_open`/`exec`/`shell_exec`; requires `nos.migration.write`; never echoes `$content` into metadata).

**Per-deviation risks + mitigations:**

- **A1 path escape / symlink TOCTOU** — the parent-realpath idiom canonicalises *before* the write, and the atomic `tmp`+`rename` plus the pre-existing-file realpath re-check close the symlink window. Pinned by the security gate. Residual: a directory swapped between `realpath` and `rename` — out of scope for a single-operator host where only this daemon writes the tree; the MR+merge gate catches any anomalous file regardless.
- **A1 content audit-leak** — migration records carry no secrets (`pii_classification: none`); the gate forbids `$content` in metadata; `agent_tool_use` input echo is acceptable per the declared classification.
- **A2 native agent can't self-validate** — resolved by moving pytest/`--syntax-check` to the deterministic `migration-pr.sh --open-pr` post-step (stricter than the LLM remembering).
- **A3 actor-spoof** — the agent runs as `nos-migration-author` (its own scope), the operator captured as `triggered_by`; `OperatorTrigger::spawn` keeps the actor-from-identity guard in one place; the button is Tier-1 + CSRF.
- **A4 lost data move** — promote no longer copies data, so an operator who forgets "Copy data" promotes an empty/stale secondary. Mitigations: the UI flow orders copy→promote left-to-right; the secondary card shows `data_copied_at` recency ("no data yet"); the walkthrough + sub-header instruct re-running Copy data right before promote. (This is the **explicit Q3 trade**: manual control over implicit coupling — freshness becomes the operator's deliberate act.)
- **A4 copy into live primary** — `G-COPY-NOT-PRIMARY` refuses; pinned by `test_copy_data_refuses_copy_into_primary`.
- **A5 bad TTL** — the `[3,60]` preflight assert fails the run before anything mutates; pinned offline.
- **A5 one-click rollback misfire** — `window.confirm` is still a deliberate click; rollback only returns to the *known-good prior primary* (the lower-risk direction); `G-PROMOTE-NOOP` makes a double-click harmless.

**Charter compliance:** all output is code + this spec on `feat/migration-author-agentkit`; the new tasks are `never`-tagged (reached only via Bone or explicit `--tags`); no `--tags` run, no docker, no live `wing.db`/Postgres write performed; final delivery is the review MR to the local GitLab forge only. **EXTEND not rewrite** throughout: `_resolve_migrate_apply` body untouched (caller relocated), `copy_data` clones the promote/deactivate plumbing shape, `spawnRunner` is *extracted* (not reinvented) into `OperatorTrigger`, the TTL value flows through the existing `ttl_seconds` plumbing, the rollback reuses the existing toggle endpoint.

**One tension flagged for the build agent:** `migration_applied` is a B5 param that A4 PART 1 documents as "inert for cutover/promote" but A4 PART 2 *re-uses* for `copy_data`'s task-already-ran short-circuit. This is deliberate (the param finds its single correct home) — update its `DOCUMENTATION` to "consumed by copy_data, ignored by cutover/promote"; do NOT delete it (the live `coexistence-copy-data.yml` task passes `migration_applied:`).
