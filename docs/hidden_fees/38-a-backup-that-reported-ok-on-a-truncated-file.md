# 38 — A backup that reported OK on a truncated file

**Found 2026-08-30, by the restore drill — seventeen days after the first one.**

```
[2026-08-30T07:42:32Z] keap-db: fetching 2026-08-30/keap-db.gz
Error: in prepare, file is not a database (26)
[2026-08-30T07:42:40Z] keap-db: UNREADABLE
[2026-08-30T07:42:52Z] ==== nOS restore drill FAILED ====
```

Reading `~/.nos/backup.log` back over 29 nights:

| night | node's `pages=` line | uploaded | logged |
| --- | --- | ---: | --- |
| 2026-08-13 | **absent** | 296 MB | `keap-db: OK` |
| 2026-08-30 | **absent** | 310 MB | `keap-db: OK` |
| all 27 others | `pages=177199` | 347 MB | `keap-db: OK` |

`pages=` is what the in-container `node:sqlite` backup prints when it
**finishes**. On those two nights it printed nothing — it died mid-copy — and
both truncated files were gzipped, encrypted, uploaded, and recorded as good
backups. The first was never noticed by anything at all.

## Why it passed

The producer branched on this:

```sh
if docker exec "${KEAP_CONTAINER}" test -s "${ctmp}" 2>/dev/null; then
```

and the code's own comment defended the choice:

> *The snapshot either exists and is non-empty, or it does not. That is the
> only claim worth branching on — the pipeline above reports rc for the
> `while`, not for node.*

Every word of that is true, and it is the entire defect. The backup pipeline
ends in `| while IFS= read -r l; do log …; done`, so node's exit code belonged
to the loop and nobody ever read it. Faced with a verdict it could not see, the
code substituted a claim it could — *there is a file* — and shipped.

**The success marker was written by the attempting code**, in the one place
where being wrong cannot be undone later.

The size alone would have caught both nights: 296 and 310 against a rock-steady
347. Nothing reads size either.

## What was done, 2026-08-30

A reader now opens the snapshot **inside the container, before the upload**,
and counts the same three tables the restore drill counts. Measured live
against `iiab-keap-1` before shipping:

| input | verdict |
| --- | --- |
| the live `keap.db` | `snapshot verified nodes/relations/objects=1711/5084/345` |
| truncated to 40 MB | `database disk image is malformed` |
| 5 KB of `/dev/urandom` | `file is not a database` ← the drill's own error |

This is the last moment the estate can still fail loudly and keep yesterday's
good object instead of overwriting the day with a bad one.

## The fix fell into the same trap, once

The first draft piped the verifier into `tee -a "$LOG_FILE"` to log its output.
A pipeline's return code is its **last** stage, `backup.sh` sets no
`pipefail`, and `tee` always succeeds — so the verifier's verdict would have
been discarded **exactly the way node's was**, by the same mechanism, in the
commit that existed to fix it.

The gate written alongside it did not catch that. It was rewritten until it
did: any rc-swallowing stage (`tee`, `while`, `cat`, `grep`, …) after the
`docker exec` fails it, verified against all three. The producer now uses a
command substitution and logs the output itself.

That is the more useful half of this entry. The rule is easy to state and was
still got wrong twice in one file by someone who had just finished writing it
down: **in a shell without `pipefail`, appending anything to a pipeline
discards the verdict of everything before it.**

Gate: `tests/anatomy/test_a_snapshot_is_opened_before_it_is_uploaded.py`.

## Not closed

**2026-08-30's object was replaced and verified** the same morning, after the
converge put the new reader on the host: a keap-only run logged `pages=177199`
then `snapshot verified nodes/relations/objects=1711/5084/345` and uploaded
347 MB over the corrupt 310 MB; the restore drill then read it back from S3 —
`keap-db: OK (1711/5084/345)`, drill green. **2026-08-13's object is still
corrupt in S3** and stays that way: it is inside the retention window with good
neighbours either side, so nothing is unrecoverable, and rewriting a dated
backup with today's data would be a lie about what that date held.

**Why node dies mid-copy is unknown — but it IS a kill, not a refusal.**
Narrowed 2026-08-30 by reproducing both candidate signatures against the live
container:

| | node output | output file | old `test -s` |
| --- | --- | --- | --- |
| source unreadable (a permission denial) | **loud stack trace**, rc=1 | **none** | false — no upload |
| `kill -9` mid-copy | **silence** | **partial, 155 MB of 726** | **true — would upload** |
| the two bad nights | **silence** | **partial, 296 / 310 MB** | uploaded |

So a TCC or filesystem permission denial is excluded: it is loud and leaves no
file. What matches is a process killed without a signal handler running. WHICH
kill is still unknown — the container's own cgroup shows 512 MB with the backup
peaking at 76 MB, the Docker VM had 8.6 GB free, and nothing distinguished
those two nights in the pulse schedule. With the exit code now logged, `137`
will say so the next time; no cause is guessed here.

**The wing-db leg has no equivalent check.** It replays a SQL dump into a
scratch database at drill time, which is a real verification, but it happens
hours later and on the verifier's side. Whether the producer should verify
there too is a decision, not an oversight, and it is not taken here.
