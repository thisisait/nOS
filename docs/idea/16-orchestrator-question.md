# 16 — The orchestrator question: which layer is ours

**Status: decision record, 2026-08-16.** The operator asked, verbatim: *"mám
tak trochu pocit, že vymýšlíme kolo — neměli bychom použít nějaký opensource
orchestrátor (něco jako LangChain)?"* The instinct deserves a real answer, and
half of it is right.

## 1. The evidence for the instinct, stated first

Four defects shipped in one week, every one in the LLM-plumbing layer:

| defect | layer | would a framework have prevented it? |
|---|---|---|
| loader regex delimiter inside its class → every agent rejected, silently, forever | URI validation (ours) | **half** — the URI scheme is ours and some validator would exist anyway, but the SILENCE is PHP's: `preg_match` returns false on a compile error; Python's `re` raises. Avoided by language, not by framework. |
| `create(...$params)` spreading `max_tokens` into a `$maxTokens` signature | SDK call convention (commodity) | **yes** — nobody calls vendor SDKs directly under a framework. |
| output cap 4096 truncating a writing ceremony mid-brief | default policy | **no** — every framework carries the same defaults; the fix (a per-agent cap) is policy, and policy is ours. |
| `getenv() ?: $default` reading a deliberate `0` as absent | config plumbing (ours) | **no** — `os.environ.get(x) or default` has the identical bug shape. Language-neutral footgun. |

Score: **~1.5 of 4** avoided by having adopted a framework in May. Against
that, a framework brings its own defect class — API churn (LangChain's
breaking-release cadence is notorious), a dependency surface the security
machine must scan, and a second place where behaviour is defined. The
instinct is right that the plumbing was reinvented and reinvented badly; the
arithmetic says the framework would have paid for at most half of this week's
bill.

## 2. The layer split, measured not felt

**Commodity (should not be hand-owned):** provider adapters, request
construction, retry/backoff, tool-schema translation, streaming, structured
output. ~1,100 LOC across four adapters + Factory. All four defects lived
here or adjacent. No differentiation, pure liability.

**Ours (exists in no framework, and is what the estate is FOR):** WORM
hash-chained audit lineage keyed on `actor_action_id`; per-agent Article-30
records that GATE routing (a binding refuses when the register does not name
the processor); prepared-not-armed derived from the registry; residency as a
property the record enforces (gate 8: `transfers_outside_eu: false` removes
the degrade path by its own force); the session ceilings checked before the
spend; fallback attribution written at answer time into a table with no
relabelling path. ~1,250 LOC of Runner+resolver, plus ~30 gate files.

**The welding:** the governance is not a wrapper today — audit emits inside
the tool loop, ceilings check before each call, attribution corrects at
session end. The PRE-loop seam (resolver, binding, register gates) is clean
and portable. The IN-loop welds need a host with veto-capable hooks;
observational callbacks (LangChain's) cannot refuse. *[CORRECTION
2026-08-17: the "observational callbacks" premise is 2024 folklore and is
stale — doc 17 §2 catalogues six of eleven surveyed hosts with veto-capable
refusal in 2026, and the LangGraph spike measured it: `langgraph==1.2.11`
driven by `tools/orchestrator-acceptance.py --host langgraph` (adapter
`tools/orchestrator_hosts/langgraph_host.py`) passed all four items —
abort before a model call (0 calls made), abort at an iteration boundary,
unretried exception propagation, and spend recorded on abort. Veto
capability no longer discriminates between candidates.]* LangGraph's
interrupts/checkpoints could host some of it. The welding is load-bearing
but not fused: a port is possible, not free.

## 3. What this week already did about it, quietly

The `OpenAiCompatAdapter` (ca2545f1) IS the exit from wheel-reinvention:
**one wire protocol reaches Mistral, DeepSeek, vLLM, Ollama — and a LiteLLM
proxy**, which reaches a hundred more with retries and spend tracking that
someone else maintains. The adapter is vendor-blank, byte-gated, and the
registry row is the unit of growth. The commodity layer stops growing by
hand as of this week — that is the operator's instinct, honoured in the
shape the estate already has.

## 4. The decision

1. **Adapter count freezes at three** (claude / anthropic / openai). A new
   provider is a registry ROW over the openai adapter — or a `local-litellm`
   row if breadth beyond that is ever wanted (cost: one more service + its
   CVE surface; benefit: someone else owns the client quirks). A fourth
   hand-written adapter requires this document to be rewritten first.
2. **The existing Runner is not ported.** Nine agents, ten ceremonies,
   governance welded and freshly byte-gated: porting buys ≈1.5 defects/week
   avoided — and the four holes are now gated shut — at 2–4 weeks of work
   plus revalidation of the gate estate. Bad trade today.
3. **The framework question is answered where it is cheapest: greenfield.**
   The loop driver (`loop-driver`, queued — the self-improvement engine's
   missing piece) does not exist yet, needs durable state, human-in-the-loop
   interrupts and checkpointing — which is LangGraph's exact shape — and
   Bone is already a Python organ, so a Python runtime is not a new class of
   thing. **When `loop-driver` starts, its first task is a one-week spike:
   LangGraph-in-Bone driving the weakness→propose→judge cycle against the
   existing Bone surfaces, governance gates called at the seams.** If the
   spike holds, new orchestration grows there and AgentKit's Runner serves
   the ceremony fleet until attrition retires it; if not, we build the
   driver by hand with this document as the record of why.
4. **Revisit triggers, written down so this is a decision and not a mood:**
   plumbing defects recurring after the byte-gates (prediction: they will
   not); multi-agent coordination or streaming demands exceeding what ~900
   LOC of loop can carry; the spike in (3) succeeding decisively.

---

## 5. Amendment 2026-08-18 — `dg/ai-access`, a third option the decision missed

The operator asked whether [`dg/ai-access`](https://github.com/dg/ai-access)
should be used or extended. It should, and the reason is that §4 answered a
question with only two candidates on the table.

**It is neither of the things §4 weighed.** It is not a framework that owns the
loop, so §2's "welding is load-bearing" objection does not apply to it. It is
also not a fourth hand-written adapter, so decision 1's freeze does not
prohibit it. It is a zero-dependency transport for precisely the list §2 called
**"no differentiation, pure liability"** — provider adapters, request
construction, retry/backoff, tool-schema translation, streaming, structured
output — and it touches nothing on the "ours" list.

**The seam is real, and its own API proves it rather than us hoping.** Omit the
tool handler and the caller drives the loop:

```php
$response = $chat->sendMessage('…');
foreach ($response->getToolCalls() as $call) {
    $chat->addToolResult($call, $result);   // WE execute; we emit; we check the ceiling
}
echo $chat->sendMessage()->getText();
```

That is the shape Runner already has. `Chat` becomes the wire plus the
conversation buffer; the iteration, the session ceilings, the synthesis turn
and every `agent_message` / `agent_tool_use` / `agent_tool_result` audit row
stay exactly where they are.

**What it would retire:** four adapters plus the factory (~1,100 LOC), the
`anthropic-ai/sdk: ^0.20` pin — a 0.x dependency is the churn risk §1 held
against LangChain, sitting in our own file — and `Grader::parseStrictJson`,
which strips ``` fences with a regex before `json_decode` and is what
"structured output" means. `getUsage()` also reports `reasoningTokens` and
`cacheReadTokens`, the latter a column `agent_sessions` has and no current
adapter fills.

**Fit that is not a coincidence:** same author as Nette, and Wing is Nette
throughout; `php: >=8.3` on both sides; New BSD; zero dependencies, so the
security machine gains one row and no transitive tree.

**The one thing it must never be allowed to do.** `Chat` also has an automatic
mode where you register handlers and it executes the round-trip itself. That
mode would move tool execution — and therefore the audit emission and the
pre-spend ceiling check — inside a library's loop. It is the ergonomic path,
it will look like the obvious way to write it, and it is the one shape that
gives away the property this estate exists for. Manual round-trip only.

### The spike, run the same day

`AiAccessAdapter` (one file, behind the two-method interface), three live round
trips against `api.minimax.io/anthropic`, ~600 tokens total:

```
round 1  stop=tool_use   roll({"sides":20})  id=call_function_618cgpmwtio4_1
round 2  stop=end_turn   "You rolled a **17**!"       ← stateless replay held
round 3  stop=end_turn   toolCalls=0                  ← tools withheld
```

Every open question above is now answered, and one assumption was wrong:

- **Binding works on BOTH dialects, and one would not have been enough.**
  `OpenAICompatible\Client` takes `baseUrl` as a constructor argument;
  `Claude\Client` takes it via `setOptions(customBaseUrl:)`. The paragraph
  above assumed the OpenAI-compatible client was the whole story — but
  `minimax` binds an **Anthropic-dialect** URL and `mistral` an OpenAI one, so
  a single-dialect adapter would have covered exactly one of the two armed
  backends. The adapter takes a `dialect` argument for this reason.
- **The stateless replay holds.** `send()` hands over the whole conversation
  each call and `Chat` is stateful; a fresh `Chat` per call with history
  replayed round-trips a tool call correctly, including `addToolResult()`
  resolving a call id out of the replayed turns.
- **Round 3 is the synthesis turn on borrowed rails** — passing no tools
  produces prose rather than another call, the same mechanism the Runner
  gained hours earlier for its own loop.
- `FinishReason` is richer than our four values, so the mapping narrows rather
  than stretches. `Unknown` maps to `error`, never `end_turn`: a provider we
  cannot read must not be recorded as one that said it was done.

The `claude` CLI backend is a subprocess and stays ours regardless.

**Found sideways, and worth more than the spike:** adding the dependency ran
`composer audit` for what appears to be the first time, and it reported a
**HIGH in `guzzlehttp/guzzle` 7.15.1** (CVE-2026-69246, noncanonical host
bypasses host-based checks; fixed in 7.15.2) plus a medium cookie-domain one.
Wing's own PHP tree — which runs the audit chain, the agent runtime and the
operator console — had never been audited by the security machine, which scans
Docker images and CVE feeds only. Lock bumped to 7.15.2, `composer audit
--locked` now clean; the class is filed as `docs/hidden_fees/17`. ai-access
itself contributed zero advisories, having zero dependencies.

**Decision: STEAL, scoped.** One spike file, `AiAccessAdapter implements
LLMClientInterface`, behind the two-method interface `test_agentkit_naming.py`
already pins — so the blast radius is one class and the gate estate is
unchanged. If it carries a real ceremony, the three HTTP adapters retire and
decision 1's freeze becomes moot rather than violated. This does not reopen
decision 3: `loop-driver` remains the greenfield question, and LangGraph
remains its candidate.
