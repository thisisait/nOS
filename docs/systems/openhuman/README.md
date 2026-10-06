# OpenHuman — the desktop agent, set up by one command (roadmap `openhuman`)

Set `install_openhuman: true` in `config.yml`, then run `ansible-playbook main.yml --tags openhuman`.

## What the role does, in order (`roles/pazny.openhuman`)
1. **Installs the app as a symbiont.** Cask `openhuman` from `homebrew_symbiont_casks`. It is installed only when neither `Caskroom/openhuman` nor `/Applications/OpenHuman.app` exists, and nOS never upgrades or removes it: the cask is `auto_updates`. The run reports which copy it found.
2. **Writes `~/.openhuman/users/local/config.toml` before the first launch.** It merges the declared keys (privacy mode, analytics and usage sharing off, core updater off, remote gitbooks MCP off, memory off, the model route, Ollama on `127.0.0.1:11434`) into whatever is already there. Keys it does not declare are kept, but comments are not.
3. **`workspace/AGENTS.md`** is a copy of `IMPRINT.md` with one provenance line. It is rewritten on every converge, so edit `IMPRINT.md`, not this copy.
4. **Skills** (`openhuman_skills`, default `nos-datatables`) are copied into `~/.openhuman/skills/`. They are not linked, because OpenHuman rejects symlinks.
5. **The MCP document** `~/.openhuman/users/local/nos-mcp.json` gives you the nOS tables, read-only. The RO token is read from `iiab-keap-1` each time the server spawns and is never stored. The repo path is `nos_main_checkout`.
6. **The Little Snitch rule group** `~/.openhuman/nos-openhuman.lsrules` denies OpenHuman every remote host. Little Snitch does not filter loopback.
7. **Verifies.** It runs `tools/openhuman-status.py` (tag `verify`). Any RED fails the play. UNKNOWN does not fail it: an idle app or the desktop updater can only show UNKNOWN.

## What nOS cannot do: three clicks, once
- **First launch: click "Set it up myself".** This is a local session with no account ([Welcome.tsx](https://github.com/tinyhumansai/openhuman/blob/main/app/src/pages/Welcome.tsx)).
- **MCP: paste `nos-mcp.json` into Connections → MCP Servers → mcp.json.** OpenHuman reads MCP servers from no file. The `mcp.json` tab is "the only way a server is added or removed": the RPC `mcp_clients_config_set` writes its own SQLite store, `mcp_clients/mcp_clients.db` ([registry README](https://github.com/tinyhumansai/openhuman/blob/main/crates/openhuman-core/src/mcp/registry/README.md)). That RPC needs the running app's own token, and writing its database by hand would be a hack against a schema nobody versions for us.
- **Firewall: import `nos-openhuman.lsrules` in Little Snitch.** The `littlesnitch` CLI has no rule-import command. Its `restore-model` replaces the whole configuration, which is too destructive to use for this. LuLu has no rules-file CLI, so with LuLu you add the same rule by hand. pf cannot filter per app, so nOS ships no pf rule.

## Provider: local model or your Claude subscription
| `openhuman_provider` | route | privacy | leaves the Mac |
|---|---|---|---|
| `ollama` (default) | `ollama:<ollama_small_model>` (`hermes3:8b`) | `local_only` | nothing |
| `claude-code` | `claude-code:<model>` (`openhuman_model`, default `sonnet`) | `standard` (`local_only` refuses every CLI delegate) | prompts, via the `claude` CLI |

The claude-code mode drives the `claude` binary that `tasks/claude-cli.yml` manages. It must be version 2.0 or newer and logged in (`claude login`; on macOS the credential lives in the Keychain). Leave `ANTHROPIC_API_KEY` unset so the subscription is used ([provider guide](https://github.com/tinyhumansai/openhuman/blob/main/gitbooks/developing/providers/claude-code.md)). The connections come from the `claude` process, not from OpenHuman, so the OpenHuman rule stays deny-all. The `claude` rule must allow `api.anthropic.com` (inference), `platform.claude.com` (OAuth refresh) and `claude.ai` (sign-in) ([network requirements](https://code.claude.com/docs/en/network-config)). In this mode Anthropic (US) becomes an Art-30 processor (see `openhuman-base/plugin.yml`).

## 10-minute acceptance: ask, then check with the reader
| # | Ask OpenHuman | Check with | It works when |
|---|---|---|---|
| 1 | "How many roadmap rows are `next`?" | `nos dtt status` | the same count, from `nos_tables read-rows` |
| 2 | "What does roadmap row `openhuman` say, and what is its status?" | `nos dtt status \| grep openhuman` | same title and status, quoted from `get-row` |
| 3 | "Which roadmap rows are `doing` right now?" | `nos dtt status` | same set, no invented rows |
| 4 | "Run `tools/red-status.py` and give me the first red line." (approve the shell call) | run it yourself | identical first red line |
| 5 | "Set roadmap row `openhuman` to `doing`." | `nos dtt status` unchanged | it reports 401/403 (reader tier) and does not retry |

A pass needs all five: answers 1–4 match the readers, question 5 is refused, and `tools/openhuman-status.py` shows `egress` OK during question 4. The Little Snitch log should show **denied** attempts (`api.tinyhumans.ai`, `github.com` updater, Sentry), not silence.

## What this is, and is not
- It belongs to the "runs as the user" attacker class (`ssot/doctrine/session-threat-model.md`). Only three things contain it: the firewall rule, the RO token and your approvals.
- The headless core (`apps/openhuman.yml.draft`) is a later step. Promoting it must give it its own toggle.
- Not yet verified on a real launch: whether the pre-written `config.toml` survives OpenHuman's schema migration, and the Little Snitch rule's process path (`OpenHuman.app/Contents/MacOS/OpenHuman`).
