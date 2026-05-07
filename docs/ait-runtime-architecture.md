# AIT runtime — AgentKit architecture (Anatomy A14)

**TL;DR** — AIT (Agentic IT) is the user-facing concept; **AgentKit** is the implementation living under `files/anatomy/wing/app/AgentKit/`. It is a self-hosted, platform-agnostic, audit-first agent runtime. It borrows the Anthropic Managed Agents conceptual surface (agent / session / thread / outcome / vault / webhook) but every byte of state lives in `wing.db` so OpenClaw / future local LLMs swap in by changing one URI in `agent.yml`.

---

## Why AgentKit, not Anthropic Managed Agents

Anthropic Managed Agents is a **hosted** runtime — `POST /v1/agents`, `POST /v1/sessions`, all reasoning + audit lives in their cloud. Beautiful primitives, conflicts with two nOS constraints:

1. **Forward-compat for OpenClaw / local LLM**. Sessions running in Anthropic's cloud cannot transparently flip to a local model. The agent definition would need to be rewritten.
2. **Privacy / sovereignty**. The whole nOS doctrine is "every service FOSS, all data local". Cloud-resident agent state breaks that.

So we kept the Anthropic concepts (they're well-designed) and reimplemented them in PHP/SQLite. Read [docs/anatomy-runtime-flow.md](anatomy-runtime-flow.md) for how AgentKit slots into the bones-and-wings picture.

---

## Core abstractions

```
files/anatomy/wing/app/AgentKit/
├── Agent.php                       # parsed agent.yml (immutable value object)
├── AgentLoader.php                 # validates + loads agent.yml
├── Runner.php                      # one agent session end-to-end
├── Coordinator.php                 # multi-agent driver (thin wrapper today)
├── LLMClient/
│   ├── LLMClientInterface.php     # 2-method protocol: identifier(), send()
│   ├── AnthropicAdapter.php       # uses anthropic-ai/sdk (composer dep)
│   ├── OpenClawAdapter.php        # HTTP to OPENCLAW_BASE_URL
│   ├── Factory.php                # URI → adapter
│   └── {Message,ToolSchema,LLMResponse,LLM*Error}.php
├── Tools/
│   ├── ToolInterface.php
│   ├── ToolRegistry.php           # capability-scope check at session start
│   ├── BashReadOnlyTool.php       # whitelisted shell
│   ├── McpWingTool.php            # GET/POST against /api/v1/*
│   └── McpBoneTool.php            # GET against Bone /api/*
├── Outcome/
│   ├── Rubric.php                 # markdown loaded from rubric_path
│   └── Grader.php                 # SEPARATE LLM call → strict-JSON verdict
├── Telemetry/
│   ├── TraceContext.php           # W3C trace_id / span_id generation
│   ├── Span.php                   # OTLP-shaped span
│   ├── OtelExporter.php           # POSTs JSON spans to Alloy 4318
│   └── AuditEmitter.php           # writes to wing.db events table
├── Vault/
│   └── CredentialResolver.php     # secret_ref → plaintext at session-open
└── Webhook/
    └── WebhookDispatcher.php      # outbound HMAC-signed POSTs (Standard Webhooks v1)
```

### Storage shape (wing.db)

| Table | One row per | Purpose |
|---|---|---|
| `agent_sessions` | one agent invocation | trace_id, model_uri, status, tokens, outcome_result |
| `agent_threads` | one agent's view in a session | primary or child; carries span_id |
| `agent_iterations` | one grader call | result + feedback for outcome loop |
| `agent_vaults` | one credential bag | grouping, never plaintext |
| `agent_credentials` | one (vault, scope) pair | `secret_ref` is `env:NAME` or `infisical:/path` |
| `agent_subscriptions` | one outbound webhook receiver | enabled/auto-disable + signing_secret |

Plus 12 new event types in `events.type`: `agent_session_{start,end}`, `agent_thread_{start,end}`, `agent_iteration_{start,end}`, `agent_tool_{use,result}`, `agent_message`, `agent_grader_decision`, `agent_webhook_dispatch`, `agent_vault_resolved`. Every event carries `actor_action_id = agent_sessions.uuid`, so a single SELECT reconstructs the entire lineage.

### Three identity layers (kept distinct)

| Layer | Identifier | Where it lives |
|---|---|---|
| **Authentik client** | `agent:conductor` | external SSO realm, used as `actor_id` in events |
| **AgentKit session** | `agent_sessions.uuid` (also `actor_action_id`) | wing.db, used to group all events from one run |
| **W3C trace** | `agent_sessions.trace_id` (32-hex) | exported to Tempo via OTel, used to cross-link tools |

---

## URI scheme (platform-agnostic LLM backend)

`agent.yml::model.primary` is a single string of the form `<provider>-<model-id>`, dashes throughout:

```
anthropic-claude-opus-4-7
openclaw-qwen-coder-32b
local-llama3.1-70b-instruct
```

Pinned by:
- `state/schema/agent.schema.yaml` regex: `^(anthropic|openclaw|openai|local)-[a-z0-9.-]+$`
- `tests/anatomy/test_agent_schema.py::test_agent_yml_model_uri_pattern`
- `App\AgentKit\AgentLoader::isValidModelUri`

`Factory::fromUri` splits on the first dash and dispatches:
- `anthropic-*` → `AnthropicAdapter` (needs `ANTHROPIC_API_KEY`)
- `openclaw-*` → `OpenClawAdapter` (HTTP to `OPENCLAW_BASE_URL`)
- `openai-*` / `local-*` → reserved, throws

To swap backends: change one line in `agent.yml`. System prompt, tool roster, audit trail, OTel spans, grader logic — all stay identical.

---

## Tool-use loop

Anthropic's Messages API tool-use semantics are the de-facto industry standard; we mirror them:

```
1. Runner sends [system, user_messages, tools] to LLMClient::send()
2. LLMResponse comes back with content_blocks + stop_reason
3. If stop_reason != 'tool_use': end the loop
4. For each tool_use block: ToolRegistry → tool.execute(input, ToolContext) → ToolResult
5. Append tool_result blocks back to conversation as a user message
6. Loop (cap: 30 LLM calls per session iteration)
```

Tool retries:
- `LLMTransientError` (429/5xx/network) → backoff [1s, 4s, 12s] then fall back to `model.fallback` URI if defined, else `LLMPermanentError`.
- `LLMPermanentError` (4xx auth/bad-request) → fall back immediately if defined, else terminate session error.

Tool errors are surfaced to the LLM as `is_error=true` content blocks — the model self-corrects rather than crashing the session. Audit row records `is_error` so analytics can grep for tool flake.

---

## Outcome iteration loop

Borrowed from Anthropic Managed Agents' outcomes. Optional — declared by `agent.yml::outcomes.rubric_path`.

```
for iteration in 0..max_iterations:
  run tool-use loop until stop_reason=end_turn
  build markdown transcript of conversation
  Grader::grade(task, rubric, transcript) → separate LLM call with strict-JSON output
  if result == satisfied:    end session
  if result == failed:        end session
  if result == needs_revision: append grader.feedback as user message, loop
```

The **grader runs in an isolated context** — it sees the rubric + transcript but not the working agent's reasoning. This mirrors Anthropic's grader-isolation property; prevents the grader from being talked into "satisfied" by clever prose.

Strict-JSON output: format-failure budget of 2 retries. After exhaustion, iteration is `failed`.

---

## Audit + telemetry strategy

Every LLM call produces THREE artefacts:

1. **`events` row** — `agent_message` with `actor_action_id`, `trace_id`, text preview. The query/grep surface.
2. **OTel span** — `llm.call` with parent `agent.session`, exported to Tempo. The cross-tool view.
3. **`agent_sessions` token tallies** — token counts roll up per session. The cost/cap dashboard surface.

Every tool call adds one more event (`agent_tool_use` + `agent_tool_result`) plus one OTel `tool.use` span. Every grader iteration adds one `agent_grader_decision` event + `grader.iteration` span.

**Retrospective LLM review** (your "auditable by future LLM" requirement):

A future agent (Claude, OpenClaw, anyone) can replay:

```sql
-- All artefacts for one session
SELECT type, ts, result_json
FROM events
WHERE actor_action_id = '<session_uuid>'
ORDER BY ts ASC;

-- Plus the OTel trace
GET /grafana/explore?datasource=tempo&query=<trace_id>
```

…and produce a fresh judgement of whether the agent's decisions were correct, without re-running anything. **That's the whole point of the audit-first design.**

---

## Vault model

`CredentialResolver::resolve(scope)` walks:

1. If a vault is bound (via `--vault=<name>` in `bin/run-agent.php`), look up `agent_credentials` row matching scope. Decode `secret_ref`:
   - `env:VAR_NAME` → `getenv(VAR_NAME)`
   - `infisical:/path` → `InfisicalClient::fetch(path)` shells out to the operator's Infisical CLI (Track B U-B-Vault, 2026-05-07)
2. Fallback: env-var by deterministic name (`anthropic-api` → `ANTHROPIC_API_KEY`, etc.)
3. Otherwise null. Caller decides whether that's fatal.

Plaintext is **never** stored in `agent_credentials.secret_ref`. The column is a pointer.

**Infisical CLI invocation contract** (locked by `tests/anatomy/test_agentkit_infisical_vault.py`):
- Path is validated against `^/[A-Za-z0-9_/-]+$` BEFORE any subprocess. Bad paths reject with `null` and the error_log line does NOT echo the bad input (it could be attacker-controlled via Tier-2 manifests).
- `proc_open` uses the **array form** (`proc_open([$bin, "secrets", "get", $name, "--path", $parent, "--plain", "--silent"], ...)`) — string form delegates to `/bin/sh -c` (A14.1 RCE class) and is forbidden.
- `proc_open` env_vars allowlist: `PATH, HOME, LANG, LC_ALL, LC_CTYPE, TZ, PWD, TMPDIR, INFISICAL_TOKEN`. Nothing else — `ANTHROPIC_API_KEY`, `WING_API_TOKEN`, `BONE_SECRET`, `WING_EVENTS_HMAC_SECRET`, `OPENCLAW_API_KEY` are NEVER forwarded to the spawned CLI.
- Resolved values are cached at `CredentialResolver` instance level for the SESSION lifetime only. `bindVault(null)` drops the cache. The cache is `private array` (not `static`) so sessions get isolated caches. Never persists to disk.
- CLI not on `PATH`? `fetch()` returns `null` + logs once per process: "infisical CLI not on PATH; falling back to env". The caller (resolver) then walks the env-var fallback. Operators install via `brew install infisical/get-cli/infisical`; an `INFISICAL_BIN` env var overrides the Homebrew/usr-local probe order.

---

## Webhooks (outbound)

`WebhookDispatcher::fire(event_type, data)`:

1. Reads `agent_subscriptions` rows where `enabled=1` AND `event_types LIKE %<event_type>%`.
2. Builds Standard-Webhooks v1 envelope: `{type:'event', id, created_at, data}`.
3. For each subscriber: HMAC-SHA256 over `<timestamp>.<body>`, base64, prefix `v1,`.
4. POST with `X-Webhook-{Id,Timestamp,Signature}` headers.
5. Retries [200ms, 1s, 5s] within the dispatcher.
6. Auto-disable after 20 consecutive failures.

External tools that already speak Anthropic webhooks (or any Standard Webhooks consumer) understand AgentKit's outbound shape unchanged.

---

## How to use

### Run an agent from the CLI

```bash
cd files/anatomy/wing
ANTHROPIC_API_KEY=sk-ant-... \
  WING_API_TOKEN=$(grep wing_api_token ~/.nos/secrets.yml | cut -d'"' -f2) \
  WING_EVENTS_HMAC_SECRET=$(grep bone_secret ~/.nos/secrets.yml | cut -d'"' -f2) \
  php bin/run-agent.php --agent=conductor
```

Output (JSON) reports session_uuid + trace_id; full lineage in `wing.db` + Tempo.

### Trigger via Pulse

Edit the relevant Pulse job's `command:` to:
```yaml
command: "{{ playbook_dir }}/files/anatomy/wing/bin/run-agent.php"
runner: subprocess
env:
  NOS_AGENT_NAME: "conductor"
  ANTHROPIC_API_KEY: "{{ anthropic_api_key }}"
  WING_API_TOKEN: "{{ wing_api_token }}"
  WING_EVENTS_HMAC_SECRET: "{{ bone_secret }}"
```

(Today the existing `pulse-run-agent.sh` is preserved as legacy — operator flips conductor's pulse config when ready.)

### Add a new agent

```bash
mkdir -p files/anatomy/agents/<name>
cat > files/anatomy/agents/<name>/agent.yml <<EOF
name: <name>
version: 1
description: |
  <One-paragraph description.>
model:
  primary: anthropic-claude-opus-4-7
system_prompt_path: system.md
tools:
  - id: bash-read-only
audit:
  capability_scopes: [bash.read]
  pii_classification: none
EOF
$EDITOR files/anatomy/agents/<name>/system.md
python3 -m pytest tests/anatomy/test_agent_schema.py    # validate before commit
```

### Add a new tool

1. Implement `App\AgentKit\Tools\ToolInterface` in `app/AgentKit/Tools/<Name>Tool.php`.
2. Add `id: <new-id>` to `state/schema/agent.schema.yaml::properties.tools.items.properties.id.enum`.
3. Register in `app/config/common.neon` services + ToolRegistry setup block.
4. `python3 -m pytest tests/anatomy/test_agent_schema.py`.

### Add a new LLM provider

1. Implement `App\AgentKit\LLMClient\LLMClientInterface` in `app/AgentKit/LLMClient/<Name>Adapter.php`.
2. Add the `<provider>-` prefix to `state/schema/agent.schema.yaml`'s URI regex AND to `App\AgentKit\AgentLoader::isValidModelUri` AND to `App\AgentKit\LLMClient\Factory::fromUri`.
3. `python3 -m pytest tests/anatomy/test_agentkit_naming.py::test_anthropic_and_openclaw_adapters_implement_interface` extends to cover the new adapter.

---

## Anatomy CI gates pinning the design

| Test | What it asserts |
|---|---|
| `test_agent_schema.py` | Every `agent.yml` validates against the schema, name matches dir, paths exist |
| `test_agentkit_naming.py::test_all_agentkit_tables_declared` | 6 tables present in schema-extensions.sql |
| `test_agentkit_naming.py::test_php_namespace_is_App_AgentKit` | PSR-4 contract holds for autoloader |
| `test_agentkit_naming.py::test_event_repository_carries_agentkit_types` | 12 A14 event types in VALID_TYPES |
| `test_agentkit_naming.py::test_uri_scheme_uses_dash_separator` | Conductor primary URI uses dashes |
| `test_agentkit_naming.py::test_runner_emits_required_audit_events` | Runner.php fires the canonical lifecycle events |
| `test_agentkit_naming.py::test_llm_client_protocol_is_minimal` | Interface stays at 2 methods (identifier, send) |
| `test_agentkit_naming.py::test_anthropic_and_openclaw_adapters_implement_interface` | Both adapters honour the protocol |

A regression that breaks any of these turns CI red before merge.

---

## What's next (post-A14)

- **Multi-agent process pool** — Coordinator currently runs sub-agents sequentially. A future iteration spawns parallel processes (capped at `max_concurrent_threads`) with primary-thread event proxy, mirroring Anthropic's full multi-agent surface.
- **Dreams** (memory consolidation) — scheduled job that reads recent `agent_sessions` + an existing memory store, produces a deduplicated output store. Uses the same Runner code path with a special "dreaming" tool roster.
- **Operator-trigger UI** — SHIPPED 2026-05-07 (Track B). `POST /api/v1/agents/<name>/sessions` (bearer auth) generates `session_uuid` server-side, spawns `php bin/run-agent.php` via `proc_open` array form (no shell), and returns 202 immediately. The Wing detail page (`/agents/<name>`) carries a "Start new session" form that proxies through `AgentsPresenter::actionStart` so the bearer token never touches browser HTML; on success the operator is redirected to `/agents/<name>/sessions/<uuid>` which auto-refreshes every 3s while status is `pending` / `running` / `starting`. Contract pinned by `tests/anatomy/test_agentkit_operator_trigger.py` (9 tests covering POST-only, actor_id derivation, proc_open array form, 202 shape, route ordering, run-agent.php --session-uuid forwarding).
- ~~**Vault refresh from Infisical**~~ — `infisical:/path` secret_ref scheme **SHIPPED Track B U-B-Vault, 2026-05-07** (see Vault model section above). Re-resolution per session means rotated values pick up automatically when a new session opens; long-running sessions still see the value resolved at session-open time (acceptable trade-off — agents are short-lived by design).
- **Per-agent webhook auto-fan-out** — agent.yml gains a `subscribe:` block to register the agent itself as a webhook receiver for events it cares about, enabling event-driven loops.
