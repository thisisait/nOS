# RustFS

> S3-kompatibilni object storage. Drop-in nahrada MinIO. Buckety, presigned URLs.

## Quick Reference

| | |
|---|---|
| **URL** | `https://fs.dev.local` — the **console** only (`rustfs_domain`). The S3 API has no public route; it is on `127.0.0.1:9010`. |
| **Port** | `9010` (S3 API on host → `9000` in container), `9001` (console). Both published on `127.0.0.1` only. |
| **Stack** | `iiab` |
| **Toggle** | `install_rustfs: true` |
| **Image** | `rustfs/rustfs:1.0.0-beta.9` (`rustfs_version`) |
| **Compose** | `~/stacks/iiab/docker-compose.yml` |
| **Data** | `{{ rustfs_data_dir }}` = `{{ nos_data_root }}/platform/services/rustfs/data` → default `~/nos/platform/services/rustfs/data` |
| **Container mount** | host data → `/data` (the object store itself) |

Data-path note: `nos_data_root` defaults to `~/nos`. On external storage the path is
overridden to `{{ external_storage_root }}/rustfs/data`
(`tasks/stacks/external-paths.yml`). This directory **is** the bucket store and is
listed in `backup_paths` as canonical copy #1 — treat it as primary data, not cache.

> **`rustfs.<tld>` is not a live alias on the default edge.** Traefik (primary proxy
> since C1) derives exactly one router per manifest row, from `domain_var` +
> `port_var` — for RustFS that is `fs.<tld>` → console port `9001`, and nothing else.
> The `rustfs.<tld>` second `server_name` exists only in
> `templates/nginx/sites-available/rustfs.conf`, i.e. only when the opt-in host nginx
> is enabled (`install_nginx: true`, default **false**).

## Authentication

- **Access key:** `{global_password_prefix}_pw_rustfs_access` (`rustfs_access_key`)
- **Secret key:** `{global_password_prefix}_pw_rustfs_secret` (`rustfs_secret_key`)
- **SSO: none.** RustFS has no `authentik:` block in
  `files/anatomy/plugins/rustfs-base/plugin.yml` — app-level identity is the access
  key / secret key pair, not OIDC. Upstream native OIDC landed in `alpha.91+` but
  wiring it (org claim mapping, bucket policy attach) is queued, not shipped.

## API Access

- **S3 endpoint:** `http://127.0.0.1:9010` — loopback only, plain HTTP. There is **no**
  `s3.<tld>` host and no HTTPS S3 endpoint; nothing in the repo routes the API port.
  Front it yourself if you need TLS off-host.
- **Auth method:** AWS Signature V4 (access key + secret key)
- **Credentials:** `~/.nos/secrets.yml` (prefix-derived). No token file, no bot account.
- **Compatible with:** aws-cli, s3cmd, boto3, restic, rclone, any S3 SDK

## Health Check

- **Endpoint:** `GET /health` (RustFS-native; returns `{"status":"ok","ready":true}` once
  IAM + storage subsystems load. Do NOT use MinIO's `/minio/health/live` — the RustFS
  1.0.0 line does not implement it.)
- **Expected:** `200 OK`
- **Container healthcheck:** `wget -q -O /dev/null http://127.0.0.1:9000/health`
  (`roles/pazny.rustfs/templates/compose.yml.j2` — the *container-internal* port is
  9000, not the published 9010).
- **Smoke probe:** `https://{{ rustfs_domain }}/health`, expect `200`
  (`state/smoke-catalog.yml`) — the root path returns `501` by S3 spec, so `/health` is
  the only valid liveness probe.

## Dependencies

- None. `roles/pazny.rustfs/tasks/main.yml` has no post-start step — single container,
  local access.
