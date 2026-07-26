# OpenClaw — Agent Definition

## OpenClawAgent

**System:** OpenClaw (host organ, non-Docker; persona "Inspektor Klepítko")
**Node:** `nos.host.openclaw`
**Role:** Autonomous DevOps agent daemon. Runs long-lived agent loops against local Ollama models and holds the tool permissions those loops act with.

### Context

- Gateway: `127.0.0.1:18789` (loopback), fronted by Traefik at `claw.<tenant_domain>` behind an Authentik forward-auth gate (Tier 1 admin).
- Inference backend: Ollama with the MLX backend at `http://127.0.0.1:11434`; primary model `qwen3-coder:30b`, dense delegate `qwen2.5-coder:32b`.
- Config: `~/.openclaw/openclaw.json`; workspace `~/.openclaw/workspace/` (persona `SOUL.md`, sub-agents `AGENTS.md`, allowed tools `TOOLS.md`).
- Logs: `~/agents/log/` (structured `.md` work records).
- Event sink: Wing at `http://127.0.0.1:9000` via `WING_API_TOKEN` (agent runs POST to Wing `/events`, A10 audit lineage).

### Capabilities

- Run the agent gateway (`openclaw gateway run`) and interactive TUI (`openclaw tui`).
- Report health (`openclaw health`).
- Read/update its own config (`openclaw config set … --strict-json`).
- Delegate to sub-agents (up to `openclaw_max_concurrent_subagents`, default 8).

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
