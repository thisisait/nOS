# Ears — what the microphone may keep

**Status:** operator decision 2026-10-03: **no transcripts by default**. Change
a number here AND in the register row
(`files/anatomy/plugins/ears-base/plugin.yml`); the gate ties the two.

Grounded in what the code does today (`files/anatomy/ears/ears-listen.py`,
`caddy.py`). Pinned by `tests/anatomy/test_ears_art30.py` and
`tests/anatomy/test_the_ears_are_wired.py`.

## What happens to a sentence

1. The operator opens the listener in a Terminal window (`s` in nos-cc). Nothing
   listens by itself; closing the window stops the microphone.
2. ffmpeg captures the microphone; a speech segment is written to one temporary
   wav, transcribed on this host by `mlx-community/parakeet-tdt-0.6b-v3`
   (parakeet-mlx), and the wav is deleted in the same call. **Audio is never at
   rest** (`ears_dump_segments: 0`; a diagnostic the operator may turn on).
3. Only a segment that follows the wake phrase becomes a turn. Everything else
   is counted (`wake_misses`) and dropped.
4. The turn is handed to the caddy as a process argument. In the default mode
   **no file is written** — not written-then-deleted.

## Modes

| `ears_keep_transcripts` | Ears writes | Caddy ledger (`caddy-sessions`) | Register `retention_days` |
|---|---|---|---|
| `false` (default) | nothing | `transcript` column empty, `summary` only when the agent answered in prose | **0 days** (transient) |
| `true` | `~/ears/turns/turns-YYYY-MM-DD.jsonl`, pruned by the listener at `ears_retention_days` (**90 days** default) | `transcript` = the turn (500 chars) | `ears_retention_days` |

The switch travels as `~/ears/listener.env`, rendered by the role; the listener,
the caddy and `tools/caddy-status.py` all read that one file.

## Data subjects

The operator, and **bystanders**: anyone in earshot of the host while the window
is open. Basis: `legitimate_interests`, Art. 6(1)(f) — balanced by the visible
window, the wake-phrase gate, on-device ASR and the store-nothing default.

## Erasure / export

`state/gdpr-erasure-map.yml` and `state/gdpr-export-map.yml`, id `svc_ears`.
Nothing exists to erase or export in the default mode.

## Switching the mode on a running host

A converge with `ears_keep_transcripts: true` renders the env and the plist
sentence ("transcripts are kept N days"); the next listener session writes
files. Flipping back to `false` stops writing and stops pruning: files already
on disk are left for the operator to delete.
