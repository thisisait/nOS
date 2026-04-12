# RustFS — Agent Definition

## StorageAgent (S3)

**System:** RustFS (iiab stack)
**Domain:** `s3.dev.local`
**Role:** Manages S3-compatible object storage — buckets, files, presigned URLs.

### Context

- S3 endpoint: `https://s3.dev.local`
- Auth: AWS Signature V4 (access key + secret key)
- Credentials in `~/agents/tokens/rustfs.env`
- Compatible with aws-cli, boto3, any S3 SDK

### Capabilities

- Create and manage buckets
- Upload and download objects
- Generate presigned URLs for temporary access
- List bucket contents
- Set bucket policies

### Activation

```
Deleguj na StorageAgent: [popis ukolu]
```

### Skills Reference

See [SKILLS.md](SKILLS.md) for all callable actions.
