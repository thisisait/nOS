# OpenClaw — Skills

> Callable actions for OpenClaw. All are CLI verbs of the `openclaw` binary
> (installed globally via NVM npm). There is no documented REST API on the
> gateway beyond a loopback, static-token endpoint, so the skills below are
> command-based, not HTTP.

## Invocation

- **Method:** CLI (`openclaw <verb>`), run on the host as the operator user.
- **Prereq:** NVM's default Node must be on PATH (`nvm use default`); Ollama must be serving on `127.0.0.1:11434`.
- **Config:** `~/.openclaw/openclaw.json`; workspace `~/.openclaw/workspace/`.

---

## run-gateway

**Trigger:** "start the openclaw gateway", "bring openclaw online", "run the agent gateway"
**Method:** CLI
**Command:** `openclaw gateway run`
**Effect:** Starts the OpenClaw gateway bound to `127.0.0.1:18789` (loopback). The launchd daemon runs this automatically after `openclaw onboard --install-daemon`.

---

## open-tui

**Trigger:** "open the openclaw tui", "interactive openclaw session", "talk to Inspektor Klepítko"
**Method:** CLI
**Command:** `openclaw tui`
**Effect:** Launches the interactive terminal UI against the configured local model.

---

## check-health

**Trigger:** "is openclaw healthy", "openclaw health", "check the agent daemon"
**Method:** CLI
**Command:** `openclaw health`
**Effect:** Reports the agent/gateway health. For the inference backend, `curl http://127.0.0.1:11434/api/version` confirms Ollama is up.

---

## set-config

**Trigger:** "set openclaw config", "change max concurrent agents", "update the openclaw primary model"
**Method:** CLI
**Command:** `openclaw config set <dotted.key> <value> --strict-json`
**Examples (verbatim, from `tasks/main.yml`):**
```bash
openclaw config set agents.defaults.maxConcurrent 4 --strict-json
openclaw config set agents.defaults.model.primary "ollama/qwen3-coder:30b" --strict-json
```
**Effect:** Mutates `~/.openclaw/openclaw.json` in place; used by the playbook for idempotent model/concurrency updates.

---

## onboard

**Trigger:** (internal — used by the playbook for first-run setup)
**Method:** CLI
**Command:** `openclaw onboard --non-interactive --mode local --auth-choice ollama --custom-base-url http://127.0.0.1:11434 --custom-model-id <model> --gateway-port 18789 --gateway-bind loopback --install-daemon`
**Effect:** One-shot onboarding against the local Ollama endpoint; writes the config and installs the launchd daemon. The role skips it once `~/.openclaw/openclaw.json` exists.
