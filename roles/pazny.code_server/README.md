# pazny.code_server

Self-hosted **VS Code v browseru** (code-server, LinuxServer.io image) jako součást devBoxNOS `devops` compose stacku.

- **Image**: `lscr.io/linuxserver/code-server:4.115.0-ls332` (multi-arch arm64v8 + amd64)
- **Port**: `3009` (host) → `8443` (kontejner)
- **Domain**: `code.{{ instance_tld | default('dev.local') }}`
- **SSO**: proxy auth — Authentik forward_auth v nginx vhostu (built-in login vypnutý, `PASSWORD=""`)
- **Data**: `{{ HOME }}/code-server/config` (extensions, settings) + `/workspace` (projekty)
- **Závislosti**: Authentik (SSO proxy), nginx (reverse proxy + mkcert TLS)
- **Tier**: 1 (admin — code-server = plný shell access k boxu)

Aktivace: `install_code_server: true` v `config.yml`.
