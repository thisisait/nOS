# rustfs-base

Wiring layer for the pazny.rustfs role. RustFS — Rust S3-compatible drop-in
for MinIO — serves as nightly backup destination plus the generic S3-API
substrate for blob-storing consumers (Outline, future Bluesky blobstore).
Console UI at `fs.<tld>` (Wing /hub card emitted), S3 endpoint at the api
port. App-level identity is access_key / secret_key, so no Authentik OIDC
block in this manifest yet — native OIDC + bucket policy wiring is a
follow-up. Activates when `install_rustfs: true`. Q3 batch.
