# RustFS — Agent Definition

## StorageAgent (S3)

**System:** RustFS (iiab stack)
**Domain:** `fs.dev.local` (console only — `rustfs_domain`). There is no `s3.dev.local`.
**Role:** Manages S3-compatible object storage — buckets, files, presigned URLs.

### Context

- S3 endpoint: `http://127.0.0.1:9010` — loopback, plain HTTP, no public route
- Console: `https://fs.dev.local` (Traefik → container port 9001)
- Auth: AWS Signature V4 (access key + secret key)
- Credentials in `~/.nos/secrets.yml` (`rustfs_access_key` / `rustfs_secret_key`);
  there is no `~/agents/tokens/` directory in this repo
- Compatible with aws-cli, boto3, restic, rclone, any S3 SDK

### Capabilities

- Create and manage buckets
- Upload and download objects
- Generate presigned URLs for temporary access
- List bucket contents
- Set bucket policies

### Activation

```
Delegate to StorageAgent: [task description]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
