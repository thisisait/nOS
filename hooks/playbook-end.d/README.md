# `hooks/playbook-end.d/` — cross-tool playbook completion hooks

Drop **executable** files here (`.sh`, `.py`, anything with a shebang).
Each one runs after the Ansible playbook finishes — once, sequentially,
in lexicographic order. Failures are swallowed (a broken hook never
kills the playbook).

## Contract

Each hook gets the playbook completion event TWO ways — pick whichever
your scripting style prefers:

### 1. Event JSON on stdin

```json
{
  "ts": "2026-04-27T21:42:51Z",
  "run_id": "run_5f9e…",
  "type": "playbook_end",
  "playbook": "main.yml",
  "duration_ms": 1234567,
  "recap": {
    "ok": 811, "changed": 254, "failed": 0,
    "skipped": 356, "unreachable": 0, "rescued": 0, "ignored": 0
  }
}
```

### 2. Environment variables

| Variable | Example |
|---|---|
| `NOS_RUN_ID` | `run_5f9e…` |
| `NOS_PLAYBOOK` | `main.yml` |
| `NOS_PLAYBOOK_DURATION_MS` | `1234567` |
| `NOS_PLAYBOOK_RECAP_OK` | `811` |
| `NOS_PLAYBOOK_RECAP_CHANGED` | `254` |
| `NOS_PLAYBOOK_RECAP_FAILED` | `0` |
| `NOS_PLAYBOOK_RECAP_SKIPPED` | `356` |
| `NOS_PLAYBOOK_RECAP_UNREACHABLE` | `0` |
| `NOS_PLAYBOOK_EVENT_JSON` | full JSON, identical to stdin |

## Skipping rules

- Files starting with `.` are ignored (`.gitkeep`, `.DS_Store`, etc.).
- Files ending in `.example` are templates — copy and rename to enable.
- `*.md` is documentation, also skipped.
- Non-executable files are skipped (use `chmod +x`).

## Timeout

Each hook has a **15-second timeout**. Anything longer should detach
itself (`nohup … &` or fire a webhook).

## Example: notify a watching agent

See `10-claude-notify.sh.example`. Copy to `10-claude-notify.sh`,
`chmod +x`, and edit. The default `~/.nos/events/playbook.jsonl` log
is appended on every event regardless of whether you have any hooks
installed — so most external agents (Claude with Monitor, Cursor,
Copilot, Codex) just need to tail that file.

## Cross-tool readers

| Tool | How to consume |
|---|---|
| **Claude Code (Monitor tool)** | `tail -f ~/.nos/events/playbook.jsonl` filtered for `playbook_end` |
| **Cursor / VS Code** | `fswatch -o ~/.nos/events/playbook.jsonl \| xargs -n1 tail -1` |
| **Codex / external agent** | HTTP poll Bone `/api/v1/events?type=playbook_end&since=...` (HMAC) |
| **CI / Slack notification** | drop a hook script with `curl` to the webhook URL |
| **systemd / launchd timer** | watch JSONL mtime and trigger downstream jobs |

See `docs/playbook-event-hooks.md` for the full design rationale.
