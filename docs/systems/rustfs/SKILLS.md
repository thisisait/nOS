# RustFS — Skills

> Callable actions for RustFS S3 storage. Uses aws-cli or S3 SDK.

## Authentication

- **Method:** AWS Signature V4
- **Credentials:** `~/.nos/secrets.yml` — `rustfs_access_key` / `rustfs_secret_key`,
  exported as `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`. There is no
  `~/agents/tokens/rustfs.env` in this repo.
- **Endpoint:** `http://127.0.0.1:9010` (S3 API — loopback only, plain HTTP; the
  `fs.dev.local` host serves the **console** on port 9001, not the S3 API)

---

## create-bucket

**Trigger:** "create bucket [name]", "new storage bucket"
**Method:** CLI
**Endpoint:** `aws s3 mb s3://{name} --endpoint-url http://127.0.0.1:9010`
**Input:** Bucket name
**Output:** `make_bucket: {name}`

---

## upload-object

**Trigger:** "upload [file] to S3", "store file in bucket"
**Method:** CLI
**Endpoint:** `aws s3 cp {file} s3://{bucket}/{key} --endpoint-url http://127.0.0.1:9010`
**Input:** Local file path, bucket, key
**Output:** `upload: ./file to s3://bucket/key`

---

## download-object

**Trigger:** "download [file] from S3", "get object from bucket"
**Method:** CLI
**Endpoint:** `aws s3 cp s3://{bucket}/{key} {local_path} --endpoint-url http://127.0.0.1:9010`
**Input:** Bucket, key, local path
**Output:** Downloaded file

---

## list-objects

**Trigger:** "list files in bucket", "show bucket contents"
**Method:** CLI
**Endpoint:** `aws s3 ls s3://{bucket}/ --endpoint-url http://127.0.0.1:9010`
**Input:** Bucket name
**Output:** Object listing with dates and sizes

---

## presign-url

**Trigger:** "generate download link", "create temporary URL for [file]"
**Method:** CLI
**Endpoint:** `aws s3 presign s3://{bucket}/{key} --expires-in 3600 --endpoint-url http://127.0.0.1:9010`
**Input:** Bucket, key, expiry seconds
**Output:** Presigned URL valid for specified duration

---

## list-buckets

**Trigger:** "show all buckets", "list storage locations"
**Method:** CLI
**Endpoint:** `aws s3 ls --endpoint-url http://127.0.0.1:9010`
**Input:** None
**Output:** Bucket listing with creation dates
