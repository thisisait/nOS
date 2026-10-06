# OpenHuman — tonight's local-only test (roadmap `openhuman`, step 0)

Desktop OpenHuman on this Mac, local model only, nOS tables read-only. Do the steps in order.
1. **Network guard first.** Little Snitch (or LuLu): before first launch, add a rule
   *OpenHuman → deny all, allow 127.0.0.1/localhost*. The config below is not a guarantee
   (the app still makes control-plane calls); the firewall is.
2. **Model.** `ollama list` must show `hermes3:8b` (the estate's host-safe size: 14B starves
   KEAP — `ollama_small_model` in `default.config.yml`). If missing: `ollama pull hermes3:8b`.
3. **Install (habitat, not symbiont).** nOS has no symbiont cask list: `software_owner` maps
   `homebrew_cask_apps` and `install_cask_apps` to `habitat`, and `homebrew_symbiont_packages`
   holds formulae only (there is no `openhuman` formula). Add to `config.yml`:
   `install_cask_apps: true` and `homebrew_cask_apps: [openhuman]`, then run
   `ansible-playbook main.yml --tags homebrew`. That list REPLACES the default one (VS Code,
   Ghostty, …): list any of those you also want, or nOS installs only OpenHuman.
4. **Write the config before first launch** — `~/.openhuman/users/local/config.toml`:

```toml
default_model = "hermes3:8b"
chat_provider = "ollama:hermes3:8b"
reasoning_provider = "ollama:hermes3:8b"
agentic_provider = "ollama:hermes3:8b"
coding_provider = "ollama:hermes3:8b"

[privacy]
mode = "local_only"          # refuses every cloud model, web search, integration, cloud embedding
[observability]
analytics_enabled = false    # Sentry + product analytics (default true)
share_usage_data = false     # agent-run traces to their Langfuse (default true)
[update]
enabled = false              # the core's own periodic check
rpc_mutations_enabled = false
[gitbooks]
enabled = false              # a REMOTE MCP server (tinyhumans.gitbook.io), on by default
[memory.conversations]
enabled = false              # memory off: no turn log, no recall pack
[memory.recall]
enabled = false
[local_ai]
runtime_enabled = true
opt_in_confirmed = true
provider = "ollama"
base_url = "http://127.0.0.1:11434"
chat_model_id = "hermes3:8b"
num_ctx = 8192
```

   Ollama's native runtime takes the host root, not `/v1`. The OpenAI-compatible
   `http://127.0.0.1:11434/v1` (the estate's `ollama` row in `state/llm-backends.yml`) is
   OpenHuman's `local-openai` route, which is set by env (`LOCAL_OPENAI_URL`) — the headless
   core's path, not the desktop's. A file with no `schema_version` is migrated on load:
   after launch, re-read it with `tools/openhuman-status.py` (step 9).

   **Desktop updater: no documented switch; the app will update itself** (Tauri updater →
   `github.com/tinyhumansai/openhuman/releases/latest/download/latest.json`; the cask is
   `auto_updates true`). The firewall rule is what stops it tonight.
5. **Launch, and do not sign in.** Sources say two different things. The docs
   ([Getting Started](https://github.com/tinyhumansai/openhuman/blob/main/gitbooks/overview/getting-started.md))
   describe only "Sign in! Let's Cook" and an Advanced core-URL panel. The current Welcome
   screen ([Welcome.tsx](https://github.com/tinyhumansai/openhuman/blob/main/app/src/pages/Welcome.tsx))
   has a second card, **"Set it up myself" — "Bring your own API keys and endpoints."**,
   which starts a local session (user id `local`, an unsigned token, no backend). Click
   that. In the wizard choose Ollama for inference, leave web search and memory off.
   macOS will ask for Accessibility / Input Monitoring: grant Accessibility only if you
   want screen actions tonight; leave the voice hotkey off (speech-to-text is never local).
6. **Imprint.** OpenHuman loads `AGENTS.md` from its workspace into the system prompt. Copy
   `IMPRINT.md` (repo root, branch `feat/imprint`, not yet on `dev`) to
   `~/.openhuman/users/local/workspace/AGENTS.md`. Settings → Persona edits `SOUL.md`
   beside it; leave that alone.
7. **nOS tables (MCP, read-only).** Connections → MCP Servers → **mcp.json** tab:

```json
{ "mcpServers": { "nos-tables": {
  "command": "/bin/sh",
  "args": ["-c", "KEAP_AGENT_TOKEN_RO=$(/usr/local/bin/docker exec iiab-keap-1 printenv KEAP_AGENT_TOKEN_RO) NOS_MCP_AGENT=openhuman exec /usr/bin/python3 /Users/pazny/projects/nOS/tools/mcp-tables-server.py"]
} } }
```

   The RO token is read from the KEAP container at spawn (same source as
   `tools/local-model-bench.py`), so it is never stored in OpenHuman's `mcp_clients.db`.
   `KEAP_API_URL` defaults to `http://127.0.0.1:8091`. **Never give it
   `KEAP_AGENT_TOKEN_RW`** — `tools/openhuman-status.py` goes RED if that name appears.
8. **nOS skills.** Compatible format: OpenHuman reads agentskills.io-style bundles (a
   directory with `SKILL.md`, YAML frontmatter `name` + `description`, Markdown body) from
   `~/.openhuman/skills`, `~/.agents/skills` and the workspace; nOS skills are that shape
   (`metadata.nos` is extra and ignored). Symlinks are rejected, so copy:
   `mkdir -p ~/.openhuman/skills && cp -R files/anatomy/skills/nos-datatables ~/.openhuman/skills/`.
   Difference: OpenHuman runs a skill as a separate agent run (`run_workflow`), not as
   instructions inside the chat; the MCP server in step 7 is the part that does the work.
9. **Check.** `tools/openhuman-status.py` — every line OK except `desktop updater` (UNKNOWN by
   design) and `egress` while the app is idle.

## 10-minute acceptance — ask, then check with the reader
| # | Ask OpenHuman | Check with | It works when |
|---|---|---|---|
| 1 | "How many roadmap rows are `next`?" | `nos dtt status` | the same count, from `nos_tables read-rows` |
| 2 | "What does roadmap row `openhuman` say, and what is its status?" | `nos dtt status \| grep openhuman` | same title and status, quoted from `get-row` |
| 3 | "Which roadmap rows are `doing` right now?" | `nos dtt status` | same set, no invented rows |
| 4 | "Run `tools/red-status.py` and give me the first red line." (approve the shell call) | run it yourself | identical first red line |
| 5 | "Set roadmap row `openhuman` to `doing`." | `nos dtt status` unchanged | it reports 401/403 (reader tier) and does not retry |

Bonus: "What is `keap` part of?" vs `tools/body.py keap`. A pass is 5/5 answers matching the readers, question 5 refused, and the egress check below clean.

## Zero cloud egress — what to watch
- `tools/openhuman-status.py` → `egress` line: RED names every non-loopback socket of an
  OpenHuman process. It is a snapshot; run it during question 4.
- `lsof -nP -iTCP -iUDP | grep -i openhuman` — expect only `127.0.0.1:*->127.0.0.1:11434`
  (Ollama) and the core's own loopback RPC port.
- Little Snitch: expect **denied** attempts, not silence — sign-in/session checks to
  `api.tinyhumans.ai`, the updater to `github.com`, crash reports to Sentry, the skills
  catalog (HermesHub). These are the control-plane calls `local_only` does not stop
  (gitbooks `privacy-mode.md`). Write down every host it tried; that list is step 1's input.
- "Zero egress" means zero *allowed*. An allowed connection to any non-local host is a fail.

## What this is, and is not
- It is the "runs as the user" attacker class (`ssot/doctrine/session-threat-model.md`):
  same uid as the operator, with accessibility, shell and browser reach. Nothing in nOS
  contains it tonight except the firewall, the RO token and your approvals.
- Not deployed by nOS. `apps/openhuman.yml.draft` (headless core, `install_openhuman: false`)
  is step 1; its gate is `tests/anatomy/test_openhuman_draft_is_local_only.py`.
- Unverified until tonight: a pre-written `config.toml` surviving migration; "Set it up myself" making no backend call; hermes3:8b driving the tool loop.
