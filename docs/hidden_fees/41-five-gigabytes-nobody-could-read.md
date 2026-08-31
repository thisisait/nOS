# 41 — Five gigabytes of the estate's best record, unrotated and unread

**Found 2026-08-31, while auditing where logs are stored and how big they get.**

```
-rw-r--r--  1 pazny  staff  5161667026  /Users/pazny/stacks/infra/traefik/log/access.log
```

**5.2 GB. 4 157 848 lines. 38 days. Growing ~140 MB/day.** Every routed request
to every one of ~50 services — client address, host, router, path, status,
duration — the most complete record the estate produces about itself.

Nothing tailed it. Not Alloy, not a Pulse job, not a dashboard, not a reader.
Nothing rotated it either. Both halves were invisible, and each hid the other:
it grew because nothing rotated it, and nobody noticed it growing because
nothing read it.

## The mechanism, which looked handled

`roles/pazny.traefik/templates/compose.yml.j2` carries this, and it reads like
the answer:

```yaml
    logging:
      driver: "json-file"
      options:
        max-size: "20m"
        max-file: "5"
```

That bounds the container's **stdout**. The access log was a `filePath:` inside
a bind mount, which the Docker log driver never sees. Traefik has no rotation of
its own. So the one guard present in the file governed a stream that was nearly
empty, while the real firehose wrote to disk unbounded, a few lines below in the
same role.

## When the bill comes due

Two separate bills, both partly paid already:

- **Disk.** At 140 MB/day it had eaten 5.2 GB of the SSD the estate stores
  everything else on, in five weeks, on a lab with one user.
- **The one that matters.** This is the record you want *after* an incident —
  who called what, when, and with which status. It existed the whole time. No
  agent, no dashboard and no query could reach it, so in practice it did not.
  Wired observability that was never observed, which is exactly the complaint
  the operator raised one level up: *"je super mít wired observabilitu, ale musí
  být reálně observed."*

## How it was found

Sideways, from the operator's question — how big do the logs get, and can we
delete them. The intended answer was a retention number for Loki. `find -size
+50M` found this instead, and it was the only file over 50 MB anywhere in
`~/stacks`, `~/wing`, `~/bone`, `~/pulse` or `~/keap`.

## What closes it

Deleting two lines. Dropping `filePath:` from both `log:` and `accessLog:` sends
them to stdout, which hands rotation to the json-file driver already configured
(20m × 5 = a 100 MB ceiling) and shipping to Alloy's `discovery.docker`, which
already tails every container in the estate. The lines now land in Loki under
the same retention as everything else.

Gate: `test_no_organ_writes_an_unrotated_log_file.py` — a containerised service
that names a `filePath` for a log is taking on rotation and shipping as its own
problem, and none of them has a rotator.

## What is still owed

- **The 5.2 GB file is still on disk.** Traefik stopped writing to it; nothing
  deletes an operator's data.
- **The gate covers containers only.** The host organs write real files by
  necessity — launchd has no log driver — and are tailed by Alloy's `organ_logs`
  block but bounded by nothing. Measured the same day: none exceeds 50 MB, so
  the fee is not yet due there. `pulse/launchd.err.log` alone was 16.9 MB.
- **Nothing watches size at all.** This was found by a `find` typed by hand.
  A reader that reports the largest unrotated writers would have found it in
  week one instead of week six.
