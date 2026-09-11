---
title: The agent (NemoClaw)
section: dev
order: 5
summary: An always-on OpenClaw agent in an OpenShell sandbox, thinking with the same local Ollama that serves Chat — how to reach it, drive it, and what it may touch.
---

**NemoClaw** is NVIDIA's reference stack for running an agent *more safely*:
the [OpenClaw](https://openclaw.ai) agent lives in an
[OpenShell](https://github.com/NVIDIA/OpenShell) sandbox — a container with a
file, network and inference policy — and the OpenShell gateway on the host
routes its model calls. On this box there is **one** of it, owned by the
operator account, and it thinks with the **same native Ollama** Chat uses
(`qwen3.5:35b`, see *Local models*). No second model server, no extra GPU
memory: the sandbox reaches Ollama through a loopback door
(`127.0.0.1:8000`, fronted by NemoClaw's token proxy on `host.openshell.internal:11435` inside).

| What | Where |
|---|---|
| sandbox name | `nos-agent` |
| the CLI (any maintainer) | `nemoclaw …` — `/usr/local/bin/nemoclaw` runs it as the operator via sudo |
| gateway | operator's user unit `nemoclaw-openshell-gateway`, `127.0.0.1:8080` |
| web UI | `https://__HOST__:8448/go` (maintainers, PAM) → the OpenClaw dashboard, token supplied by the edge |
| install log · pin | `/opt/nos-dgx/nemoclaw/install.log` · `NEMOCLAW_PIN` in the recipe |
| provider settings | `/etc/nos/nemoclaw.env` (no secrets; the wrapper exports it) |

## Drive it

```
nemoclaw nos-agent status            # gateway, sandbox, inference route
nemoclaw nos-agent connect           # a shell inside the sandbox; then: openclaw tui
nemoclaw nos-agent logs --follow
nemoclaw nos-agent dashboard-url --quiet
```

## The web UI

The **Agent** card on the landing page (`https://__HOST__:8448/go`): log in with
your Linux account (maintainers) and the OpenClaw dashboard opens. Behind the
PAM gate the edge appends OpenClaw's own gateway token for you — the dashboard
does not keep it between visits, and the token lives in a root-only nginx
include the recipe renders from `nemoclaw nos-agent gateway-token`. After a
token rotation (`nemoclaw credentials reset`), re-run the recipe. Opening
`https://__HOST__:8448/` directly shows OpenClaw's login form: paste the output
of `nemoclaw nos-agent gateway-token --quiet` there. Without the LAN edge, the SSH tunnel still works:
`ssh -L 18789:127.0.0.1:18789 <you>@__HOST__` and the printed URL as is.

Maintainers only (`nos-maintainers`): the wrapper's sudo rule is in
`/etc/sudoers.d/nos-nemoclaw`. A tier-3 user has no door to the agent — by design.

## Its tools

Every OpenClaw tool (exec, files, web fetch, sessions, …) is presented to the
model directly (`NEMOCLAW_TOOL_DISCLOSURE=direct`). NemoClaw's default hides
them behind a `tool_search` meta-tool to save context, and a local model then
tends to say it has no exec tool rather than search for it. Exec runs INSIDE the
sandbox — the agent cannot touch the host.

## What it is for, and what it is not

OpenClaw is an agent: it runs commands, reads and writes files, fetches the
web, spawns sub-sessions and reports back. Its dashboard is a **chat plus a
file preview**, not an artifact renderer — "draw me a pinball game" works in
Chat (Open WebUI renders HTML it receives) and does not work here. The one
rendering surface OpenClaw has is the **Canvas** tab (A2UI components, HTML,
charts) driven by the agent's `canvas` tool; the recipe enables that plugin
(NemoClaw ships without it). Ask for "show it on the canvas" and it has a
place to draw.

## Inside the sandbox (what the agent learns the hard way)

A session transcript from the first day, so nobody reads them as bugs:

| The agent tried | What happened | Why |
|---|---|---|
| write `/usr/local/bin/x.py` | `EACCES` | it is user `sandbox`, not root — write under `/sandbox` (its home and workspace) or `/tmp` |
| `pip install pygame`, `apt-get install` | fails | no root; pip reaches PyPI (preset) but a windowed library has no display anyway |
| `python -m http.server` + `curl localhost` | **DENIED** by OpenShell | loopback is refused by policy (SSRF hardening); the sandbox may not listen or call itself |
| `web_fetch file:///tmp/x.html` | invalid URL | the tool takes http(s) only |
| shows a file from `/tmp` in the dashboard | "session file not found" | the preview reads the agent's workspace, `/sandbox/.openclaw/workspace` |

Outbound network is only what the policy allows (`nemoclaw nos-agent policy
list`): package registries, Hugging Face, GitHub for brew, the inference route.
Everything else is denied and logged; `nemoclaw nos-agent policy add <preset>`
opens a named door. Files the agent builds for a human to open are the
roadmap row `dgx-agent-outputs` (served at `/out/`, not yet built).

## Models and tool calling

The agent thinks with whatever `NEMOCLAW_MODEL` names in `/etc/nos/nemoclaw.env`
(`nemotron-3-nano:30b` since 2026-09-08; Chat keeps `qwen3.5:35b` — two
models loaded side by side fit the 121 GB). Tool calling is where small local models
differ most: qwen sometimes wraps tool arguments in a string and the call is
dropped, and with progressive disclosure it looped on `tool_search`. Candidates
already in Ollama with `tools` capability: `nemotron-3-nano:30b` (NVIDIA's
own, 24 GB, 1M context — NemoClaw's tuned pairing), `gpt-oss:120b` (best at
tools, 65 GB). Switching: set `NEMOCLAW_MODEL` in the recipe and re-run it. (Not
`nemoclaw inference set` — it refuses a no-auth compatible route in both
directions; the recipe changes the model in OpenClaw's own config, which is
all the route needs, and restarts the gateway.) A one-off by hand:

```
nemoclaw nos-agent config set --key agents.defaults.model.primary --value inference/<ollama tag> --restart
```

after the tag is in `models.providers.inference.models` (the recipe adds it).

## Reading a session

`nemoclaw nos-agent logs` is the gateway log (tool failures say `[tools] write
failed: …`). The transcripts live in the sandbox at
`/sandbox/.openclaw/agents/main/sessions/<id>.jsonl`; read them with
`nemoclaw nos-agent exec -- <command>`, which runs any command inside the
sandbox as the agent's user.

## What it may touch

The sandbox starts with NemoClaw's *suggested* policy: reads and writes stay
inside the sandbox, outbound network is allow-listed (hot-reloadable:
`nemoclaw nos-agent policy …`), inference goes only to the registered route.
Messaging channels (Telegram, Discord, Slack) are **off** and stay a deliberate
operator step. Web search is not configured.

## When it is red

`dgx-status` shows two rows: *openshell gateway* (a listener on `:8080`) and
*nemoclaw sandbox* (a running container). As the operator:

```
systemctl --user status nemoclaw-openshell-gateway
nemoclaw nos-agent status
```

Re-running the recipe (`sudo bash /srv/nos-dgx/setup-root.sh`) resumes an
interrupted onboarding; `NOS_NEMOCLAW=0` skips the whole section. Ollama must
answer on `127.0.0.1:8000` first (`nos-ollama-loopback.socket`).
