# pazny.gitlab

Ansible role for deploying **GitLab CE** as a compose override fragment in the devBoxNOS `devops` stack. Full self-hosted DevOps platform (Git, CI/CD, container registry, wiki, issues).

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction batch.

## What it does

Two invocation modes from `tasks/stacks/stack-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose up devops`:
   - Creates `{{ gitlab_data_dir }}`, `{{ gitlab_config_dir }}`, `~/gitlab-logs`, and `~/agents/log`
   - Deploys `gitlab.rb` Omnibus configuration (external URL, internal nginx port, SSH port, disabled bundled Prometheus/Grafana/Loki)
   - Enables the nginx reverse-proxy vhost symlink
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/devops/overrides/gitlab.yml`
   - The override is picked up by stack-up's `find + -f` loop and merged into the devops compose project
   - Notifies `Restart gitlab` if the override template changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose up devops --wait`:
   - Waits up to 10 minutes for `/-/readiness` (GitLab Omnibus init is slow — 2-5 minutes typical)
   - Overwrites the `root` password via `gitlab-rails runner` (state-declarative reconverge; safe to run every playbook execution)

## Requirements

- Docker Desktop for Mac (ARM64)
- At least **4 GB of RAM** free for the container — this is the single heaviest service in devBoxNOS
- `stacks_shared_network` defined at the play level
- Nginx reverse-proxy vhost at `sites-available/gitlab.conf`
- Mkcert root CA at `{{ stacks_dir }}/shared-certs/rootCA.pem` (for OIDC TLS trust when Authentik is enabled)

## Variables

| Variable | Default | Description |
|---|---|---|
| `gitlab_version` | `18.10.1-ce.0` | Pinned for CVE-2026-0723 (2FA bypass) + 9 HIGH CVEs |
| `gitlab_domain` | `gitlab.dev.local` | Public nginx vhost hostname |
| `gitlab_http_port` | `8929` | Internal HTTP port (nginx handles SSL) |
| `gitlab_ssh_port` | `2224` | Git-over-SSH port (22=system, 2222=Gitea) |
| `gitlab_data_dir` | `~/gitlab` | Repos, uploads, artifacts (large — move to external SSD) |
| `gitlab_config_dir` | `~/gitlab-config` | gitlab.rb + keys + certs |
| `gitlab_timezone` | `Europe/Prague` | Rails `time_zone` |
| `gitlab_signup_enabled` | `false` | Disable public registration |
| `gitlab_puma_workers` | `2` | Puma worker processes |
| `gitlab_sidekiq_concurrency` | `10` | Background job threads |
| `gitlab_admin_password` | *(from credentials)* | Rotated via `global_password_prefix` |

## Usage

From `tasks/stacks/stack-up.yml`, gate the role invocations on `install_gitlab`:

```yaml
- name: "[Stacks] GitLab render + dirs (pazny.gitlab role)"
  ansible.builtin.include_role:
    name: pazny.gitlab
  when: install_gitlab | default(false)

# ... stack-up.yml renders base devops compose + runs docker compose up ...

- name: "[Stacks] GitLab post-start root password reconverge"
  ansible.builtin.include_role:
    name: pazny.gitlab
    tasks_from: post.yml
  when: install_gitlab | default(false)
```

## Rollback

Revert the commit and:

1. Restore the gitlab service block in `templates/stacks/devops/docker-compose.yml.j2`
2. Restore `tasks/iiab/gitlab.yml` and `tasks/iiab/gitlab_post.yml`
3. Restore the `include_tasks` calls in `main.yml` and `tasks/stacks/stack-up.yml`
