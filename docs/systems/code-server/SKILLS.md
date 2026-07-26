# code-server — Skills

> code-server has **no external skill surface**. It is a browser IDE (VS Code) that
> nOS runs behind an Authentik forward-auth gate, with its built-in login disabled.
> There is nothing here for an agent to invoke — do not synthesize endpoints.

## Authentication

- **Method:** none exposed. Access is gated by Authentik forward_auth at the proxy; code-server carries no per-user identity, no API token, and no bearer surface.

## No invocable actions

There is deliberately no callable action for code-server:

- It exposes no REST/RPC API that nOS drives — the manifest declares no `health_check`, the role has no `post.yml`, and no `tools/*` script targets it.
- Built-in password auth is off (`PASSWORD`/`HASHED_PASSWORD` empty), so there is not even a login endpoint to script.
- All use is interactive and human: opening files, running a terminal, editing the `/config/workspace` tree — none of it is an agent-triggerable skill.

If an agent needs to act on the same files, it should operate on the host filesystem (`{{ nos_data_root }}/platform/services/code_server/workspace`) or through the host shell directly, not through code-server.
