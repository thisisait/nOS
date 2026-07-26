# OpenCode — Skills

> **No external skill surface.** This file deliberately declares no `**Trigger:**`
> actions, so it ingests as honest notes rather than invocable skills.

## No Invocable Surface

OpenCode is an interactive agentic coding TUI, not a service. It has no daemon,
no listening port, no domain, and no REST/HTTP API. It is launched by the
operator in a project directory (`opencode`) and then driven interactively
inside the terminal UI — an agent cannot script it by reading a card alone, so
there are no skills to expose.

The only invocation is the launch itself, documented as plain commands in
[README.md](README.md) (`opencode`, `opencode --model …`, `opencode --version`,
`/provider` inside the TUI). These are not agent skills — inventing HTTP
endpoints for them would be a confident-wrong answer, which is exactly the
failure this corpus removes.

## Where OpenCode's Capability Lives

OpenCode's real work happens through its configured provider — the local Ollama
endpoint at `http://127.0.0.1:11434/v1`. Agent-facing model calls belong to that
backend, not to OpenCode. If you need a scriptable coding agent with callable
actions, use OpenClaw (gateway/CLI) or Hermes (CLI + MCP), which do expose
skills.
