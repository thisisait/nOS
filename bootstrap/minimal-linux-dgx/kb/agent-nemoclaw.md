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
(`127.0.0.1:11434`, rewritten to `host.openshell.internal:11434` inside).

| What | Where |
|---|---|
| sandbox name | `nos-agent` |
| the CLI (any maintainer) | `nemoclaw …` — `/usr/local/bin/nemoclaw` runs it as the operator via sudo |
| gateway | operator's user unit `nemoclaw-openshell-gateway`, `127.0.0.1:8080` |
| dashboard | `http://127.0.0.1:<port>/#token=…` on the DGX — not on the LAN |
| install log · pin | `/opt/nos-dgx/nemoclaw/install.log` · `NEMOCLAW_PIN` in the recipe |

## Drive it

```
nemoclaw nos-agent status            # gateway, sandbox, inference route
nemoclaw nos-agent connect           # a shell inside the sandbox; then: openclaw tui
nemoclaw nos-agent logs --follow
nemoclaw nos-agent dashboard-url --quiet
```

The dashboard refuses any origin but `127.0.0.1`, so from a laptop tunnel it:

```
ssh -L 18789:127.0.0.1:18789 <you>@__HOST__
# on the DGX: nemoclaw nos-agent dashboard-url --quiet  → open that URL in the tunnelled browser
```

Maintainers only (`nos-maintainers`): the wrapper's sudo rule is in
`/etc/sudoers.d/nos-nemoclaw`. A tier-3 user has no door to the agent — by design.

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
answer on `127.0.0.1:11434` first (`nos-ollama-loopback.socket`).
