# pazny.code_server

Self-hosted **VS Code in the browser** (code-server, LinuxServer.io image) as part of the nOS `devops` compose stack.

- **Image**: `lscr.io/linuxserver/code-server:4.115.0-ls332` (multi-arch arm64v8 + amd64)
- **Port**: `3009` (host) -> `8443` (container)
- **Domain**: `code.{{ instance_tld | default('dev.local') }}`
- **SSO**: proxy auth — Authentik forward_auth in the nginx vhost (built-in login disabled, `PASSWORD=""`)
- **Data**: `{{ HOME }}/code-server/config` (extensions, settings) + `/workspace` (projects)
- **Dependencies**: Authentik (SSO proxy), nginx (reverse proxy + mkcert TLS)
- **Tier**: 1 (admin — code-server = full shell access to the host)

Enable via `install_code_server: true` in `config.yml`.
