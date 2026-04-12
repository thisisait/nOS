# pazny.woodpecker

Ansible role for deploying **Woodpecker CI** (server + agent) as a compose override fragment in the devBoxNOS `devops` stack. Lightweight CI/CD wired to Gitea via OAuth2.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction batch.

## What it does

Single invocation mode from `tasks/stacks/stack-up.yml` — **no post-start task**:

- Creates `{{ woodpecker_data_dir }}` and `~/agents/log`
- Enables the nginx reverse-proxy vhost symlink
- Renders `templates/compose.yml.j2` (server + agent in one fragment) into `{{ stacks_dir }}/devops/overrides/woodpecker.yml`
- The override is picked up by stack-up's `find + -f` loop and merged into the devops compose project
- Notifies `Restart woodpecker` (restarts both server and agent as one logical unit)
- Displays manual OAuth2 setup instructions when `woodpecker_gitea_client` or `woodpecker_gitea_secret` is empty

## Requirements

- Docker Desktop for Mac (ARM64)
- `stacks_shared_network` defined at the play level
- Nginx reverse-proxy vhost at `sites-available/woodpecker.conf`
- **Manual step**: create an OAuth2 application in Gitea (Settings → Applications) and set `woodpecker_gitea_client` + `woodpecker_gitea_secret` in `config.yml`. Redirect URI must be `https://{{ woodpecker_domain }}/authorize`.

## Variables

| Variable | Default | Description |
|---|---|---|
| `woodpecker_version` | `v3` | Semver tag (`latest` was removed upstream) |
| `woodpecker_domain` | `ci.dev.local` | Public nginx vhost hostname |
| `woodpecker_port` | `8060` | Web UI host port |
| `woodpecker_grpc_port` | `9060` | Internal gRPC for agents |
| `woodpecker_data_dir` | `~/woodpecker` | Host bind mount for persistence |
| `woodpecker_agent_secret` | *(from credentials)* | Shared secret between server + agent |
| `woodpecker_gitea_client` | *empty (required)* | Gitea OAuth2 client ID |
| `woodpecker_gitea_secret` | *empty (required)* | Gitea OAuth2 client secret |
| `woodpecker_open_registration` | `false` | Gate on Gitea account access |
| `woodpecker_max_workflows` | `4` | Parallel pipeline runs per agent |

## Usage

From `tasks/stacks/stack-up.yml`, gate the role invocation on `install_woodpecker`:

```yaml
- name: "[Stacks] Woodpecker render + dirs (pazny.woodpecker role)"
  ansible.builtin.include_role:
    name: pazny.woodpecker
  when: install_woodpecker | default(false)
```

No post-task — Woodpecker bootstraps purely from env vars at container start.

## Rollback

Revert the commit and:

1. Restore the woodpecker-server + woodpecker-agent service blocks in `templates/stacks/devops/docker-compose.yml.j2`
2. Restore `tasks/iiab/woodpecker.yml`
3. Restore the `include_tasks` call in `main.yml` and `tasks/stacks/stack-up.yml`
