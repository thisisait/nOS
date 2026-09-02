# Ears — Skills

> Host actions for the listening organ. Ears exposes no API and binds no socket;
> it is reached through the host service manager only.

## Authentication

- **Method:** N/A — Ears issues no credential. The actions below run as the operator.

---

## check-ears-session

**Trigger:** "is Ears running", "is the microphone listening", "ears status"
**Method:** state reader (there is no daemon — listening is a Terminal session)
**Command:**
```bash
tools/caddy-status.py        # listener state, mic_ok, last heard turn
pgrep -fl ears-listen        # is a session process alive right now
```
**Output:** session state and pid. **Not running is the DEFAULT and is not a
fault** — the operator opens a session with `s` in nos-cc and closes the window
to stop it. Report the state; do not infer a problem from absence.

---

## read-ears-log

**Trigger:** "what did Ears hear", "ears log", "why did it not wake"
**Method:** file read
**Command:**
```bash
tail -n 100 ~/ears/log/ears-listen.log
```
**Output:** wake/submit decisions and transcription lines. The usual cause of
"it never woke" is a spelling the wake phrase does not carry — check
`ears_wake_phrase` before assuming the microphone or the model is at fault.
