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
