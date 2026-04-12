# RustFS — Skills

> Callable actions for RustFS S3 storage. Uses aws-cli or S3 SDK.

## Authentication

- **Method:** AWS Signature V4
- **Credentials:** `~/agents/tokens/rustfs.env` (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
- **Endpoint:** `https://s3.dev.local`

---

## create-bucket

**Trigger:** "create bucket [name]", "new storage bucket"
**Method:** CLI
**Endpoint:** `aws s3 mb s3://{name} --endpoint-url https://s3.dev.local`
**Input:** Bucket name
**Output:** `make_bucket: {name}`

---

## upload-object

**Trigger:** "upload [file] to S3", "store file in bucket"
**Method:** CLI
**Endpoint:** `aws s3 cp {file} s3://{bucket}/{key} --endpoint-url https://s3.dev.local`
**Input:** Local file path, bucket, key
**Output:** `upload: ./file to s3://bucket/key`

---

## download-object

**Trigger:** "download [file] from S3", "get object from bucket"
**Method:** CLI
**Endpoint:** `aws s3 cp s3://{bucket}/{key} {local_path} --endpoint-url https://s3.dev.local`
**Input:** Bucket, key, local path
**Output:** Downloaded file

---

## list-objects

**Trigger:** "list files in bucket", "show bucket contents"
**Method:** CLI
**Endpoint:** `aws s3 ls s3://{bucket}/ --endpoint-url https://s3.dev.local`
**Input:** Bucket name
**Output:** Object listing with dates and sizes

---

## presign-url

**Trigger:** "generate download link", "create temporary URL for [file]"
**Method:** CLI
**Endpoint:** `aws s3 presign s3://{bucket}/{key} --expires-in 3600 --endpoint-url https://s3.dev.local`
**Input:** Bucket, key, expiry seconds
**Output:** Presigned URL valid for specified duration

---

## list-buckets

**Trigger:** "show all buckets", "list storage locations"
**Method:** CLI
**Endpoint:** `aws s3 ls --endpoint-url https://s3.dev.local`
**Input:** None
**Output:** Bucket listing with creation dates
