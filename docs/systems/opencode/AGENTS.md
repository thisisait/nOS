# OpenCode — Agent Definition

## OpenCode (operator tool, not an addressable agent)

**System:** OpenCode (host organ, non-Docker; sst.dev coding TUI)
**Node:** `nos.host.opencode`
**Role:** Agentic coding helper that edits files and runs commands inside a checked-out repository. It is an interactive terminal tool the operator launches on demand — not a daemon and not a delegate an orchestrator can dispatch to over an API.

### Context

- Binary: `/opt/homebrew/bin/opencode` (brew) or `~/.opencode/bin/opencode` (curl install).
- Config: `~/.config/opencode/opencode.json`.
- Provider: local Ollama at `http://127.0.0.1:11434/v1`; default model `ollama/qwen3-coder:30b`.
- No port, no domain, no SSO, no launchd daemon.

### Capabilities

- Interactive, in-repo coding sessions driven from the TUI.
- Model/provider switching via `/provider` or `--model`.

### Delegation Note

OpenCode is not a callable agent. For scriptable agent work, delegate to
OpenClaw or Hermes instead — they carry real skill surfaces (see their
`SKILLS.md`). See [SKILLS.md](SKILLS.md) for why OpenCode exposes none.
