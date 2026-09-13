# Raw archive store — Object Lock verification

CLAIM: HONOR

Reader: `tools/raw-archive-probe.py` against live `rustfs/rustfs:1.0.0-rc.1`
(`iiab-rustfs-1`, `http://127.0.0.1:9010`) on 2026-09-13. Gate:
`tests/anatomy/test_raw_archive_probe.py` (red if anyone claims WORM without a 403).

## Live reader output (quoted)

```
verdict: HONOR
live: True
endpoint: http://127.0.0.1:9010
lock_status: 200
put_status: 200
delete_status: 403
version_id: 879697dd-8753-498c-8671-a83e4780c128
note: CreateBucket object-lock header -> 200
note: PutObject COMPLIANCE retain-until 2026-09-13T11:48:30.000Z -> 200
note: DeleteObject versionId=879697dd-8753-498c-8671-a83e4780c128 -> 403
```

Pre-fix of the claim-check (`--claim-worm --dry-run`) is red: `claimed WORM but
delete returned None, not 403` (exit 1). That is the false-green the row named.

## Sketch if HONOR (this is that sketch)

Do **not** park the archive in bucket `backups` (same instance, same failure
domain as the nightly dump). Dedicated bucket, Object Lock on create:

- Bucket: `raw-archive` (ObjectLockEnabled, versioning implied).
- Key: `raw/<source>/<content-hash>` — partition by SOURCE (estate==firm).
- Headers on put: `x-amz-object-lock-mode: COMPLIANCE` +
  `x-amz-object-lock-retain-until-date` = GDPR retention TTL.
- Interface (already decided on the row, not built here):
  `archive_put(source, content) -> content_hash` / `archive_get(hash)`.

No importer in this change. Do not stuff a zip into KEAP as a substitute.

## Ceiling that remains (not a WORM lie)

Object Lock COMPLIANCE on this box is **tamper-resistant at the S3 API**.
It is **not** independent durability: `roles/pazny.backup` still targets
`http://127.0.0.1:9010` bucket `backups` — the same process. Disk/host loss
takes store and backups together. That is `raw-archive-backup`, not this row.

## Still unverified

- Overwrite of the *same version* / GET-after-delete byte identity (this run
  proved version-delete 403 only).
- Shortening retain-until under COMPLIANCE.
- Lifecycle expiry of a locked version.
- GOVERNANCE bypass vs COMPLIANCE (only COMPLIANCE was probed).
- A second replica off this host.
- Probe leftover: live bucket `raprobe-*` holds a 15-minute COMPLIANCE object;
  it expires, do not force-delete it.
