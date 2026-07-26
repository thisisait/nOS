# OpenCode

> Agentic coding TUI (sst.dev) wired to a local Ollama provider. It works inside
> a checked-out repository — editing files and running commands — rather than
> serving a browser session. Non-Docker, no daemon, no port: an on-demand
> terminal tool the operator launches in a project directory.

## Quick Reference

| | |
|---|---|
| **Type** | Host organ (non-Docker), on-demand TUI binary — no daemon, no port, no domain |
| **Stack** | `host` (synthetic bucket for `stack: null` manifest services) |
| **Toggle** | `install_opencode: false` (default off) |
| **Manifest id** | `opencode` → node `nos.host.opencode` |
| **Version source** | Homebrew formula `opencode` (fallback: upstream `curl … \| bash` installer at `https://opencode.ai/install`) |
| **Binary** | `/opt/homebrew/bin/opencode` (brew) or `~/.opencode/bin/opencode` (curl install) |
| **Config** | `~/.config/opencode/opencode.json` (mode `0600`) |

Values read from `roles/pazny.opencode/defaults/main.yml`,
`roles/pazny.opencode/tasks/main.yml`, and `state/manifest.yml`.

## Provider

- **Ollama (local, OpenAI-compatible):** `http://127.0.0.1:11434/v1` (no API key).
- **Default model:** `ollama/qwen3-coder:30b` (`opencode_default_model`).
- **Available models:** `qwen3-coder:30b`, `qwen2.5-coder:32b`, `hermes3:8b`, `qwen3:14b`.
- **Optional providers:** Anthropic (when `anthropic_api_key` is set) and OpenAI (when `openai_api_key` is set) — both off unless a key is provided.

## Authentication

- **SSO bucket:** none. OpenCode is a local terminal tool run by the operator; it has no web surface, no manifest `domain_var`/`port_var`, and no Authentik provider.

## Invocation

OpenCode is launched interactively in the current project directory:

- `opencode` — open the TUI in the current repo.
- `opencode --model ollama/hermes3:8b` — launch with a specific model.
- `opencode --version` — print the installed version.
- `/provider` — switch provider/model from inside the TUI.

There is no agent-facing API; see [SKILLS.md](SKILLS.md).

## Dependencies

- Ollama (local inference backend, at `127.0.0.1:11434/v1`)
- Homebrew on Apple Silicon (ARM64), or the upstream curl installer
