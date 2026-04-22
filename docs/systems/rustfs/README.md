# RustFS

> S3-kompatibilni object storage. Drop-in nahrada MinIO. Buckety, presigned URLs.

## Quick Reference

| | |
|---|---|
| **URL** | `https://fs.dev.local` (console; `rustfs.dev.local` alias works too). S3 API is on `127.0.0.1:9010` — no public nginx vhost by default. |
| **Port** | `9010` (S3 API on host, mapped to 9000 in container), `9001` (console) |
| **Stack** | `iiab` |
| **Toggle** | `install_rustfs: true` |
| **Compose** | `~/stacks/iiab/docker-compose.yml` |
| **Data** | `~/rustfs` |

## Authentication

- **Access key:** `{global_password_prefix}_pw_rustfs_access`
- **Secret key:** `{global_password_prefix}_pw_rustfs_secret`

## API Access

- **S3 endpoint:** `http://127.0.0.1:9010` (bound to loopback by default; front with nginx if you need HTTPS)
- **Auth method:** AWS Signature V4 (access key + secret key)
- **Compatible with:** aws-cli, s3cmd, boto3, any S3 SDK

## Health Check

- **Endpoint:** `GET /health` (RustFS-native; returns `{"status":"ok","ready":true}` once IAM + storage subsystems load. Do NOT use MinIO's `/minio/health/live` — RustFS 1.0.0-alpha.x does not implement it.)
- **Expected:** `200 OK`

## Dependencies

- None
