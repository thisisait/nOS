# pazny.gitea

Ansible role for deploying **Gitea** as a compose override fragment in the devBoxNOS `devops` stack. Self-hosted Git service with built-in Actions, wiki, issue tracker.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction batch.

## What it does

Two invocation modes from `tasks/stacks/stack-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose up devops`:
   - Creates `{{ gitea_data_dir }}` on the host
   - Stops any lingering Homebrew Gitea service (legacy cleanup)
   - Enables the nginx vhost symlink (`sites-enabled/gitea.conf`)
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/devops/overrides/gitea.yml`
   - The override is picked up by stack-up's `find + -f` loop and merged into the devops compose project
   - Notifies `Restart gitea` if the override template changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose up devops --wait`:
   - Checks if the container is running
   - Checks if the admin user already exists in Gitea's DB
   - On first run: creates the admin user via `gitea admin user create`
   - On subsequent runs: overwrites the admin password via `gitea admin user change-password` (state-declarative reconverge)

## Requirements

- Docker Desktop for Mac (ARM64)
- `stacks_shared_network` defined at the play level (`devops_net` and the external shared network must already exist in the base compose file)
- Nginx reverse-proxy vhost at `sites-available/gitea.conf`

## Variables

| Variable | Default | Description |
|---|---|---|
| `gitea_version` | `1.25.5` | Pinned for CVE-2026-gitea-template-traversal (authenticated RCE) |
| `gitea_domain` | `git.dev.local` | Public nginx vhost hostname |
| `gitea_port` | `3003` | Host-side port (3000=Grafana, 3001=Uptime Kuma, 3002=reserved) |
| `gitea_ssh_port` | `2222` | Git-over-SSH port |
| `gitea_data_dir` | `~/gitea` | Host bind mount for persistence |
| `gitea_admin_user` | *(current `$USER`)* | CLI-provisioned admin |
| `gitea_admin_password` | *(from credentials)* | Rotated via `global_password_prefix` |
| `gitea_admin_email` | *empty* | Admin contact (fill in config.yml) |
| `gitea_secret_key` | *(from credentials)* | Installer-lock secret |
| `gitea_disable_registration` | `false` | `true` = admin-only user creation |

## Usage

From `tasks/stacks/stack-up.yml`, gate the role invocations on `install_gitea`:

```yaml
# Before devops compose up
- name: "[Stacks] Gitea render + dirs (pazny.gitea role)"
  ansible.builtin.include_role:
    name: pazny.gitea
  when: install_gitea | default(false)

# ... stack-up.yml renders base devops compose + runs docker compose up ...

# After devops compose up
- name: "[Stacks] Gitea post-start admin setup"
  ansible.builtin.include_role:
    name: pazny.gitea
    tasks_from: post.yml
  when: install_gitea | default(false)
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the gitea service block in `templates/stacks/devops/docker-compose.yml.j2`
2. Restore `tasks/iiab/gitea.yml` and `tasks/iiab/gitea_post.yml`
3. Restore the `include_tasks` calls in `main.yml` and `tasks/stacks/stack-up.yml`

The override file at `~/stacks/devops/overrides/gitea.yml` becomes dead — delete it manually if the rollback is permanent.
