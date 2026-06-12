---
id: 2026-05-07-agentkit-runtime
title: "A14: AgentKit, a self-hosted agent runtime where the audit trail is the product"
date: 2026-05-07
namespace: nos-core
summary: "Anatomy A14 reimplemented the Anthropic Managed Agents surface — agent, session, thread, outcome, vault, webhook — as PHP inside Wing, with every byte of state in wing.db. One actor_action_id query reconstructs an entire agent run; one URI line in agent.yml swaps the LLM backend. The conductor agent shipped first."
tags: [agents, agentkit, wing, audit]
actors: [pazny, claude]
related: [docs/ait-runtime-architecture.md, files/anatomy/agents/conductor]
---
## Why not just use the hosted thing

Anthropic Managed Agents has beautiful primitives — agents, sessions,
threads, graded outcomes, credential vaults, webhooks. It is also a hosted
runtime: the reasoning and the audit trail live in someone else's cloud.
That collides head-on with two nOS constraints. The platform doctrine is
"every service FOSS, all data local", and the whole point of OpenClaw is
that a local model must be able to take over an agent definition without a
rewrite. A session that lives in a vendor's cloud can't transparently flip
to a Mac Studio running MLX.

So A14 kept the concepts and rebuilt the runtime: `App\AgentKit\*` in PHP
under Wing, every byte of state in `wing.db` SQLite. Six tables —
`agent_sessions`, `agent_threads`, `agent_iterations`, `agent_vaults`,
`agent_credentials`, `agent_subscriptions` — plus twelve new event types.

## Audit-first means one query rebuilds the run

The design center isn't the agent loop, it's the lineage. Every LLM call
produces three artefacts: an `events` row (the grep surface), an OTel span
exported to Tempo via Alloy on 4318 (the cross-tool view), and a token tally
on `agent_sessions` (the cost surface). Every event carries
`actor_action_id = agent_sessions.uuid`, so

```sql
SELECT type, ts, result_json FROM events
WHERE actor_action_id = '<session_uuid>' ORDER BY ts;
```

returns the entire run — every tool use, every message, every grader
verdict. The explicit goal: a *future* LLM can replay the trail and judge
whether the agent's decisions were correct, without re-running anything.
Three identity layers stay distinct on purpose: the Authentik client
(`agent:conductor`, external SSO realm), the session UUID (wing.db grouping
key), and the W3C trace_id (Tempo deep-link from the Wing UI).

## The portability bet: a one-line model URI

`agent.yml::model.primary` is a single dash-separated URI —
`anthropic-claude-opus-4-7`, `openclaw-qwen-coder-32b`. `Factory::fromUri`
splits on the first dash and dispatches to an adapter; the `LLMClient`
interface is deliberately two methods (`identifier()`, `send()`), and a CI
gate fails the build if anyone widens it. Swap the backend, and the system
prompt, tool roster, audit trail, spans, and grader logic all stay
identical. Secrets follow the same discipline: `agent_credentials.secret_ref`
is never plaintext — it's an `env:` or `infisical:` pointer resolved at
session-open, with plaintext living only in function-local memory.

The outcome loop borrows Anthropic's grader isolation: a separate LLM call
scores the transcript against a markdown rubric and returns strict JSON. The
grader never sees the working agent's reasoning, so it can't be talked into
"satisfied" by clever prose.

## First agent: conductor

The first profile in `files/anatomy/agents/` is `conductor` — the platform
self-test ceremony. It hits Wing's hub-health and Pulse APIs, reports under
a fixed `## Conductor report` heading, and gets graded against
`rubric.md` for evidence discipline. Eight anatomy CI gates pin the design:
schema validation, table presence, the 2-method protocol, the dash-URI
scheme, the canonical lifecycle events.

## Where it stands

The post-A14 "deferred" list didn't stay deferred long: the multi-agent
process pool, Dreams memory consolidation, operator-trigger UI, Infisical
vault resolution, and per-agent webhook fan-out all shipped within the week
(Track B). Conductor, Scout, and Remediator run live today; the scheduled
closed-loop conductor — the nerve that fires itself on a cadence — is still
queued, by design rather than by accident.
