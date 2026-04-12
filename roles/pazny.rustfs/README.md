# pazny.rustfs

Ansible role for deploying **RustFS** (S3-compatible object storage, Rust drop-in MinIO replacement) as a compose override fragment in the devBoxNOS `iiab` stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction. Member of the `iiab-agents` group (`pazny.open_webui`, `pazny.uptime_kuma`, `pazny.vaultwarden`, **`pazny.rustfs`**).

## What it does

Single invocation from `tasks/stacks/stack-up.yml` (wired in Phase B):

- Creates `{{ rustfs_data_dir }}` and `~/agents/log` on the host
- Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/rustfs.yml`
- Notifies `Restart rustfs` if the override template changed
- Prints S3 endpoint connection info for the operator

No post-start task — RustFS is a single container with local-only access.

## Requirements

- Docker Desktop for Mac (ARM64)
- `stacks_shared_network` defined at the play level
- A top-level `Restart rustfs` handler in the consuming playbook (role-local fallback also provided)

## Variables

| Variable | Default | Description |
|---|---|---|
| `rustfs_version` | `1.0.0-alpha.90` | Pinned for CVE-2025-68926 (hardcoded gRPC token) + 3 more CVEs |
| `rustfs_api_port` | `9010` | S3 API port (aws-cli, rclone, restic, SDK) |
| `rustfs_console_port` | `9001` | Web console port |
| `rustfs_domain` | `fs.dev.local` | Nginx vhost hostname |
| `rustfs_data_dir` | `~/rustfs/data` | Host bind mount for persistence |
| `rustfs_access_key` | *(from credentials)* | S3 access key, rotated via `global_password_prefix` |
| `rustfs_secret_key` | *(from credentials)* | S3 secret key, rotated via `global_password_prefix` |
| `rustfs_mem_limit` | `{{ docker_mem_limit_light }}` | Defaults to `512m` |

## Usage

From `tasks/stacks/stack-up.yml`, gated on `install_rustfs`:

```yaml
- name: "[Stacks] Render pazny.rustfs compose override"
  ansible.builtin.include_role:
    name: pazny.rustfs
    apply:
      tags: ['rustfs', 's3', 'storage']
  when: install_rustfs | default(false)
  tags: ['rustfs', 's3', 'storage']
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the `rustfs:` service block in `templates/stacks/iiab/docker-compose.yml.j2`
2. Restore `tasks/iiab/rustfs.yml` (if also reverted in Phase B)
3. Delete the leftover override file at `~/stacks/iiab/overrides/rustfs.yml`
