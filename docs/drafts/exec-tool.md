# `exec` — one tool, one cortex-lang sentence

Status: rough design draft, not implemented. Motivation: an agent guessing a
`mcp-wing` REST path produced an invented endpoint and a 404 on the first real
turn. `exec` replaces path-guessing with a closed, validated grammar so a
~1B-parameter tool-caller has one surface to learn instead of N REST shapes.

## 1. Surface

- **Tool id:** `exec`. New enum entry in `state/schema/agent.schema.yaml`
  `tools[].id`, alongside `mcp-wing` etc.
- **Required scopes:** same axis as the cortex token, not a new one —
  `requiredScopes()` returns `['cortex.exec']`. An agent's
  `capability_scopes` must carry it before the registry loads the tool
  (`ToolRegistry::forAgent`, unchanged mechanism). This is the FIRST gate,
  before any sentence is ever seen — an agent with no cortex grant never gets
  the tool description in its system prompt.
- **Input schema:** one required string, one optional bool.
  ```json
  {
    "type": "object",
    "required": ["chain"],
    "properties": {
      "chain":   { "type": "string", "description": "One cortex-lang sentence." },
      "confirm": { "type": "boolean", "description": "Required true if the chain contains a mutating stage." }
    }
  }
  ```
  No `binding` field — the tool is stateless per call; see §2 on why the tool,
  not the model, carries binding freshness.
- **Output on success:** the stage-result rows exactly as `CortexExecutorPresenter`
  already returns them (`{ok: true, stages: [{opcode, rows|note}]}`) — no
  reshaping, so the executor stays the single formatter.
- **Output on invalid (parse/validate failure):** `{ok: false, code, detail}`
  where `code` is one of the registry's closed error codes
  (`unknown_namespace`, `unknown_operand`, `malformed_operand`,
  `invalid_param_value`, …) and `detail` is the constant, operand-independent
  string the registry already emits — never a list of what would have parsed.
- **Output on refused:** `{ok: false, code: "confirm_required"|"scope_denied"|"binding_drift", detail}`.

## 2. The path a call takes

```
LLM emits exec({chain, confirm?})
  -> ExecTool::execute()
       -> POST /agent/v1/validate  (cortex daemon, KEAP-side; stateless, no DB write)
            refuses here: unknown_namespace, unknown_operand (namespace-const,
            'unresolvable' policy — no DB call issued), malformed_operand,
            invalid_param_value, stage-limit exceeded
       -> CortexBindingGate::check(fresh, cached=null)
            refuses here: binding_expired (should be unreachable), binding_drift
            (ExecTool never accepts a caller-supplied binding — see below)
       -> per-stage dispatch against CortexOpcodeRegistry handlers
            get/resolve            -> execute for real, return rows
            map/filter/rank/classify -> execute for real (threaded input, since 2026-08-11)
            embed                  -> LateBoundHandler: "no surface to call", ok:true, rows:[]
            delegate/anything mutating -> refused HERE, before dispatch, unless
            confirm:true was passed AND the caller's CortexCapability.verbs allow it
```

Today only `get`/`resolve` (and now `map`/`filter`/`rank`/`classify`) execute;
`embed` is honestly `unavailable`; anything `mutating()===true` (`delegate`,
and any future write verb) is refused at the door regardless of `confirm` —
**P1 refuses every mutating stage before dispatch**, so `confirm:true` today
only ever reaches a chain of non-mutating verbs faster. The flag exists now so
the schema doesn't need a breaking change the day one mutating verb ships a
handler.

`ExecTool` never receives, stores, or forwards a `binding` — it always calls
`/validate` fresh and passes `cached=null` to `CortexBindingGate`, so
`binding_drift` cannot fire from this path (identity drift only matters to a
caller holding a cached AST across calls, which `exec` — one sentence in, one
result out, no session state — never does). One less thing the model has to
reason about.

## 3. The two refusals, structurally enforced

**(a) No enumeration on refusal.** Already true of the registry `exec` calls
into — `unknown_operand` is namespace-const (`NAMESPACE_POLICY.unresolvable`
returns the identical string regardless of which operand failed; measured:
all 261 cases in nOS's own recall set answer the same `unknown_operand`
`docs`). `ExecTool` must not add a repair path on top: it forwards
`{code, detail}` byte-for-byte from `/validate`'s response and MUST NOT catch
`unknown_operand`/`unknown_namespace` to enrich it with "did you mean" or a
candidate list — that would be `exec` re-introducing the WrenAI oracle one
layer up, at the tool boundary instead of the language boundary. **Reviewer
check:** grep `ExecTool.php` for any array of operands/namespaces/ids
assembled outside the pass-through of `/validate`'s own body; a gate
(`test_exec_tool_does_not_enumerate.php` style, mirroring
`test_cortex_lang_vendor_conditions.py`'s "compare declarations" method) feeds
a deliberately-wrong operand and asserts the response body is IDENTICAL in
shape/length class to a second wrong operand, i.e. no operand-keyed branching.

**(b) `exec` cannot skip the confirm gate.** `delegate` and every other
`mutating()===true` opcode are refused by `LateBoundHandler`/the dispatch
loop regardless of the `confirm` field — `confirm:true` is not a capability
grant, it is a caller assertion that gets checked, not trusted. Concretely:
`ExecTool::execute()` must call the SAME `CortexOpcodeRegistry::isMutating()`
check the presenter uses today, BEFORE dispatch, and:
  - if any stage is mutating and `confirm !== true` → refuse `confirm_required`,
    zero stages executed (all-or-nothing per chain, not per-stage).
  - if any stage is mutating and `confirm === true` → still gated by
    `CortexCapability.allowsVerb()` on the token's `cortex_verbs` — `confirm`
    narrows nothing the token didn't already grant, exactly the `?via=`
    asymmetry (data may narrow, never widen). A token with no mutating verb
    grant sees `confirm_required` collapse into the ordinary `scope_denied`.
  **Reviewer check:** a gate that constructs a chain with a mutating stage,
  passes `confirm:true`, and asserts execution still stops at the capability
  check when the token's `cortex_verbs` excludes that opcode — i.e. `confirm`
  is necessary but never sufficient. This is the "add no capability" test the
  brief asks for: run the same chain through the OLD path (hypothetical raw
  REST call to whatever endpoint the verb would hit) and the NEW path
  (`exec`), and assert the set of things each can cause to happen is
  identical. If `exec` can trigger anything the executor + gate would refuse
  today, the tool added capability and the design failed its own test.

## 4. What happens to `mcp-wing` (and `mcp-bone`, `mcp-pulse`, `mcp-keap`)?

Keep all four, unchanged. The honest trade:

- `exec` is a closed, ontology-typed vocabulary over `tax:`/`rel:`/`kg:`/
  `ent:`/`agent:` — the estate's OWN structure. It cannot express "give me
  pulse job run history" or "list events since timestamp X" because those
  live in `db:`/`svc:` namespaces that are `deferred` (Wing decides, KEAP
  never resolves) and today mostly have no handler at all. `mcp-wing` covers
  exactly that gap — Wing's own `/api/v1/*` surface (health, events,
  pulse_jobs) — and nothing in cortex-lang replaces it yet.
- A read that cortex-lang CAN express goes through more machinery per call
  (validate round-trip + binding check + dispatch) than a direct
  `GET /api/v1/pulse_jobs` — slower, and today most verbs beyond `get`/
  `resolve`/the four threaded ones don't execute at all, so a chain into
  `embed` or `delegate` returns `unavailable`/`confirm_required` where the
  REST tool would have just 404'd or worked.
- The win `exec` buys is not speed, it's a **guessable-vs-guaranteed**
  boundary: a cortex-lang sentence that parses is, by construction, a sentence
  the grammar allows — there is no invented endpoint to 404 on, because there
  is no endpoint, only opcodes the registry hash-compares at boot. `mcp-wing`
  has no such guarantee; the 404 that motivated this draft is a `mcp-wing`
  failure mode `exec` cannot reproduce for anything inside its vocabulary.
- Verdict: `exec` becomes the PRIMARY tool for anything ontology-shaped
  (taxonomy, entities, knowledge-graph, ranking/classification over that
  data, agent delegation once it binds); `mcp-wing`/`mcp-bone`/`mcp-pulse`
  stay for estate-operational reads (health, jobs, events) that cortex-lang's
  `db:`/`svc:` namespaces don't yet serve. Not a replacement — a narrowing of
  which questions reach for free-form REST at all.

## 5. Is a ~1B model plausible as the caller?

Measured so far: hermes3:8b 2/6 valid chains (failures were punctuation —
grammar-shaped, fixable by the model learning the surface syntax better) and
qwen3:14b 4/6 (failures were about the world — picking real operands, not
syntax). Neither number is from a model near 1B, and the two failure MODES
point in different directions: 8B failed at the grammar a 1B model would need
to nail even harder; 14B failed at world-knowledge a smaller model has even
less of.

`state/cortex-lang.gbnf` (grammar-constrained decoding) exists in the bench
but is **not wired into the runtime path** — AgentKit's `LLMClient` adapters
send plain tool-call JSON, no grammar/logit-bias constraint on the `chain`
field. For a 1B caller to be plausible, at minimum:

1. **GBNF (or an equivalent constrained-decoding hook) must move from bench
   to runtime** for this one tool's `chain` argument — it eliminates the
   8B-class punctuation failures by construction (the syntax failure mode
   simply becomes unreachable), which is the failure mode a 1B model would
   hit hardest.
2. **World-knowledge failures don't go away with grammar.** Constrained
   decoding guarantees a PARSING chain, not a chain over operands that
   exist — `unknown_operand` is still reachable and a 1B model needs either
   a short few-shot (the operator's own measurement: 0/6 → 2/6 on ONE
   in-prompt example) or a `resolve` pre-stage that turns fuzzy surface terms
   into real ids before the model has to name one directly.
3. **The tool's own error message is the model's only feedback loop** — since
   §3(a) forbids enumeration, a 1B model correcting `unknown_operand` has
   less to go on than a bigger model would infer from context. This cuts
   against plausibility unless `resolve` (which IS designed to map fuzzy
   terms to ids, non-enumerating by construction — it looks one up, it
   doesn't list what's there) is the model's default first stage rather than
   guessing `tax:`/`ent:` operands cold.

Net: plausible only as `constrained-decoding + resolve-first habit`, not as
"the same prompt, cheaper model." Neither precondition is built yet — this is
the honest gap between the direction and today's bench.

## Where this draft contradicts or sharpens the brief

- The brief describes mutating verbs as "refused at the door" — true, but the
  door is `mutating()` on the handler, checked by the dispatch loop, not
  something `CortexBindingGate` does; `confirm` therefore cannot be enforced
  inside the binding gate as one might assume from the call-order in §2 of
  the brief. It's a THIRD, separate check in the chain, after validate and
  binding, before per-stage dispatch.
- `unknown_operand`'s non-enumeration is not something `exec` has to newly
  build — it's already the D1 `unresolvable` policy in the KEAP registry
  (`kg:`/`ent:`), measured live (261/261 identical refusal). `exec`'s job is
  narrower than the brief implies: don't UNDO that guarantee by adding a
  helpful layer on top, not construct it from scratch.
