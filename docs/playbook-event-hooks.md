# Playbook event hooks — cross-tool, cross-IDE

End-of-playbook signal designed to be consumable from **any** agent or
tool: Claude Code, Cursor, Copilot, Codex, an editor file-watcher, a
shell `tail`, a CI runner, or a `launchd`/`systemd` timer. No vendor
lock-in. No special protocol.

The mechanism is two dumb files:

1. **`~/.nos/events/playbook.jsonl`** — append-only JSONL log. One
   line per `playbook_start` and `playbook_end` event. Always written,
   regardless of `NOS_TELEMETRY_ENABLED` / Bone HTTP availability.
2. **`hooks/playbook-end.d/*`** — operator-defined executable scripts
   in the repo. Run sequentially after each playbook finishes, with
   the event JSON on stdin and `NOS_*` env vars in scope.

Implemented by `callback_plugins/wing_telemetry.py`. No additional
playbook config required — the callback is loaded by `tests/ansible.cfg`
and `ansible.cfg` already.

---

## Event schema

Each line in the JSONL is a single JSON object:

```json
{
  "ts": "2026-04-27T21:42:51Z",
  "run_id": "run_5f9e1a3b-…",
  "type": "playbook_start",
  "playbook": "main.yml"
}
```

```json
{
  "ts": "2026-04-27T22:01:14Z",
  "run_id": "run_5f9e1a3b-…",
  "type": "playbook_end",
  "playbook": "main.yml",
  "duration_ms": 1124237,
  "recap": {
    "ok": 811, "changed": 254, "failed": 0,
    "skipped": 356, "unreachable": 0,
    "rescued": 0, "ignored": 0
  }
}
```

`run_id` is stable across the start/end pair so consumers can match
them.

`recap` mirrors the PLAY RECAP line — `failed > 0` is the canonical
signal of "something broke".

---

## Consumer recipes

### Claude Code (Monitor tool, in-conversation)

```bash
# Wake up the moment a playbook_end event lands:
tail -F ~/.nos/events/playbook.jsonl | grep --line-buffered '"playbook_end"'
```

The Monitor tool fires per-line, so the next agent turn is triggered
within milliseconds of `v2_playbook_on_stats` finishing. No `sleep`
loops, no scheduled wakeups.

### Cursor / VS Code

A simple watcher launched from a status bar contribution:

```bash
fswatch -o ~/.nos/events/playbook.jsonl |
  xargs -n1 -I{} bash -c 'tail -1 ~/.nos/events/playbook.jsonl |
    jq -r "select(.type == \"playbook_end\") |
           \"\(.recap.failed) failed, \(.recap.ok) ok\""'
```

### CLI tail one-liner

```bash
# What was the last playbook outcome?
jq -r 'select(.type == "playbook_end")
       | "\(.ts) failed=\(.recap.failed) ok=\(.recap.ok)"' \
   < ~/.nos/events/playbook.jsonl | tail -1
```

### Bone HTTP (HMAC, networked)

The same lifecycle events are also pushed via HMAC POST to Bone
`/api/v1/events` when telemetry is on (`NOS_TELEMETRY_ENABLED=1` or
`wing_telemetry_enabled: true`). Use that for cross-host fleet
observability. Read back with `GET /api/v1/events?type=playbook_end`.

The JSONL log is the **always-on** local mirror; the Bone push is
opt-in fleet telemetry.

### Hook scripts (push side)

Drop something like this in `hooks/playbook-end.d/20-tell-slack.sh`,
`chmod +x`:

```bash
#!/usr/bin/env bash
[[ "${NOS_PLAYBOOK_RECAP_FAILED:-0}" -gt 0 ]] || exit 0   # only on fail
curl -sf -X POST "$SLACK_WEBHOOK_URL" \
  -H 'Content-Type: application/json' \
  -d "{\"text\":\"nOS run failed: $NOS_PLAYBOOK_RECAP_FAILED tasks down\"}"
```

Hooks run once per playbook end, sequentially, 15-second timeout each.
A failing hook is logged to stderr but does not propagate.

---

## Design notes

### Why JSONL (not a single state file)

- Append-only is crash-safe — a partial write at most loses the
  current line, never corrupts past history.
- Cheap to tail (`tail -f`, `fswatch -o`, `Monitor`).
- Trivial to grep / `jq` historically (debug "what happened during
  yesterday's blank?").

### Why a hooks dir (not "just one webhook URL")

- Multiple consumers (Slack + desktop notifier + CI marker file)
  without coupling them to each other.
- Versioned with the repo — operator's hook scripts ride along on
  branches and PRs (e.g. a release branch can have its own
  notification routing).
- Shell scripts are the lowest common denominator — works with
  `bash`, `zsh`, `python3`, `curl`, `jq`, `node`, anything.

### Why this is independent of telemetry on/off

The Bone HMAC push has trade-offs (HMAC secret management, network
dependency, cross-host fleet semantics). The local JSONL + hooks
should "just work" on a fresh install without any setup, so the
agent-loop story stays smooth even before telemetry is configured.

### Override paths

| Env var | Default |
|---|---|
| `NOS_PLAYBOOK_JSONL_PATH` | `~/.nos/events/playbook.jsonl` |
| `NOS_PLAYBOOK_HOOKS_DIR` | `<repo>/hooks/playbook-end.d/` |

Both expand `~` and `$VARS`.

---

## What's NOT in scope here (yet)

- **Per-task hooks** — out of scope. If you need to react to a single
  failing task, watch the Bone events stream instead (every
  `task_failed` event is already published via HMAC).
- **Migrations / upgrades** — `migration_apply` and `upgrade_apply`
  events use the same Bone pipeline. Not yet mirrored to JSONL —
  could land in a follow-up if there's a use case.
- **Cross-host aggregation** — JSONL is per-host. For fleet-level
  views use Wing `/api/v1/hub/...` endpoints which already aggregate.

---

## Testing the hook end-to-end

```bash
# 1. Trigger a tiny "playbook" event manually
mkdir -p ~/.nos/events
python3 - <<'PY'
import json, sys, datetime
sys.path.insert(0, '.')
from callback_plugins.wing_telemetry import CallbackModule, utc_now_iso
cb = CallbackModule()
cb._run_id = "run_test"
cb._playbook_name = "smoke.yml"
cb._publish_lifecycle("playbook_end", {
  "ts": utc_now_iso(),
  "run_id": "run_test",
  "type": "playbook_end",
  "playbook": "smoke.yml",
  "duration_ms": 1234,
  "recap": {"ok": 1, "changed": 0, "failed": 0, "skipped": 0,
            "unreachable": 0, "rescued": 0, "ignored": 0},
})
PY

# 2. Verify the JSONL got the line
tail -1 ~/.nos/events/playbook.jsonl

# 3. Verify any hook scripts you've enabled fired (check their side effect)
```
