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
