# Wing cortex-lang Executor — P1 design

> **Status:** design-locked, P1 = **read-only**. The nOS-side counterpart to KEAP's
> `POST /agent/v1/validate` (`feat/cortex-validate`). Synthesized by a 7-agent
> ultracode workflow (2026-07-25): the minimal design's synchronous spine + the
> security design's capability-token model verbatim + the agentkit design's
> audit-lineage reuse, with all async/ledger machinery deferred to P3.
> **Companion:** [`nos-cortex-lang.md`](nos-cortex-lang.md) (the language + the KEAP side).
> **Open integration risks are in §8 — read those before PR-1** (esp. the Wing-host →
> KEAP-container network path).

## Design verdict & provenance

**Ranked, with the deciding trade-off for each.**

**1 — Design 0 (minimal) — best spine.** Its thesis is the correct P1 shape: read verbs are single loopback GETs that return in milliseconds, so dispatch is **synchronous** and the entire detached-spawn / status-poll / session-UUID / 202-Accepted surface is dead weight in P1. That is genuinely zero-blast-radius — one presenter, one route, one schema column, no new daemon, no new table, no orchestration change. Deciding factor: it deletes the machinery the other two build. Correctness is complete (source-not-ast, revalidate-at-dispatch, 409 on databaseId drift, phase-2 never shipped to KEAP, D3 coverage gate, 7 read verbs). Its one weakness is security posture: a NULL-scope brain token passes `requireCortexScope` silently.

**2 — Design 1 (security) — strongest capability boundary; take its security wholesale.** Best on (b) by a clear margin and tied-best on (a). Wins that this synthesis grafts: **qualified namespaces** (`db:wing`, not bare `db`) so a token can read `db:events` but not `db:gdpr`; **refuse the NULL-scope brain token at the executor door** ("the strong token may not use the weak door"); **`auth_scope` emitted at phase-2 resolution** so credential binding and resource resolution are decided in one place (a handler cannot reach a store its resolved target didn't authorize); **refusals audited as first-class events**; the fully-ordered binding gate including `opcodeRegistryHash` → re-run coverage; and the `ent:`/`kg:`-reaching-a-handler → 500 invariant-violation. Deciding demerit vs Design 0: it front-loads the `cortex_dispatches` ledger + idempotency table into PR-1 that P1 read verbs never exercise — heft the synchronous spine doesn't need yet.

**3 — Design 2 (agentkit) — best consistency idea, over-built for P1.** Correct and the only one that makes executor runs appear in `/agents`. But it spawns a detached `agent_sessions` run + `bin/run-cortex.php` for verbs that return in milliseconds — exactly the blast radius Design 0's thesis argues against, and the design itself concedes `plan` (sync) and `dispatch` (detached) do identical work for read-only P1. Grafts taken: reuse of `AuditEmitter` + `events` + `actor_action_id` lineage **without** the spawn (a synchronous dispatch writes the same audit rows), its clean resolution of the 13-vs-7 opcode-coverage ambiguity (scope the D3 gate to **non-mutating** published opcodes), and its explicit brain-token-refusal. The `ExecutorSpawner`/detached path is deferred to P3, where long-running writes actually justify it.

**Synthesis rule:** Design 0's synchronous spine + Design 1's security model verbatim + Design 2's audit-lineage reuse and coverage-gate scoping, with all async/ledger/idempotency machinery deferred to P3 seams that are cut now but unwritten.

---

Below is the deliverable spec, ready to land as `docs/plans/nos-cortex-lang-wing-executor.md`.

---



**Status:** design-locked, P1 = read-only.
**Root for all paths:** `/Users/pazny/projects/nOS/files/anatomy/wing` unless otherwise absolute.

## 0. Thesis and invariants

The executor is a **capability boundary with read-verb handlers hanging off it**, dispatching **synchronously**. Three properties are non-negotiable and every one is built in P1:

1. **Authority separation.** KEAP owns *meaning* (`valid:true` is not authorization; `scope.authorizes:false` is a literal KEAP constant). Wing owns *permission* (capability tokens) and *phase-2 resolution* (`db:`/`svc:`/`doc:`). The executor never treats `valid:true` as authorization.
2. **Synchronous read dispatch.** A read verb is a loopback GET; the executor dispatches in-request and returns inline. No detached spawn, no `/status/<id>`, no `agent_sessions` row, no new daemon in P1. That surface is a P3 write-verb concern (§6).
3. **Strictly-weaker capability tokens.** The executor is reachable **only** by a per-`(verbs × namespaces × tenant)` token that is provably weaker than both the flat Wing `default` brain token and the KEAP `/agent/v1` system token. The brain token is refused at the executor door.

**Hard invariants (from the KEAP contract):**

- The executor accepts `source`, never a caller-supplied `ast`. It re-POSTs to KEAP to obtain a fresh validated AST (revalidate-at-dispatch). A caller may pass a cached `ast_binding` **only** to prove freshness and short-circuit the round-trip; a missing/mismatched binding forces a full `validate()`.
- `db:` / `svc:` / `doc:` **do not exist in KEAP** and must never be sent to KEAP to "consolidate." Wing is their sole validation authority.
- `kg:` / `ent:` can never appear in a `valid:true` AST (KEAP constant-rejects them). If one reaches a handler it is a KEAP-contract breach → **500 invariant-violation**, audited.
- `databaseId` drift is identity drift → **409 REJECT**, never silently re-resolved.
- Handler map is **code-owned**; a capability can never be added by data. Boot fails closed if handlers ⊉ KEAP's published **non-mutating** opcodes.

---

## 1. The endpoint

### 1.1 Routes — `app/Core/RouterFactory.php` (`$api` block)

Insert after the Pulse block (~line 112), specific-before-catch-all (Nette first-match-wins):

```php
// Cortex-lang executor (P1 — read verbs only, synchronous). Bearer + capability scope.
$api->addRoute('api/v1/cortex/opcodes', 'CortexExecutor:opcodes'); // GET handler-map self-report
$api->addRoute('api/v1/cortex/execute', 'CortexExecutor:execute'); // POST validate→resolve→dispatch, inline result
```

No `/status/<id>` in P1 — synchronous dispatch has no job to poll. P3 adds `api/v1/cortex/execute/status/<id>` **above** these lines when write verbs go async.

### 1.2 Presenter — `app/Presenters/Api/CortexExecutorPresenter.php` (NEW)

Extends `BaseApiPresenter` (bearer only — **not** `BasePresenter`; no edge / forward-auth / tier gate). Auto-discovered via `application.mapping` (`Api: App\Presenters\Api\*Presenter`, `common.neon:20`); no neon entry for the presenter itself. Constructor-injects the five services (§7).

```php
final class CortexExecutorPresenter extends BaseApiPresenter
{
    public function __construct(
        private KeapCortexClient      $keap,     // §5.2 Wing→KEAP RO validate + read client
        private CortexOpcodeRegistry  $opcodes,  // §3   code-owned opcode→handler map
        private CortexPhase2Resolver  $phase2,   // §2   db:/svc:/doc: authority (+ auth_scope)
        private CortexBindingGate     $binding,  // §5.3 TTL / onto / databaseId / registryHash gate
        private CortexAuditWriter     $audit,    // §5.1 events + actor_action_id lineage
    ) {}

    public function startup(): void  // §4.3 refuse the brain (NULL-scope) token at the door
    public function actionOpcodes(): void   // GET  { handlers[], registry_hash, covers_keap:true }
    public function actionExecute(): void   // POST the linear gate below
}
```

### 1.3 `actionExecute()` — the linear gate (hard-stop ordered; none skippable)

```
requireMethod('POST')
body   = getJsonBody(); require string `source`  else 422
actor  = getActorId()                 // token 'name' — NEVER from body (anti-spoof)
tenant = body.tenant ?? validatedToken.tenant ?? 'default'   // body may only NARROW, never widen (§4)
reject body.commit truthy             // §6 write-future gate: 403 in P1

1. report = keap.validate(source, body.ttlSeconds)          // §5.2 phase-1 authority
   KEAP unreachable/broken envelope → 502 (distinct from valid:false)
2. if !report.valid → 200 { valid:false, ast:null, errors:report.errors[], dispatched:false }
                                                            // codes passed through verbatim; repair loop lives in caller
3. binding.assertDispatchable(report.ast.binding, body.ast_binding ?? null)   // §5.3 → 409 on databaseId drift
4. phase2 = phase2.resolve(report.ast, tenant)             // §2 fills db:/svc:/doc:; tenant-filtered
   if !phase2.valid → 200 { valid:false, dispatched:false, errors:phase2.errors[] }   // uniform shape
5. for each stage in report.ast.pipeline.stages:
     a. if stage.mutating === true          → 501 "mutating verbs not dispatchable in P1"   (defense-in-depth)
     b. if !opcodes.has(stage.opcode)        → 501 "no handler for opcode '<x>'"
     c. requireCortexScope(stage.opcode, stage.operands, tenant)   // §4.3 → 403 per axis
     d. any operand.ns ∈ {kg,ent}            → 500 invariant-violation (KEAP breach), audit cortex_dispatch_reject
6. for each stage (execute + audit, per-stage lineage):
     resolved  = phase2 result for stage
     actionId  = audit.begin(stage, actor, tenant, report.ast.binding)  // §5.1 mints cx-<ulid>
     result    = opcodes.handler(stage.opcode).execute(resolved, ctx)   // §3 read-only
     audit.finish(actionId, result)
     out[] = { index, opcode, ns, result, audited_action_id: actionId }
7. sendSuccess({ valid:true, complete:report.complete, dispatched:true, stages:out,
                 binding:report.ast.binding }, 200)
```

Any gate refusal (a–d) emits a first-class `cortex_dispatch_reject` audit row (§5.1) carrying the gate name + code before the error response.

### 1.4 Request / response

**Request** `POST /api/v1/cortex/execute`, `Authorization: Bearer <executor-token>`:

```jsonc
{
  "source": "get tax:physics | rank ?by=depth ?limit=10",  // REQUIRED — the cortex-lang program
  "tenant": "default",          // OPTIONAL; may only narrow the token's tenant
  "ttlSeconds": 900,            // OPTIONAL; forwarded to KEAP validate, clamped there
  "ast_binding": { … },         // OPTIONAL; caller-cached binding to prove freshness (never a full AST)
  "commit": false,              // §6 write-future hook — must be false/absent in P1
  "idempotency_key": null       // §6 write-future hook — ignored in P1
}
```

**Response 200** (success, synchronous):

```jsonc
{
  "success": true,
  "data": {
    "valid": true, "complete": true, "dispatched": true,
    "stages": [
      { "index": 0, "opcode": "get", "ns": "tax",
        "result": { /* handler output verbatim */ }, "audited_action_id": "cx-01J…" }
    ],
    "binding": { "ontologyVersion": "onto1:…", "databaseId": "…",
                 "opcodeRegistryHash": "…", "validatedAt": "…", "expiresAt": "…" }
  }
}
```

### 1.5 Status-code contract (**flagged — no nOS precedent; confirm before PR-1**)

| Condition | Code | Envelope |
|---|---|---|
| Program valid, dispatched | 200 | `success:true` |
| KEAP `valid:false` (phase-1) | 200 | `data:{valid:false, errors[], dispatched:false}` (KEAP mirror) |
| Phase-2 unresolvable (`db:`/`svc:`/`doc:`) | 200 | `data:{valid:false, errors:[{code:"unresolvable_resource",…}], dispatched:false}` |
| `source` missing / not a string | 422 | `sendError` |
| Scope / namespace / tenant refusal | 403 | `sendError` |
| Brain (NULL-scope) token at executor | 403 | `sendError` (§4.3 startup) |
| Mutating verb in P1 / no handler | 501 | `sendError` |
| `databaseId` drift / `databaseId==''` | 409 | `sendError` |
| `kg:`/`ent:` reached a handler | 500 | invariant-violation, audited |
| KEAP unreachable / broken envelope | 502 | `sendError` |

---

## 2. Phase-2 validation — `db:` / `svc:` / `doc:`

KEAP hands these as `kind:"deferred"`, `id:null`, also enumerated in `ast.deferred[]`. Wing is the sole authority. New: `app/Cortex/CortexPhase2Resolver.php` + `app/Cortex/ResourceRegistry.php`.

**Doctrine:** *code-owned for the shape of each namespace, data-backed only for `svc:` membership* — mirrors KEAP (opcodes code, ontology data). A store/doc-source is a **capability**; it must not be addable by data.

| ns | resolves `surface` against | source of truth | connector for §3 |
|----|----|----|----|
| `svc:` | an **enabled** nOS service with a read surface | `hub_systems` (served by `Api\HubPresenter` `api/v1/hub/systems`, populated from `state/manifest.yml` + apps_runner post-hooks), **tenant-filtered** | loopback bearer (`McpWingTool` template) or `BoneClient` (`X-API-Key`) for host services |
| `db:` | a **fixed code enum** of read surfaces | `const STORES = ['mariadb','postgres','redis','wing_sqlite','qdrant', 'events','remediation','pentest','gdpr']` (qualified where a store has sub-surfaces) | `Nette\Database\Explorer` (sqlite), `QdrantClient`, thin PG/MariaDB read connector |
| `doc:` | a **fixed code map** of content sources | `const DOC_SOURCES = ['keap','nextcloud','calibre','kiwix','openwebui']` → the read surface each names | KEAP `/agent/v1` content read, or loopback service API |

### 2.1 `resolve(ast, tenant): Phase2Report`

```php
foreach ($ast['deferred'] as $ref) {           // {stage, operand, ns, surface}
    $id = match($ref['ns']) {
        'svc' => $this->hub->findEnabledSlug($ref['surface'], $tenant),   // tenant-scoped DB lookup
        'db'  => in_array($ref['surface'], self::STORES, true) ? $ref['surface'] : null,
        'doc' => self::DOC_SOURCES[$ref['surface']] ?? null,
    };
    if ($id === null) $errors[] = new UnresolvableResource($ref['ns'], $ref['surface']);
    else $resolved[$ref['stage']][$ref['operand']] = new ResolvedResource(
        ns: $ref['ns'], surface: $ref['surface'], target: $id,
        transport: /* http|explorer|qdrant|bone */,
        auth_scope: /* the CredentialResolver scope the handler will need — §2.3 */,
    );
}
```

- `tax:`/`rel:` operands are already `kind:"resolved"` (id + resolvedName from KEAP); phase-2 leaves them untouched.
- **Tenant is enforced here, not in the handler.** `svc:` resolution is tenant-filtered against `hub_systems`; a token scoped to tenant A physically cannot resolve a tenant-B `svc:` target — the phase-2 gate *is* a tenant gate. (`db:`/`doc:` are host-global in P1 — **flagged**, §8.1.)

### 2.2 Uniform error shape

`UnresolvableResource` renders **byte-identical to KEAP's closed shape** so the caller's repair loop is symmetric across phases:

```jsonc
{ "code": "unresolvable_resource", "severity": "error", "stage": 2,
  "detail": { "ns": "svc", "surface": "nextcloud" } }   // closed: ns + surface only, no "did you mean"
```

Ambiguous alias (multi-match) → `ambiguous_resource` with capped `candidates:[{id,name}]`, mirroring KEAP's `ambiguous_operand`.

### 2.3 `auth_scope` binding (grafted from Design 1)

`resolve()` emits, per resolved operand, the exact `CredentialResolver` scope name the handler will use. **Resolution and credential-binding are decided in one place** — a handler can never reach a store its resolved target didn't authorize. Plaintext lives only in a function-local inside the connector call, never in a handler field, never in the DB.

---

## 3. Code-owned opcode → handler registry

New: `app/Cortex/CortexOpcodeRegistry.php` + `app/Cortex/Handler/CortexHandlerInterface.php` + `app/Cortex/Handler/*Handler.php`.

### 3.1 The closed set

```php
private const HANDLERS = [
    'get'      => ['class' => GetHandler::class,      'mutating' => false],
    'map'      => ['class' => MapHandler::class,      'mutating' => false],
    'filter'   => ['class' => FilterHandler::class,   'mutating' => false],
    'rank'     => ['class' => RankHandler::class,     'mutating' => false],
    'classify' => ['class' => ClassifyHandler::class, 'mutating' => false],
    'resolve'  => ['class' => ResolveHandler::class,  'mutating' => false],
    'embed'    => ['class' => EmbedHandler::class,     'mutating' => false],
];   // 7 non-mutating verbs. `mutating` mirrored from KEAP — defense-in-depth, Wing re-derives, never trusts the AST flag blindly.
```

Registered via a `ToolRegistry`-style factory in `common.neon` (mirror `common.neon:137-153`). Prefer **many specific typed verbs over one polymorphic dispatcher** — each verb its own class, its own `acceptedNamespaces()`, its own return type.

### 3.2 Boot-time coverage gate (D3 fail-closed)

`CortexOpcodeRegistry::assertCoversPublished(array $keapOpcodes)` throws if any published **non-mutating** opcode lacks a handler key → Wing **refuses to start**. Invoked cheaply from `startup()` (KEAP `GET /agent/v1/validate/opcodes` cached with its `opcodeRegistryHash`; re-fetched on hash miss) and re-run standalone by `bin/cortex-preflight.php` in the `pazny.wing` post-deploy.

> **Coverage scope (resolved ambiguity, from Design 2):** KEAP publishes 13 opcodes (7 read + 6 write); P1 Wing has 7 read handlers. The coverage check is scoped to **non-mutating** published opcodes — Wing rejects any `mutating:true` stage at the door (§1.3 step 5a), so it never *accepts* an AST it cannot dispatch. **Confirm with the KEAP owner** that D3's intent is "cover every dispatchable opcode," not the literal full set; if literal, the check must be explicitly narrowed on the KEAP side too. Ordering: Wing ships the handler first, KEAP enables the opcode second. Gate: `tests/anatomy/test_cortex_handler_coverage.py`.

### 3.3 Handler contract

```php
interface CortexHandlerInterface {
    public function opcode(): string;
    public function mutating(): bool;                 // false for all 7 P1 verbs
    public function acceptedNamespaces(): array;      // MUST ⊆ KEAP's for this opcode
    public function execute(ResolvedStage $stage, CortexContext $ctx): CortexStageResult;
}
```

Shaped to *converge toward* AgentKit's `ToolInterface` (opcode≈identifier, `execute(ctx)`≈`run(ctx)`) so the two runtimes read alike — but deliberately **thinner**: scope enforcement already happened at the token boundary (§4), so no `ToolContext`/scopes plumbing. `CortexContext` carries `{ actorId, tenant, traceId, actionId, ResourceRegistry, CredentialResolver }` — the handler never sees the raw token, never reaches global state. `CortexStageResult` carries `{ effect:'read', rows, cost }`.

### 3.4 The 7 read handlers + the surface each calls

Zero new read code — each handler is a thin adapter over an existing surface.

| opcode | operand ns (P1) | calls | how |
|---|---|---|---|
| `get` | `tax`,`rel` → KEAP; `svc`; `db`; `doc` | `KeapCortexClient` node fetch (RO bearer) / `HubRepository`+loopback bearer / `Explorer`·`QdrantClient`·`BoneClient` / doc source | honours `limit`/`fields` from `stage.params` |
| `map` | `tax` | `KeapCortexClient` subtree/edge listing | tax-only (`kg` never valid) |
| `filter` | `tax` | `KeapCortexClient` filtered list + `?where` | `where` is a **structured predicate the handler compiles, never raw SQL** |
| `rank` | `tax` | `KeapCortexClient` ranked list + `?by`/`?limit` | tax-only |
| `classify` | `tax` | `KeapCortexClient` classify + `?threshold` | tax-only |
| `resolve` | `tax`,`rel` | **pure AST read-back** — echoes carried `{id, resolvedName}`; for `db`/`svc`/`doc` returns the `ResolvedResource` target | no downstream I/O; cheapest verb, no new resolution authority |
| `embed` | `tax`,`doc` | `QdrantClient` projection / KEAP embed + `?model` | non-mutating projection; **P1 pragmatic cut** below |

**P1 cut:** `embed` is the only handler needing a built Qdrant corpus. If unavailable it returns a typed `{code:"late_binding_unavailable"}` rather than block the PR — the handler **key still exists**, so the D3 coverage gate stays green. Ship 6 live + `embed` stubbed-typed.

### 3.5 `KeapCortexClient` — `app/Model/KeapCortexClient.php` (NEW)

Loopback/gated-net HTTP to KEAP `/agent/v1/*` with the **RO agent bearer** (`CredentialResolver->resolve('keap-agent-ro')` → `env:KEAP_AGENT_RO_TOKEN`), modeled on `McpWingTool` (bearer-over-loopback) + `BoneClient` (return `{status,body}` verbatim). Methods: `validate(source, ttl): CortexValidateReport` plus per-verb read methods. Non-200 envelope / DB-broken → executor 502 (distinct from `valid:false` → 200).

---

## 4. Capability-scoped tokens

The flat `default` brain token and the KEAP `/agent/v1` token are both too strong. The executor requires a strictly-weaker per-capability token and **refuses the brain token at the door**.

### 4.1 Schema — `api_tokens.scopes` + `tenant` (idempotent)

`bin/init-db.php:286` and mirror `files/anatomy/skills/contracts/wing.db-schema.sql:131`. Additive, via the existing `$addMissingColumns` sweep:

```php
$addMissingColumns($db, 'api_tokens', [ 'scopes' => 'TEXT', 'tenant' => 'TEXT' ]);
// scopes JSON, NULL = legacy flat/brain token (full /api/v1/* — unchanged for every OTHER endpoint)
```

`scopes` is a JSON document (never CSV) encoding three axes:

```jsonc
{ "verbs":      ["get","map","rank","classify","resolve"],
  "namespaces": ["tax","rel","db:wing_sqlite","db:events","svc:gitea","doc:keap"],  // QUALIFIED where it matters
  "tenants":    ["default"] }
```

- **`verbs`** — subset of the 7 read opcodes. A write verb can never appear in a P1 executor token.
- **`namespaces`** — qualified down to the resource: a token may carry `db:events` but not `db:gdpr`. `nsAllowed` matches both bare (`db`) and qualified (`db:events`) grants.
- **`tenants`** — allowed tenant ids; the executor forces `tenant` from the token, request `tenant` may only narrow.

**No P1 executor token is NULL-scope and none carries `"*"`.**

### 4.2 Issuance

`TokenRepository::create()` (`app/Model/TokenRepository.php:48`) gains `?array $scopes, ?string $tenant`; `validate()` already strips the hash and returns the row — add decoded `scopes`+`tenant` to the returned array (rides along once columns exist). `bin/provision-token.php:71` gains `--scopes=<json>` / `--tenant=`. The `pazny.wing` role mints, per playbook pass (idempotent DELETE-by-name + INSERT), a narrow token e.g. `name=cortex-exec-readonly-default` holding exactly the read verbs × read namespaces × `default` — **never** the `default` brain token.

### 4.3 Verification — `BaseApiPresenter` + presenter startup

Beside `getActorId()` (`BaseApiPresenter:68`):

```php
protected function requireCortexScope(string $verb, array $operands, string $tenant): void
{
    $s = $this->validatedToken['scopes'] ?? null;   // NULL handled at the DOOR (below), not here
    $g = json_decode($s, true) ?: [];
    if (!in_array($verb, $g['verbs'] ?? [], true))
        $this->sendError("token not authorized for verb '$verb'", 403);
    foreach ($operands as $op)
        if (!$this->nsAllowed($op['ns'], $op['surface'] ?? null, $g['namespaces'] ?? []))
            $this->sendError("token not authorized for namespace '{$op['ns']}'", 403);
    if (!in_array($tenant, $g['tenants'] ?? [], true))
        $this->sendError("token not authorized for tenant '$tenant'", 403);
}
```

**Brain-token refusal (grafted from Design 1's recommendation, enforced per Design 2):** the strong token may not use the weak door. In `CortexExecutorPresenter::startup()` **only** (not globally — every other endpoint keeps NULL=full-access back-compat):

```php
public function startup(): void {
    parent::startup();
    if (($this->validatedToken['scopes'] ?? null) === null)
        $this->sendError('executor requires a capability-scoped token', 403);
}
```

This makes the executor token provably weaker along three independent axes the brain token bypasses. Gate: `tests/anatomy/test_cortex_token_scope.py`.

---

## 5. Audit + AST TTL

### 5.1 Audit — one lineage per stage, reusing `AuditEmitter`

New `app/Cortex/CortexAuditWriter.php`, modeled on `AgentKit\Telemetry\AuditEmitter` (direct in-process `EventRepository::insert()`, fail-soft) — **no new table in P1** (zero blast radius; the `events` table + `actor_action_id` lineage key are reused verbatim).

- `begin(stage, actor, tenant, binding): string` — mints `actor_action_id = "cx-<ulid>"`, inserts `events` row `type=cortex_dispatch_start`, `source='cortex'`, `actor_id=<token name>` (from `getActorId()`, **never body**), `detail={opcode, ns[], tenant, ontologyVersion, databaseId}`.
- `finish(actionId, result)` — inserts `cortex_dispatch_ok` / `cortex_dispatch_error`, same `actor_action_id`.
- **One `actor_action_id` per stage** (pipeline of N stages = N lineages) → granular per-verb audit; `SELECT * FROM events WHERE actor_action_id=?` reconstructs a stage, identical discipline to AgentKit sessions.
- **Refusals are first-class:** every gate refusal emits `cortex_dispatch_reject` with the gate name + code before the error response.
- New event types to register: `cortex_dispatch_start`, `cortex_dispatch_ok`, `cortex_dispatch_error`, `cortex_dispatch_reject`, `cortex_binding_rejected`.
- **OTel optional in P1:** the AgentKit `OtelExporter` → Alloy `127.0.0.1:4318` path (service name `nos.cortex`) is reusable; `events`-row audit is mandatory, span export is nice-to-have.

### 5.2 KEAP validate client

`KeapCortexClient::validate(source, ttl)` (§3.5) POSTs `{source, ttlSeconds}` to KEAP `POST /agent/v1/validate` with the RO bearer; returns typed `CortexValidateReport` / `CortexAst` / `CortexAstBinding` / `CortexIssue`.

### 5.3 AST TTL / revalidate-at-dispatch — `app/Cortex/CortexBindingGate.php` (NEW)

validate-time ≠ dispatch-time. `assertDispatchable(fresh, cached?)` implements KEAP's mandated order:

```
databaseId == ''                     → 409 REJECT (pre-initDb fail-closed sentinel; never equals a real id)
databaseId (fresh) != knownDatabaseId → 409 REJECT — different DB = different language = identity drift. NEVER re-resolve.
expiresAt < now                      → already revalidated (canonical path re-POSTs source); proceed on fresh report
ontologyVersion moved                → already covered by revalidate-at-dispatch; proceed on fresh report
opcodeRegistryHash moved             → refuse dispatch + re-run §3.2 boot coverage gate (handler map may no longer cover)
else (fresh, within TTL)             → dispatch
```

Because `actionExecute` **always** re-POSTs `source` to KEAP first (§1.3 step 1), the TTL and `ontologyVersion` arms are automatic — the executor can never hold a stale AST. The `databaseId` arm is the one hard reject; `opcodeRegistryHash` drift re-runs coverage (grafted from Design 1). A caller-supplied `ast_binding` may only short-circuit the round-trip when provably fresh; mismatch forces full `validate()`. **No `{ast}` input is ever accepted** — a caller-supplied AST could forge resolution. `knownDatabaseId()` is fetched from KEAP once at boot and cached (equals the just-returned report's binding). Gate: `tests/anatomy/test_cortex_binding_gate.py`.

### 5.4 `ent:` / `kg:` never received

A `valid:true` AST never contains `kg:`/`ent:` (KEAP constant-rejects, zero DB query, no timing oracle). Defense-in-depth: any operand with `ns ∈ {kg,ent}` reaching step 5d is a **500 invariant-violation** (KEAP-contract breach), audited as `cortex_dispatch_reject`. This pins the acceptance criterion that nOS's P2 emitter must never emit `ent:`.

---

## 6. Write-verb-future hook (P3-additive, seams cut now, unwritten in P1)

P1 refuses mutating verbs at step 5a (501), but the attachment points exist so P3 is purely additive — **new handler classes + un-stub one branch**, no boundary moves:

- **Registry split.** `HANDLERS` is read-verb-only; P3 adds a parallel `MUTATING_HANDLERS` + a `WriteHandlerInterface`. The `stage.mutating` flag KEAP stamps is the switch — step 5a flips from `501` to `dispatchWrite()`.
- **`dry_run` / `commit`.** KEAP already computes `stage.effective.dry_run` (default `true` for mutating) and emits the `commit_requires_confirm_gate` warning on `commit=true`/`dry_run=false`. P1 refuses `commit=true` at the door; P3 reads `effective.dry_run` (**normative** — never `params`) and honours `?commit=true`.
- **Confirm-gate.** `app/Cortex/CortexConfirmGate.php` (empty stub interface registered in neon now so the constructor signature is stable) keys on `commit_requires_confirm_gate` + opcode ∈ {delete,update}; P3 fills it with the nOS destructive-op safety model (dry-run default + explicit second confirm token, manual over auto-scheduled — memory `feedback-destructive-op-safety`).
- **Idempotence.** P3 adds `cortex_idempotency (idempotency_key, actor_id, database_id, result_hash, created_at)` — **not created in P1** (reads are pure; replay-dedup is low value and a new table is blast radius the thesis forbids). The `actor_action_id` audit thread is already the dedup substrate. `idempotency_key` becomes **required** for mutating dispatch. Replay never bypasses the dry-run gate; modifiers/flags never inherited (read `effective` fresh per stage).
- **Async spawn.** When a write is long-running, *that* is when the AgentKit detached-spawn pattern (`OperatorTrigger` clone → `agent_sessions` row → `/status/<id>` poll) attaches (Design 2's machinery, deferred here). **Read verbs stay synchronous forever.**
- **Token scopes already express writes.** A write-capable token is a different `name` with write verbs in `scopes.verbs`. No schema change at P3.

---

## 7. First-PR build plan (`feat/cortex-executor` off `dev`)

Zero blast radius: **no composer deps** (pure PHP + existing HTTP clients) → the lockfile-sync gate can't break → no blank run needed to validate; pytest + a Wing live-verify (memory `wing-live-verify-recipe`).

### New files
```
app/Presenters/Api/CortexExecutorPresenter.php          §1 endpoint + startup brain-token refusal
app/Cortex/CortexOpcodeRegistry.php                     §3 const map + assertCoversPublished (D3)
app/Cortex/Handler/CortexHandlerInterface.php           §3.3 thin read contract
app/Cortex/Handler/{Get,Map,Filter,Rank,Classify,Resolve,Embed}Handler.php   §3.4 (6 live + embed typed-stub)
app/Cortex/CortexPhase2Resolver.php                     §2 db:/svc:/doc: resolution + auth_scope
app/Cortex/ResourceRegistry.php                         §2 STORES / DOC_SOURCES code enums
app/Cortex/CortexBindingGate.php                        §5.3 TTL/onto/databaseId/registryHash gate
app/Cortex/CortexAuditWriter.php                        §5.1 events + actor_action_id (no new table)
app/Cortex/CortexContext.php                            §3.3 per-run context
app/Cortex/ResolvedStage.php  ResolvedResource.php
app/Cortex/Exception/{UnresolvableResource,BindingRejected,InvariantViolation}.php
app/Cortex/CortexConfirmGate.php                        §6 stub interface (registered, unreferenced in P1)
app/Model/KeapCortexClient.php                          §3.5 Wing→KEAP RO validate + read client
bin/cortex-preflight.php                                §3.2 standalone D3 gate for pazny.wing post-deploy
tests/anatomy/test_cortex_handler_coverage.py           handlers ⊇ published non-mutating opcodes
tests/anatomy/test_cortex_token_scope.py                3-axis scope refusal + brain-token 403 at door
tests/anatomy/test_cortex_binding_gate.py               expired→revalidate, databaseId-moved→409, ''→409
tests/anatomy/test_cortex_phase2_uniform_error.py       unknown svc/db/doc → byte-identical {code,detail:{ns,surface}}
```

### Edits
```
app/Core/RouterFactory.php               +2 routes (opcodes, execute), specific-before-catch-all
app/Presenters/Api/BaseApiPresenter.php  +requireCortexScope() + nsAllowed() beside getActorId():68
app/Model/TokenRepository.php:48         create() gains ?array $scopes, ?string $tenant; validate() returns them
bin/init-db.php:286                      $addMissingColumns api_tokens += scopes, tenant (idempotent sweep)
files/anatomy/skills/contracts/wing.db-schema.sql:131   mirror the schema delta
bin/provision-token.php:71               --scopes= / --tenant= ; mint cortex-exec-readonly-<tenant>
app/config/common.neon (services:)       register KeapCortexClient, CortexOpcodeRegistry (ToolRegistry-style
                                         factory ~137-153), CortexPhase2Resolver, ResourceRegistry,
                                         CortexBindingGate, CortexAuditWriter, CortexConfirmGate, 7 handlers;
                                         CredentialResolver scope 'keap-agent-ro'
roles/pazny.wing/tasks/*                 provision the scoped token; run bin/cortex-preflight.php;
                                         surface KEAP_AGENT_URL + keap-agent-ro secret_ref into Wing env
```

### First-PR acceptance
Endpoint accepts `get tax:…` and `get svc:gitea` with a scoped token, dispatches read-only **synchronously**, audits per-stage `cortex_dispatch_*` events under one `actor_action_id` each, rejects a mutating verb with 501, rejects a stale `databaseId` with 409, refuses the brain token with 403 at the door, refuses to boot if KEAP publishes a non-mutating opcode Wing has no handler for, and returns phase-2 `unresolvable_resource` in the byte-identical KEAP shape.

### Phase 2 (follow-up PR)
`embed` live (Qdrant corpus), `doc:` reach into Nextcloud/Calibre read surfaces, per-tenant `db:`/`doc:` scoping, optional OTel span export, optional AgentKit-native detached `dispatch` path (`/agents` visibility) reusing `OperatorTrigger` — **only if** a read caller wants an audited session view; not required.

### Phase 3 (post-P2 emitter)
Write verbs: `MUTATING_HANDLERS` + `WriteHandlerInterface`, `CortexConfirmGate` fill, `cortex_idempotency` table, `?commit=true` + `effective.dry_run` enforcement, detached `/status/<id>` spawn for long writes.

---

## 8. Ambiguities the maps left open (flagged, with the P1 default chosen)

1. **`db:` / `doc:` tenancy.** `svc:` is cleanly tenant-scoped via `hub_systems`; the maps give no per-tenant model for `db:` stores or `doc:` sources. **P1 default:** host-global (code const). Deferred to Phase 2. If a tenant must not see another tenant's DB, this is a P1 gap — confirm.
2. **Status codes** for missing-handler (501) / scope refusal (403) / stale binding (409) / mutating-in-P1 (501) have no nOS precedent. Confirm against any convention before PR-1.
3. **5 vs 7 read verbs.** Acceptance names 5 (`get/map/classify/resolve/rank`); KEAP's `mutating:false` set publishes 7 (`+filter +embed`). The D3 gate forces covering every **non-mutating** published opcode → ship all 7 (embed typed-stubbed), OR have KEAP publish only the enabled subset. **Resolve jointly with the KEAP owner before PR-1** or boot red-lines.
4. **D3 coverage scope** — resolved to **non-mutating** published opcodes (§3.2). Confirm KEAP's literal intent isn't the full 13-opcode set.
5. **KEAP RO-token provisioning into Wing.** Assumed `env:KEAP_AGENT_RO_TOKEN` surfaced by `pazny.keap` into Wing's fastcgi env (same channel as `BONE_SECRET`), resolved via `CredentialResolver`. Confirm which role owns the mint.
6. **Wing→KEAP network path (the one genuine integration risk).** Wing is a host launchd process; KEAP is a Docker service, `gated_net`-only per SEC-02, `/agent/v1` on loopback + scope-split bearer. Host→container is not automatic. Assumes a resolvable `KEAP_AGENT_URL` (host-bound gated_net port, Bone-proxied hop, or Traefik internal route). **Verify reachability before `KeapCortexClient` is more than a stub** — everything else is in-process Wing.
7. **`opcodeRegistryHash` per-dispatch pinning.** Covered implicitly by the boot coverage gate + revalidate-at-dispatch + the §5.3 registryHash-drift arm. Flag if per-dispatch hash pinning beyond that is wanted.

---

## 9. File anchors verified across the three source maps
`app/Presenters/Api/BaseApiPresenter.php:68` (`getActorId`, anti-spoof), `app/Model/TokenRepository.php:48` (`create`), `bin/init-db.php:286` (`api_tokens`, no scope column today), `app/Core/RouterFactory.php` (`$api` block; parameterized poll at ~236), `app/Presenters/Api/PulsePresenter.php:267-317` (allowlist discipline to copy), `app/AgentKit/OperatorTrigger.php:64,176` (spawn + `generateUuidV4`, P3), `app/AgentKit/Telemetry/AuditEmitter.php:31,44-45` (`emit`, `actor_action_id` lineage), `app/AgentKit/Tools/McpWingTool.php` (loopback-bearer template), `app/Model/BoneClient.php` (host-bridge template), `app/Model/QdrantClient.php`, `app/config/common.neon:20-22` (Api mapping), `common.neon:137-153` (ToolRegistry factory), `files/anatomy/skills/contracts/wing.db-schema.sql:131`, `state/manifest.yml` + `apps/*.yml` (`svc:` source), `docs/plans/nos-cortex-lang.md`.