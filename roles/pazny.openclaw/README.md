# pazny.openclaw

Ansible role for deploying **OpenClaw** (Inspektor Klepítko) — a self-hosted AI agent running 100% locally on Apple Silicon with an [Ollama](https://ollama.com) MLX backend. Part of [devBoxNOS](../../README.md).

OpenClaw is devBoxNOS' autonomous DevOps agent. This role installs Ollama, pulls the primary model, installs the `openclaw` npm package, performs non-interactive onboarding against the local Ollama endpoint, and deploys the agent workspace (persona, sub-agents, tools, logs).

## What it does

1. Installs/upgrades Ollama via Homebrew (Ollama 0.19+ auto-selects the MLX backend on Apple Silicon)
2. Exports Ollama tuning env vars via `launchctl setenv` and starts `ollama` as a brew service
3. Waits for the Ollama HTTP API to come up and pulls the configured primary model (async, 30-minute timeout)
4. Installs the `openclaw` CLI globally via NVM-managed npm if missing
5. Creates the agentic directory tree (`~/agents`, `~/agents/log`, `~/projects`, `~/.openclaw/workspace`)
6. Runs `openclaw onboard --non-interactive` against the local Ollama endpoint on first run (installs launchd daemon)
7. Sets `agents.defaults.maxConcurrent` via `openclaw config set`
8. Deploys persona (`SOUL.md`), sub-agents (`AGENTS.md`), allowed tools (`TOOLS.md`), log template and `onboard.sh` script from `files/openclaw/`
9. Injects Ollama env vars into `~/.zshrc`, tightens `~/.openclaw` permissions to `0700`
10. Creates a default nginx project landing page under `~/projects/default/`

Notified handler `Restart openclaw` kicks the launchd agent `com.openclaw.agent`.

## Requirements

- macOS with Homebrew on Apple Silicon (ARM64)
- Node.js via NVM (handled by the main devBoxNOS playbook)
- `community.general` collection for the `homebrew` module
- The `files/openclaw/` and `files/project-openclaw/` trees staying inside the playbook repo
- Play-level handler `Restart openclaw` defined in the consuming playbook (a role-local copy is also provided)

## Variables

| Variable | Default | Description |
|---|---|---|
| `openclaw_user` | `{{ ansible_facts['user_id'] }}` | Host user running the agent |
| `openclaw_base_dir` | `{{ ansible_facts['env']['HOME'] }}` | Base home directory |
| `openclaw_agents_dir` | `~/agents` | Agent install / config directory |
| `openclaw_projects_dir` | `~/projects` | Nginx-hosted projects root |
| `openclaw_log_dir` | `~/agents/log` | Structured `.md` work logs |
| `openclaw_config_dir` | `~/.openclaw` | OpenClaw config directory |
| `openclaw_model` | `qwen3:14b` | Ollama primary model (MLX optimized for 36GB RAM) |
| `ollama_max_loaded_models` | `1` | Max models kept in RAM |
| `ollama_num_parallel` | `2` | Max parallel inference requests |
| `ollama_keep_alive` | `5m` | Release model from RAM after idle |
| `ollama_flash_attention` | `1` | Flash attention (faster, less memory) |
| `openclaw_install_daemon` | `true` | Install launchd daemon on onboarding |
| `openclaw_domain` | `claw.dev.local` | Public hostname for the nginx vhost |
| `openclaw_gateway_port` | `18789` | OpenClaw gateway listen port (loopback) |
| `openclaw_agent_name` | `Inspektor Klepítko` | Persona name |
| `openclaw_max_concurrent_agents` | `4` | Max concurrent agents |
| `openclaw_max_concurrent_subagents` | `8` | Max concurrent sub-agents |

## Usage

In the consuming playbook:

```yaml
- import_role:
    name: pazny.openclaw
  when: install_openclaw | default(false)
  tags: ['openclaw', 'ai', 'agent']
```

## Rollback

Revert the commit that introduced this role and restore `tasks/openclaw.yml` + the `import_tasks` call site in `main.yml`. The installed Ollama brew formula, the pulled model data (`~/.ollama/models/`), and the `~/.openclaw/` workspace are left untouched — remove them manually if a full cleanup is desired (`brew uninstall ollama`, `rm -rf ~/.openclaw ~/.ollama`).
