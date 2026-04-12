# RustFS

> S3-kompatibilni object storage. Drop-in nahrada MinIO. Buckety, presigned URLs.

## Quick Reference

| | |
|---|---|
| **URL** | `https://s3.dev.local` (API), `https://s3-console.dev.local` (UI) |
| **Port** | `9000` (API), `9001` (console) |
| **Stack** | `iiab` |
| **Toggle** | `install_rustfs: true` |
| **Compose** | `~/stacks/iiab/docker-compose.yml` |
| **Data** | `~/rustfs` |

## Authentication

- **Access key:** `{global_password_prefix}_pw_rustfs_access`
- **Secret key:** `{global_password_prefix}_pw_rustfs_secret`

## API Access

- **S3 endpoint:** `https://s3.dev.local`
- **Auth method:** AWS Signature V4 (access key + secret key)
- **Compatible with:** aws-cli, s3cmd, boto3, any S3 SDK

## Health Check

- **Endpoint:** `GET /minio/health/live` (RustFS is MinIO-compatible)
- **Expected:** `200 OK`

## Dependencies

- None
