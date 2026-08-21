# 18 — A report that reaches nobody

**Found 2026-08-22, sideways, while unpausing the minimax-backed agents.**

`files/anatomy/scripts/pulse-run-agent.sh` — the shell bridge every scheduled
agent runs through — posted its finishing notification to `$WING_API_URL`, which
is Wing on `:9000`. Wing's `NotificationsPresenter` exposes **GET** under Bearer
auth and says so in its own docblock:

> This is a read-only projection of the notifications table; creation stays on
> the Bone HMAC path (POST is not exposed here).

So every agent's report got `401`, and the script printed one line to stderr:

```
WARN: notification POST returned HTTP 401
```

Then the wrapper exited 0, because the agent had in fact done its work.

## Why this is a fee and not a bug

Nothing failed. The librarian judged 20 findings, correctly refused to promote
ten stock Nextcloud template files, and wrote a full report to
`~/.nos/librarian-report-<ts>.md`. Its verdict was `REVIEW` — *awaiting a
moderator*. The moderator was never told. A bug would have stopped something;
this delivered everything except the part where a human finds out.

The estate's own A9 doctrine is explicit that this must not be possible —
`files/anatomy/docs/notification-fanout.md`, and `docs/doctrine/loops.md` §5
states it as an invariant: *"fallback wing-inbox: nothing is ever fully
silent."* It was silent.

## The measurement

`notifications` grouped by `origin_agent`, on the live estate:

| origin_agent | rows | first | last |
| --- | ---: | --- | --- |
| *(null)* | 128 | 2026-07-25 | 2026-08-21 |
| `e2e-mock-agent` | 29 | 2026-08-11 | 2026-08-16 |
| `conductor` | 2 | 2026-08-08 | 2026-08-08 |

Not one row from `librarian`, `surveyor`, `scout` or `remediator` — ever. The
conductor's two are from a day when something else posted them; its Sunday
self-test has been silent since.

**The e2e mock agent's notifications land and the real agents' do not**, because
the e2e path posts to Bone. The test exercised a different door than production
used, so the coverage was real and proved the wrong thing — this estate's oldest
shape, in a new place.

## The diagnosis, and what made it invisible

The signature and the secret were right the whole time. Line 24 of the script
documents `WING_EVENTS_HMAC_SECRET — {{ bone_secret }}`, i.e. the variable wears
Wing's name and carries Bone's key. Only the host was wrong. Probed both doors
with one valid signature over one deliberately-invalid body:

```
Bone :8099 -> 400  {"detail":"notifications[0]: missing required field: severity"}
Wing :9000 -> 401  {"error":"Missing or invalid Authorization header…"}
```

Bone verified the HMAC and rejected the body on its merits. The auth was never
the problem.

Three things had to line up for this to survive:

1. **A variable named for the wrong organ.** `WING_EVENTS_HMAC_SECRET` holding
   `bone_secret` reads as "this goes to Wing" at every call site.
2. **A second implementation of a solved thing.** `nos-notify.sh` already sends
   notifications to `${BONE_URL:-http://127.0.0.1:8099}`, and
   `drift-watch.sh:19` already carries the comment *"(Bone; 9000 is Wing)"* —
   somebody had met this confusion and written it down next door.
3. **A warning as the whole error path.** stderr, inside a Pulse job, on a run
   whose exit code was 0 and whose verdict was legitimately `REVIEW`.

## Fixed

`BONE_URL="${BONE_API_URL:-http://127.0.0.1:8099}"`, the house pattern from
`run-remediator.sh`, `run-migration-author.sh` and `deploy-from-ci.sh`. The WARN
now names the door it tried and says plainly that the report did not reach the
inbox.

Gate: `tests/anatomy/test_an_agent_report_reaches_the_inbox.py`.

## What is still owed

- The fee is **paid but not recovered**: every verdict those agents produced
  before today is in a `~/.nos/*-report-*.md` file and in no inbox. Nothing
  replays them.
- `WING_EVENTS_HMAC_SECRET` still names the wrong organ. Renaming it touches
  the plugin manifests, the catalog renderer and `templates/secrets.yml.j2`;
  until then the name is a trap that has now sprung once.
- The conductor's Sunday self-test has posted nothing since 2026-08-08. This
  fix plausibly explains it and **that is not the same as having checked** —
  the conductor runs through `bin/run-agent.php`, not this script.
