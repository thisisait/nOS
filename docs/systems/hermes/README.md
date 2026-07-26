# Hermes

> Cross-channel agent gateway (Nous Research Hermes Agent). Bridges outside chat
> channels — Telegram, Discord, Signal — into the estate's agent runtime, and
> exposes a FastAPI dashboard plus an MCP server. Non-Docker — a host daemon,
> sibling of OpenClaw. Its web UI daemon is opt-in and OFF by default.

## Quick Reference

| | |
|---|---|
| **Type** | Host organ (non-Docker), Python daemon + Ollama MLX backend |
| **Domain** | `hermes.<tenant_domain>` (e.g. `hermes.dev.local`; Traefik file-provider route) |
| **Web UI port** | `18790` (`hermes_web_port`), bound `127.0.0.1` (loopback) |
| **Stack** | `host` (synthetic bucket for `stack: null` manifest services) |
| **Toggle** | `install_hermes: false` (default off) |
| **Web daemon toggle** | `hermes_daemon_mode: false` (opt-in launchd web UI; default off) |
| **Manifest id** | `hermes` → node `nos.host.hermes` |
| **launchd label** | `eu.thisisait.nos.hermes` |
| **Install** | git clone `NousResearch/hermes-agent` @ `v2026.4.16` → `uv pip install -e .` |
| **Home** | `~/agents/hermes/` (venv `~/agents/hermes/.venv`) |
| **Config** | `~/.hermes/` (CLI config, `memory.json`, `skills/`) |
| **Logs** | `~/agents/log/` |

Values read from `roles/pazny.hermes/defaults/main.yml`,
`roles/pazny.hermes/templates/{hermes.plist.j2,cli-config.yaml.j2}`,
`state/manifest.yml`, and `files/anatomy/plugins/hermes-base/plugin.yml`.

## Backend

- **Inference:** Ollama at `http://127.0.0.1:11434` (OpenAI-compatible `/v1`).
- **Primary model:** `hermes3:8b` (orchestrator + MCP caller + tool calls).
- **Heavy delegate:** `qwen2.5-coder:32b` (dense coder, shared with OpenClaw).
- **Optional external delegation (OFF by default):** Anthropic API (`hermes_anthropic_api_key`) and the Claude Code CLI (`hermes_claude_code_enabled`). Enabling Anthropic delegation transfers prompts outside the EU — update the GDPR row accordingly.

## Authentication

- **SSO bucket:** `forward_auth` (Authentik proxy/forward-auth gate at the Traefik layer).
- **RBAC tier:** Tier 1 (admin) — the operator's personal agent gateway.
- **Authentik provider:** slug `hermes`, `client_id` `nos-hermes` (Proxy Provider; no native OIDC).
- The FastAPI web UI has no native login of its own; once past the Authentik gate it is effectively 0-click for the operator.

## Web UI / API

When `hermes_daemon_mode: true`, the launchd unit self-starts the FastAPI
dashboard via `hermes dashboard --host 127.0.0.1 --port 18790 --no-open`
(loopback only; Traefik fronts the route). No manifest `health_check` row is
declared, so no HTTP health endpoint is asserted here.

## MCP

Hermes is an MCP client that connects directly (stdio) to these servers:
`filesystem`, `git`, `fetch`, `memory`, `time` (see `hermes_mcp_servers`). It can
also expose its own conversations as an MCP server (`hermes mcp serve`).

## Dependencies

- Ollama (local inference backend, at `127.0.0.1:11434`)
- Python 3.11+ with `uv` (git-clone install into a venv)
- Homebrew on Apple Silicon (ARM64)
- Authentik (SSO forward-auth gate, optional)
- MCP server binaries via `npx` / `uvx` (filesystem, git, fetch, memory, time)
