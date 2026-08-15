# MiniMax backend — prepared, not armed

**Status: PREPARED, NOT ARMED (2026-08-12).** Every piece of plumbing to route the
scheduled agents through MiniMax's Anthropic-compatible endpoint is in place and
inert. Arming it is deliberately left to the operator because two decisions on
this page are the operator's to make, not an agent's — and because the switch
must not half-happen.

## What "prepared" means (the credential path, end to end)

Pasting a key into `credentials.yml` and converging is the ONLY remaining step to
arm the backend. The path, in the order a converge walks it:

1. **`default.credentials.yml`** carries `minimax_api_key: ""` — the empty default
   and the documented place to paste the real key (in the gitignored
   `credentials.yml`, which outranks it).
2. **`templates/secrets.yml.j2`** persists it to `~/.nos/secrets.yml` as
   `minimax_api_key`. Blank-safe: declared-and-empty resolves as an answer, so an
   unarmed estate carries an empty entry, not a missing one.
3. **`discover-pulse-catalog.py`** maps the `{{ minimax_api_key }}` token to the
   reference `secret:minimax_api_key` — never a value. This satisfies BOTH
   allow-lists that a token must clear (the catalog substitution table here, and
   the `job.env` dict forwarded wholesale by `roles/pazny.wing/tasks/post.yml`);
   the shape-based gate `test_minimax_prepared_not_armed.py` pins it, the same
   double-allowlist that dropped `args[]` in May and `curator_wing_api_token` in
   August.
4. The **Pulse daemon** resolves `secret:minimax_api_key` from `~/.nos/secrets.yml`
   at exec time, so the key reaches the agent process as `ANTHROPIC_AUTH_TOKEN`
   and is NEVER stored in `pulse_jobs.env_json` (AgentKit's `secret_ref` rule).

## What "not armed" means (the flag, and the injection)

`minimax_enabled: false` (in `default.config.yml`) is the master switch.

- `roles/pazny.wing/tasks/post.yml` renders `NOS_MINIMAX_ENABLED` from it (`'0'`
  when false) and passes it, plus the base URL and the two model remaps, to the
  catalog builder. Ansible renders these (the catalog cannot parse Jinja).
- `discover-pulse-catalog.py::_minimax_env()` returns `{}` unless
  `NOS_MINIMAX_ENABLED` is truthy. Off → nothing is injected into any job.
- When armed, the override rides on **every scheduled-agent job** (the ones that
  fork `pulse-run-agent.sh`) and on no other job:

  ```
  ANTHROPIC_BASE_URL:          <minimax_base_url>          # plain value
  ANTHROPIC_AUTH_TOKEN:        secret:minimax_api_key      # reference, resolved by Pulse
  ANTHROPIC_MODEL:             <minimax_model>             # alias remap (main tier)
  ANTHROPIC_SMALL_FAST_MODEL:  <minimax_small_model>       # alias remap (haiku tier)
  ```

  A job's own `env` wins on a key clash, so the injection only ADDS keys.

**It does NOT touch `~/.claude/settings.json`.** The operator shares that file with
their own interactive thread, and the requirement is explicit: every cloud agent
EXCEPT the operator's own thread. This backend applies only to the scheduled
Pulse agents, through their per-job env — nowhere near the operator's settings.

The cost-honesty half is already wired independently (readiness item 2):
`pulse-run-agent.sh` stamps `cost_basis: foreign:<host>` and DROPS the CLI's
dollar figure whenever `ANTHROPIC_BASE_URL` points off Anthropic, because that
figure is priced against the wrong table. Tokens are still recorded. So the day
MiniMax is armed, spend is reported truthfully (tokens + basis), never as a
fictional dollar amount.

---

## Decision 1 — third-party model under `--permission-mode bypassPermissions`

**The fact.** Both agent runtimes launch the inner CLI with
`--permission-mode bypassPermissions`, hardcoded:

- `files/anatomy/scripts/pulse-run-agent.sh:270`
- `files/anatomy/wing/app/AgentKit/LLMClient/ClaudeCliAdapter.php:98`

Its documented reason (both files) is sound for a non-interactive subprocess: the
runner cannot answer permission prompts, and the agent is already gated by
Authentik client-credentials + a scoped Wing bearer. So every Bash/curl the
ceremony issues runs without an inner gate.

**Why it is a decision now.** Today the model deciding which commands to run is
Anthropic's, under Anthropic's terms. Arming MiniMax means a **third-party-hosted
model** chooses those commands, running as the operator's UID, with bypassed
permissions, on the live estate. The trust boundary moves from "Anthropic's
model + nOS's Authentik/Wing gates" to "MiniMax's model + the same gates" — and
the same gates were sized for the former.

**The operator must decide** whether that is acceptable as-is, or whether a
foreign backend should run under a tighter inner posture — e.g. a non-bypass
permission mode with an allow-list, or a reduced tool set — for the scheduled
agents specifically. This is not an agent's call to make; it is a change in who
is trusted to run commands as the operator.

## Decision 2 — the error classifiers speak only Anthropic

**The fact.** Transient-vs-permanent classification is by **string match on
Anthropic's phrasings**, in two places:

- `ClaudeCliAdapter.php:171-173` — `stripos($message, 'rate limit')`,
  `'overloaded'`, `'usage limit'` → `LLMTransientError` (retried); anything else
  → `LLMPermanentError` (not retried).
- The shell path in `pulse-run-agent.sh` classifies only by **exit code**
  (`NOS_AGENT_EXIT` sentinel + non-zero), with the A9 notification severity
  keyed off the exit — it has no phrase matching, so a MiniMax throttle that
  exits non-zero is notified but its transience is never inferred.

**Why it is a decision now.** MiniMax's endpoint will phrase its throttle,
overload and quota responses in its own words. A MiniMax rate-limit whose message
is not one of the three Anthropic phrases is classified **permanent** and NOT
retried — the first outage would be misread as a bad flag and give up, exactly
when a retry is what the situation wants.

**The operator must decide** whether to teach the classifier MiniMax's strings
(and which ones) before arming, or to accept the first outage as the way to learn
them. This is a judgement about MiniMax's actual error surface, which the operator
can see and an agent cannot.

## Arming gotcha to resolve alongside the decisions

`pulse-run-agent.sh` passes `--model <alias>` from the per-job `NOS_AGENT_MODEL`
pin (haiku/sonnet/opus). The CLI's `--model` flag **outranks** `ANTHROPIC_MODEL`,
so the alias remaps above do not take effect while `--model` is passed. Arming
therefore also requires deciding how `NOS_AGENT_MODEL` routes under a foreign
backend — e.g. drop the `--model` flag when `ANTHROPIC_BASE_URL` is set and let
`ANTHROPIC_MODEL`/`ANTHROPIC_SMALL_FAST_MODEL` drive, or carry the MiniMax model
id directly in `NOS_AGENT_MODEL`. Left to the operator so the six deliberate tier
pins (readiness item 3) are re-decided consciously, not silently rerouted.

---

# The rulings (operator, 2026-08-12)

All three decisions above are SETTLED. What follows is what was decided, and —
because a fifth review pass went looking for what the rulings imply — what each
one turned out to require that the decision itself did not say.

## Ruling 1 — the switch is per job, at maximum granularity

Ceremonies that only read KEAP APIs and write text may route to MiniMax.
Ceremonies that AUTHOR CODE (`recipe-author`, `promote-migration`, both
`opus`-pinned) stay on Anthropic until the inner posture is tighter. The switch
is never estate-wide.

**THE CRITERION NEEDS A SECOND AXIS, and this is the correction the ruling did
not survive first contact without.** "Authors code vs. writes text" is one axis:
output capability. It classifies `triage-open-findings` as MiniMax-eligible —
and that ceremony is the single most sensitive READER in the fleet. It does not
read the CVE queue (that travels via `scan-runner.sh`, which never meets the
injection); it reads gitleaks findings, whose rows carry git author name and
email, and then `cat`s the file around every leak site ±4 lines — the plaintext
neighbourhood of every unresolved secret leak. So a ceremony qualifies on
capability AND on data sensitivity, and either axis alone routes it wrong.

**WHAT WAS BUILT COULD NOT EXPRESS THIS — RESOLVED 2026-08-13 (spine
increment 1).** The history: `discover-pulse-catalog.py` injected the override
into every `pulse-run-agent.sh` job, and the old
`test_minimax_prepared_not_armed.py` asserted that estate-wide shape — the
gate enforced what the ruling forbids; the env-clash escape could override
`ANTHROPIC_BASE_URL` but never REMOVE the injected token, and a new ceremony
landed on MiniMax silently (fail-open). All of that is gone. The ruling now
lives as a **per-agent binding**:

- `model.backend: minimax` in `files/anatomy/agents/<name>/agent.yml` — the
  declaration, per agent, never estate-wide.
- `state/llm-backends.yml` — the closed backend registry and the six
  fail-closed gates, prose and all.
- `App\AgentKit\LLMClient\BindingResolver` — the gates as running code:
  registry membership, arming via `NOS_ARMED_BACKENDS` (wing.plist, rendered
  from `minimax_enabled`), **agreement with the agent's own Article-30
  record** (the second axis, read from the register rather than duplicated —
  a routing the register does not declare REFUSES the session), deferred
  agents refused, opus-tier refused (the code-authoring carve-out), and an
  armed backend with no model id refused.
- The catalog carries **no backend env at all**, armed or not — the
  shell-bridge ceremonies always run on the default backend, which makes the
  fail-open default fail-closed. Gates:
  `test_minimax_prepared_not_armed.py` (rewritten once, as predicted),
  `test_a_binding_reads_the_register.py` (declared data vs the register),
  `test_binding_resolver_effects.py` (the PHP, executed).

What still waits on the supervised night: an actual ceremony routed through
AgentKit under a binding, and the per-ROUTED-agent MiniMax processor entry in
its gdpr block (see item 1 below).

**THE SPINE REDIRECT (operator, 2026-08-15), and what it changed here.** The
night's first attempt found `spine-tools-vs-cli-refusal`: every agent declares
tools, the CLI adapter refuses tool schemas (rightly — it cannot honour them),
and the Runner rethrows a capability refusal without fallback (also rightly).
Three correct decisions, one deadlock: AgentKit could run NO agent through the
CLI. The operator's direction: **primarily the classic API** — where
`AnthropicAdapter` speaks the tool protocol and AgentKit's own Runner drives
the loop, so the refusal dissolves structurally — with Claude as only ONE of
the permitted highest-level orchestrators (mechanically: one row in
`state/llm-backends.yml`, which IS the permitted-orchestrator list; see its
header). The binding layer built for the CLI carried over unchanged in
doctrine and mostly in code: the API adapter is now the primary bindable one
(base_url + bearer + tier-remapped model id, `model_effective` stamped at
session start), the CLI binding remains for tool-less ceremonies, and the
tier carve-out follows the TIER, not the adapter — an opus-tier agent refuses
a foreign binding on every path, or switching provider would be the bypass.
The tmux idea (interactive CLI as an agent surface) was assessed and does NOT
enter this increment: an agent that can type into an interactive session can
answer its own permission prompts, which converts the permission system into
a formality, and the path yields no structured envelope for the audit trail —
if ever wanted, it needs its own threat model and a dedicated runner.

## Ruling 2 — fail-closed classification, with the unmatched message logged

An error phrase the classifier does not recognise stays PERMANENT (not retried).
Retrying a real configuration fault forever is worse than losing one night. The
unmatched message is logged so MiniMax's actual phrasings can be learned from one
outage instead of guessed from documentation nobody verified.

**THE GENUINELY UNLOGGED THING IS NOT THE MESSAGE — IT IS THE FALLBACK.** An
unmatched phrase becomes `LLMPermanentError`, which falls back immediately with
no retry, and the fallback's answer is returned with NO RECORD that it answered:
`model_uri` is written once at session open from the PRIMARY. All nine profiles
declare `openclaw-qwen2.5-coder:32b`. So the first MiniMax throttle yields output
authored by a 32B local model, recorded as the primary's — and `events` rows are
WORM-triggered and hash-chained, so the mislabel is permanent by construction.
The RFL corpus has no writer yet and no provider field, so provenance must be
right AT WRITE TIME; there is no relabelling later. Record the identifier of the
client that actually answered, and emit a fallback event.

## Ruling 3 — no `--model` when `ANTHROPIC_BASE_URL` is set

`--model` outranks `ANTHROPIC_MODEL`, so the alias remaps a foreign backend needs
would not take effect while the flag is passed. With the flag dropped,
`ANTHROPIC_MODEL` / `ANTHROPIC_SMALL_FAST_MODEL` drive.

**THE TIERS COLLAPSE UNLESS PER-JOB OVERRIDES ARE PERMITTED.** One global
`ANTHROPIC_MODEL` erases the haiku/sonnet distinction the six deliberate pins
express. Note `test_agent_jobs_pin_model.py` hard-codes `{haiku,sonnet,opus}` and
would refuse a MiniMax id in `NOS_AGENT_MODEL` — the gate agrees with this ruling
and refuses the alternative. Deeper: the pulse path records
`model_uri = 'cli:unrecorded'` by design, so once armed, NOTHING anywhere records
which backend or model served a run except `cost_basis` on the end event. Stamp
the effective backend and model into the run-end event when arming.

**RESOLVED 2026-08-13 (spine increment 1), on the only path that can arm.**
`ClaudeCliAdapter` under a binding passes NO `--model` and drives via
`ANTHROPIC_MODEL` carrying the binding's tier-resolved id — measured at the
argv line by `test_binding_resolver_effects.py::test_ruling_3_at_the_argv_line`,
both directions. The tiers survive because the resolver maps each agent's own
tier (`claude-haiku`/`claude-sonnet`) through the registry's `model_env`
per run; `opus` maps to null by ruling 1. The shell-bridge path keeps
`--model` and needs no drop rule anymore: the catalog injects no
`ANTHROPIC_BASE_URL`, so the conflict this ruling resolves cannot arise there.
The write-time stamp (backend + effective model in `agent_run_end`) shipped
2026-08-13 in `pulse-run-agent.sh` (gate
`test_runner_child_env_and_attribution.py`).

## What must happen before arming, in order

1. ~~The Art-30 / DPA register work.~~ **DONE 2026-08-13** for the Anthropic
   half, which was the part that was already false. Eight ceremonies now carry
   their own `gdpr:` block in `files/anatomy/agents/<name>/agent.yml`, swept by
   `nos_gdpr.records_from_agents()`; the register went from 79 records / 0
   processors / 0 EU exits to 88 / 8 / 8. Gate:
   `tests/anatomy/test_a_ceremony_declares_its_processor.py`.

   **WHAT ARMING MINIMAX ADDS, and it is not one edit.** A second processor
   entry must be appended to the `gdpr.processors` list of EACH agent routed to
   it — per agent, because ruling 1 routes per job, so the register would be
   false if it declared the transfer estate-wide. `agent_remediator` is the
   named exception: its record already carries the routing consequence, that
   its data categories (leak neighbourhoods, commit-author identity) fail the
   sensitivity axis for any additional recipient. `agent_inspektor` is the
   other one to re-read — it declares `processors: []` truthfully today only
   because `runner_status: deferred`, and its own note says so.

   Do NOT pre-declare MiniMax before it is armed: a record asserting a transfer
   that does not occur is wrong in the same way the empty list was, just
   pointing the other direction.
2. ~~`w-agentkit-spine`, which is where rulings 1 and 3 acquire a place to
   live.~~ **THE NON-SUPERVISED HALF SHIPPED 2026-08-13**: rulings 1 and 3 now
   live in the binding layer (`state/llm-backends.yml` +
   `App\AgentKit\LLMClient\BindingResolver` + `model.backend` per agent.yml —
   see ruling 1's resolution above for the map). What remains of the spine row
   is the operator-supervised half: a parallel-run night proving a real
   ceremony through AgentKit, then the Pulse cutover. Arming MiniMax for an
   agent is, in full: paste the key (credentials.yml) · converge · set
   `minimax_enabled: true` + the two model ids (config.yml) · declare
   `model.backend: minimax` in that agent's agent.yml · append the MiniMax
   processor entry to that agent's gdpr block — and the resolver refuses any
   subset that disagrees.
3. The env-withholding hardening — **half shipped 2026-08-13, half was wrong as
   written.** `NOS_AGENT_CLIENT_SECRET` is genuinely runner-only (the runner
   exchanges it for a scoped token before the spawn) and is now withheld from
   the child — gate `tests/anatomy/test_runner_child_env_and_attribution.py`.
   But `WING_EVENTS_HMAC_SECRET` is NOT withholdable today, measured: the
   conductor profile (`files/anatomy/agents/conductor.yml:43`) instructs the
   ceremony to POST its own attributed events, Bone's `/api/v1/events` accepts
   only HMAC, and the live `conductor_report` of 2026-08-09T04:04:25Z sits
   between `agent_run_start` and `agent_run_end` — the child signed it with
   the inherited secret. So the model is handed the key that derives the audit
   chain (`AuditChain.php:56`: a holder "can recompute the whole chain
   undetectably") *because the events endpoint gives its report no other door*.
   The withholding of this one lands with the spine: the runtime posts the
   report (or the events POST learns bearer auth), then the secret leaves the
   child env and the gate's documented assertion flips.
