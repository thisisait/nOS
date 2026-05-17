# Notification fanout — operator-attention queue (Anatomy A9)

> **Status:** shipped 2026-05-16. Source-of-truth: `bones-and-wings-refactor.md` §10.1.
>
> **Anatomy gates:** `tests/anatomy/test_notification_fanout.py` (13 tests).

## Why

A8 (conductor agent) and A7 (gitleaks plugin) generate findings and run
reports the operator needs to see. Before A9 those signals lived only in
events and `gitleaks_findings`; nothing escalated. A9 closes that loop:
**one severity-tagged write seam** that delivers to the operator's inbox,
their phone (ntfy), and their mailbox depending on per-plugin severity
routing.

Three channels, severity-routed per plugin/agent manifest:

| Channel | Use | Implementation |
|---|---|---|
| **Wing /inbox** | Primary, all severities | `wing.db.notifications` rows; `/inbox` lists unread for the current operator |
| **ntfy**        | Push (severity ≥ high) | HTTP POST to ntfy container, topic `nos-<severity>`, native priority/tags |
| **Mail**        | Critical + daily digest | Raw SMTP to mailpit (dev) — Stalwart TLS path is future work |

## Surfaces

```
┌─────────────────────────┐
│ Plugin / agent emitter  │  POST /api/v1/notifications  ────────┐
└─────────────────────────┘                                       │
                                                                  ▼
                                                       ┌──────────────────────┐
                                              HMAC ───▶│ Bone main.py route   │
                                                       │ → notifications.py   │
                                                       │ → clients/wing.py    │
                                                       └──────────┬───────────┘
                                                                  │ INSERT
                                                                  ▼
                                                       ┌──────────────────────┐
                                                       │ wing.db.notifications│
                                                       └──────────┬───────────┘
                                                                  │
                                ┌─────────────────────────────────┼─────────────────────────┐
                                │                                 │                         │
                                ▼                                 ▼                         ▼
                ┌──────────────────────────┐    ┌──────────────────────────────┐    ┌───────────────────┐
                │ Wing /inbox presenter    │    │ bin/dispatch-notifications   │    │ (operator audit:  │
                │ unread + mark-read POST  │    │ Pulse-fired every minute     │    │  /audit deep-link)│
                └──────────────────────────┘    │  → ntfy + mail dispatch      │    └───────────────────┘
                                                └──────────────────────────────┘
```

## Schema (`files/anatomy/wing/db/schema-extensions.sql`)

`notifications` carries one row per emitted notification. Key columns:

| Column                | Purpose |
|---|---|
| `uuid`                | Stable identity (mint at insert) |
| `severity`            | `critical \| high \| medium \| low \| info` |
| `title` / `body`      | Inbox display |
| `actor_id` / `actor_action_id` | A10 audit lineage — groups with source event |
| `target_actor_id`     | Who is the addressee (default `operator`) |
| `origin_plugin` / `origin_agent` | Attribution + routing-lookup key |
| `source_event_id`     | Soft FK `events.id` — `/inbox` can deep-link `/audit` |
| `channels_json`       | JSON array: subset of `[wing-inbox, ntfy, mail]` |
| `wing_inbox_read_at`  | NULL = unread (mark-read action stamps it) |
| `ntfy_dispatched_at` + `ntfy_error` | Dispatch worker stamps these |
| `mail_dispatched_at` + `mail_error` | Dispatch worker stamps these |
| `metadata_json`       | Per-channel hints (e.g. ntfy click URL, mail recipients override) |

## Wing surface

* `App\Model\NotificationRepository` — single-seam access. `insert / query /
  findByUuid / markRead / countUnread / pendingForChannel / markDispatched`.
* `App\Presenters\InboxPresenter` — `/inbox` route, three sections:
  1. **Notifications** (A9) — severity-filtered, unread toggle, POST mark-read.
  2. **Secret findings** (A8.c carryover) — unresolved `gitleaks_findings`.
  3. **Conductor runs** (A8.c carryover) — recent `source='conductor'` events.

## Bone surface

* `POST /api/v1/notifications` — HMAC-authenticated. Batches accepted as
  `{notifications: [...]}`; single-object payloads also accepted.
* `GET /api/v1/notifications?target_actor_id=...&unread_only=true&...` —
  CLI/dispatch-worker convenience read.

Payload schema:

```json
{
  "severity": "high",                                  // required
  "title": "Gitleaks: aws-access-token in roles/foo/main.yml",
  "body":  "Fingerprint a1b2c3..; commit deadbeef; line 42.",
  "channels": ["wing-inbox", "ntfy"],                  // optional — see routing
  "target_actor_id": "operator",                       // optional, default "operator"
  "actor_id": "plugin:gitleaks",                       // optional, A10 attribution
  "actor_action_id": "uuid-of-the-scan-run",           // optional, A10 lineage
  "origin_plugin": "gitleaks",                         // optional, fallback routing key
  "origin_agent":  null,                               // optional, fallback routing key
  "source_event_id": 12345,                            // optional, /audit deep-link
  "metadata": {"click_url": "https://wing/inbox/<uuid>"}
}
```

## Severity routing (A9.5)

Plugins declare per-severity channel lists in their `plugin.yml`:

```yaml
notification:
  on_critical: [wing-inbox, ntfy, mail]
  on_high:     [wing-inbox, ntfy]
  on_medium:   [wing-inbox]
  on_low:      []
  on_info:     []
```

The `wing-base` plugin's aggregator harvests these blocks into
`inputs.notification_routing` at plugin-load time, and its `post_compose`
hook renders the flat map to
`~/wing/app/data/notification-routing.json`. Bone's `clients/wing.py`
reads that sidecar at notification-insert time and resolves channels
when the emitter provides `origin_plugin`/`origin_agent` + `severity`
but no explicit `channels:` array.

**Resolution order in `insert_notification`:**

1. Explicit `channels:` in payload (always wins).
2. Aggregator-rendered routing for `origin_*` + `severity`.
3. Fallback to `["wing-inbox"]` — no notification is ever fully silent.

## Dispatch worker (`bin/dispatch-notifications.php`)

Pulse-eligible PHP CLI registered as a per-minute subprocess job by
`wing-base/plugin.yml`. Reads `wing.db.notifications` rows where the
channel appears in `channels_json` AND the per-channel `dispatched_at`
column is NULL.

Per-channel delivery:
* **ntfy** — `POST <NTFY_URL>/nos-<severity>` with `Title:`, `Priority:`,
  `Tags:`, optional `Click:` headers. Body becomes the ntfy message body.
* **mail** — Raw SMTP to `MAIL_HOST:MAIL_PORT` (no TLS, no auth — targeted
  at mailpit). `Subject: [nOS][SEVERITY] <title>`, `X-NOS-*` headers carry
  attribution. Stalwart TLS path is future work.

Lock: per-row `*_dispatched_at` timestamp. Partial failures stamp the
matching `*_error` column and re-try on the next tick.

Exit codes: `0` clean, `1` fatal (DB unreadable), `2` partial (≥1 failure).

Env vars (read at startup):

| Var | Default | Purpose |
|---|---|---|
| `WING_DB_PATH` | `~/wing/app/data/wing.db` | SQLite location |
| `NTFY_URL` | `http://127.0.0.1:2586` | Empty string disables the ntfy channel |
| `MAIL_HOST` | `127.0.0.1` | Empty disables the mail channel |
| `MAIL_PORT` | `1025` | mailpit default |
| `MAIL_FROM` | `wing@dev.local` | SMTP `MAIL FROM` |
| `MAIL_RECIPIENT` | (empty — required to enable mail) | SMTP `RCPT TO` |
| `DISPATCH_BATCH_LIMIT` | `50` | Per-channel cap per tick |
| `DISPATCH_DRY_RUN` | `0` | `1` = log only, no delivery, no stamp |

## How to emit a notification from a plugin

From a Pulse-fired skill script (e.g. `skills/run-gitleaks.sh`):

```bash
TS=$(date +%s)
BODY='{"severity":"high","title":"Gitleaks: aws-access-token in roles/foo/main.yml",
  "body":"Fingerprint a1b2c3...","origin_plugin":"gitleaks","actor_id":"plugin:gitleaks"}'
# Canonical compact JSON for HMAC reproducibility
BODY=$(echo "$BODY" | jq -c .)
SIG=$(printf '%s.%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$WING_EVENTS_HMAC_SECRET" -r | awk '{print $1}')
curl -sS -X POST http://127.0.0.1:9000/api/v1/notifications \
  -H "Content-Type: application/json" \
  -H "X-Wing-Timestamp: $TS" \
  -H "X-Wing-Signature: $SIG" \
  -d "$BODY"
```

From an agent (PHP, via the `mcp_wing` tool):

```php
$client->post('/api/v1/notifications', [
    'severity' => 'critical',
    'title'    => 'Conductor self-test failed: 3/8 steps red',
    'body'     => $report,
    'origin_agent'   => 'conductor',
    'actor_id'       => 'agent:conductor',
    'actor_action_id' => $sessionUuid,
    'source_event_id' => $sessionRowId,
    // channels omitted — aggregator routing picks based on severity
]);
```

## Anatomy gates

`tests/anatomy/test_notification_fanout.py` pins:

* Schema columns + indexes present.
* `NotificationRepository` class + DI registration.
* `InboxPresenter` uses the repository and gates mutating actions POST-only.
* Bone `notifications.py` + `clients/wing.py` carry the documented surface.
* Bone `main.py` registers both `POST` + `GET /api/v1/notifications`.
* Dispatch worker script exists with `deliver_ntfy` + `deliver_mail` +
  `mark_dispatched`.
* `wing-base` registers the `dispatch-notifications` Pulse job with a
  per-minute cron.
* `wing-base` declares the consumer-block + agent-profile aggregator
  specs and the routing-template provisioning entry.
* Routing template iterates `inputs.notification_routing` and emits all
  five severity keys.
* `gitleaks` plugin (first consumer) pins critical→3-channel + on_low/on_info=[].
* End-to-end aggregator smoke against synthetic peers.

## Daily-digest mail (A9.2, 2026-05-17)

To avoid mailbox spam during burst-events (e.g. a Gitleaks-finding flurry
after an audit-PR merge), low-severity mail notifications batch into ONE
daily summary email instead of N immediate dispatches.

**Severity floor** (`mail_digest_floor` in `default.config.yml`,
default `medium`):

| Severity vs floor | Per-minute worker action |
|---|---|
| Above floor (`critical`, `high`) | Immediate SMTP — same as pre-A9.2 |
| At/below floor (`medium`, `low`, `info`) | Stamp `mail_digest_window`, leave `mail_dispatched_at` NULL |

A second Pulse job (`dispatch-notifications-digest`, schedule
`mail_digest_cron` — default `0 9 * * *`) invokes the same dispatch script
with `DISPATCH_DIGEST_FLUSH=1`. It reads every row where
`mail_digest_window IS NOT NULL AND mail_dispatched_at IS NULL`, sends ONE
aggregated email grouped by severity, then stamps `mail_dispatched_at` on
each row atomically.

### Aggregated email format

```
Subject: [nOS] Daily digest: <N> notification(s) — YYYY-MM-DD
From:    nOS Wing <wing@<tld>>
X-NOS-Digest: 1
X-NOS-Digest-Count: <N>

nOS notification digest — YYYY-MM-DD HH:MM:SS UTC
<N> notifications across this window.

── MEDIUM (3) ────────────────
  [2026-05-16 23:14:01] Gitleaks: 2 new finding(s) (by plugin:gitleaks)
    Fingerprint a1b2c3...; commit deadbeef; line 42
  [2026-05-17 06:22:18] ERPNext maintenance window expired (by plugin:erpnext)

── LOW (2) ───────────────────
  …
─── End of digest ───
Open Wing /inbox to mark items read.
```

### Failure handling

Digest-flush failure (SMTP unreachable, recipient rejected) stamps the
`mail_error` column on every queued row but leaves `mail_dispatched_at`
NULL — the next daily flush retries the entire batch. The per-minute
worker excludes already-queued rows (`mail_digest_window IS NOT NULL`)
so digest failures don't trigger immediate-mail fallback.

### Disabling

Set `mail_digest_floor: "none"` in `config.yml` — the per-minute worker
then fires every severity immediately and the daily flush job is a
clean no-op (zero queued rows).

### Operator knobs

| Var | Default | Purpose |
|---|---|---|
| `mail_digest_floor` | `medium` | Severity at-or-below which mail batches into digest |
| `mail_digest_cron` | `0 9 * * *` | Pulse cron expression for the daily flush |

## Per-plugin templates (2026-05-17)

Plugins MAY declare named title/body templates in the same `notification:`
block. Emitters then POST `{template: <name>, context: {...}}` instead
of building literal title/body strings. Bone resolves the template via
the aggregator routing sidecar and renders with Python `string.Template`
(`$var` / `${var}` syntax — distinct from Latte/Jinja `{{ var }}` to
prevent double-evaluation at routing-render time).

Manifest shape:

```yaml
notification:
  on_critical: [wing-inbox, ntfy, mail]
  on_high:     [wing-inbox, ntfy]
  on_medium:   [wing-inbox]
  on_low:      []
  on_info:     []
  templates:
    new_findings:
      title: "Gitleaks: $count new secret finding(s)"
      body: |
        **$count new finding(s)** in $scan_dir

        $top_findings_md
```

Emitter (bash):

```bash
NOTIF_BODY=$(jq -n \
    --arg sev "$MAX_SEV" --arg tpl "new_findings" \
    --arg count "$INSERTED" --arg scan_dir "$SCAN_DIR" \
    --arg top "$TOP_FINDINGS_MD" \
    '{severity: $sev, template: $tpl,
      context: {count: $count, scan_dir: $scan_dir, top_findings_md: $top},
      origin_plugin: "gitleaks", actor_id: "plugin:gitleaks"}')
```

Resolution path inside Bone (`clients/wing.py`):

1. If payload has `title` literally → use it.
2. Else if payload has `template: name` + optional `context: {...}` →
   `_lookup_template(origin_plugin/origin_agent, name)` reads the routing
   sidecar, fetches the template strings, then `string.Template(s)
   .safe_substitute(context)` renders each.
3. Missing context keys leave the literal `${missing}` in place rather
   than erroring — safer than hard-failing the emit.

Template name pattern: `^[a-z0-9][a-z0-9_-]+[a-z0-9]$` (alphanum +
hyphen + underscore, 2-50 chars). Pinned by Bone's `validate_payload`
+ the `test_bone_validate_payload_accepts_template_or_title` anatomy
gate.

## Out of scope (post-A9)

* Stalwart TLS SMTP path (Track G follow-on).
* Per-recipient routing (today `target_actor_id` is honored but always
  `operator` in practice).
* Webhook-fanout duplicate-suppression (per-notification idempotency key).
* Time-window-aware digest (e.g. "send digest only if M+ rows pending").
* Conditional / loop logic in templates — `string.Template` is
  intentionally minimal; emitters that need conditionals build the
  rendered string and POST `title`/`body` literally.

These can be added incrementally; the table + repository + dispatch worker
are stable.
