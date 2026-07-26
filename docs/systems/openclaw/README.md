# OpenClaw

> Autonomous DevOps agent daemon on the host (persona "Inspektor Klepítko"). Runs
> long-lived agent loops against local Ollama models with the MLX backend; holds
> the tool permissions those loops act with. Non-Docker — a host launchd daemon.

## Quick Reference

| | |
|---|---|
| **Type** | Host organ (non-Docker), launchd daemon + Ollama MLX backend |
| **Domain** | `claw.<tenant_domain>` (e.g. `claw.dev.local`; Traefik file-provider route) |
| **Gateway port** | `18789` (loopback bind only) |
| **Stack** | `host` (synthetic bucket for `stack: null` manifest services) |
| **Toggle** | `install_openclaw: true` (default on) |
| **Manifest id** | `openclaw` → node `nos.host.openclaw` |
| **Install** | npm global package `openclaw` (via NVM); Ollama via Homebrew |
| **Config** | `~/.openclaw/openclaw.json` (dir `~/.openclaw/`, mode `0700`) |
| **Workspace** | `~/.openclaw/workspace/` (`SOUL.md`, `AGENTS.md`, `TOOLS.md`) |
| **Agents dir** | `~/agents/` |
| **Logs** | `~/agents/log/` |
| **Models** | `~/.ollama/models` (`ollama_models_dir`; persists across a blank on external SSD) |

Values read from `roles/pazny.openclaw/defaults/main.yml`,
`roles/pazny.openclaw/tasks/main.yml`, `state/manifest.yml`, and
`files/anatomy/plugins/openclaw-base/plugin.yml`.

## Backend

- **Inference:** Ollama `0.19+` with the MLX backend (Apple Silicon native), served at `http://127.0.0.1:11434`.
- **Primary model:** `qwen3-coder:30b` (`openclaw_model`; MoE, 256K context).
- **Additional model:** `qwen2.5-coder:32b` (dense coder, `openclaw_additional_models`).
- Ollama itself runs as the `com.ollama.agent` launchd LaunchAgent (env-carrying wrapper deployed by this role, replacing the brew-managed plist).

## Authentication

- **SSO bucket:** `forward_auth` (Authentik proxy/forward-auth gate at the Traefik layer).
- **RBAC tier:** Tier 1 (admin) — the operator's personal LLM infra.
- **Authentik provider:** slug `openclaw`, `client_id` `nos-openclaw` (Proxy Provider; no native OIDC).
- The gateway itself has no per-user identity; the Node.js gateway authenticates callers with a static gateway token bound to loopback. Authentik gates the `claw.<tenant_domain>` route only.

## Invocation

OpenClaw is driven through its CLI; see [SKILLS.md](SKILLS.md) for the callable
actions. The daemon is installed by `openclaw onboard --install-daemon` (launchd)
and the gateway binds `127.0.0.1:18789`.

## Health Check

No manifest `health_check` row is declared for OpenClaw. Liveness is checked via
the CLI (`openclaw health`) and, for the inference backend, the Ollama version
endpoint `GET http://127.0.0.1:11434/api/version` (expected `200`).

## Wing Integration

The role exports `WING_API_URL=http://127.0.0.1:9000` and a `WING_API_TOKEN`
into the launchd env and `~/.zshrc`, so agent runs can POST events to Wing
(source `agent:*`, A10 `actor_id` audit lineage).

## Dependencies

- Ollama (local inference backend; started by this role)
- Node.js via NVM (the `openclaw` npm package)
- Homebrew on Apple Silicon (ARM64)
- Authentik (SSO forward-auth gate, optional — only when `install_authentik` and a local TLD)
- Wing / Bone (optional event audit sink)
