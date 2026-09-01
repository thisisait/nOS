# Ears — Skills

> Host actions for the listening organ. Ears exposes no API and binds no socket;
> it is reached through the host service manager only.

## Authentication

- **Method:** N/A — Ears issues no credential. The actions below run as the operator.

---

## check-ears-daemon

**Trigger:** "is Ears running", "is the microphone listening", "ears status"
**Method:** host service manager
**Command:**
```bash
launchctl print "gui/$(id -u)/eu.thisisait.nos.ears-listen"     # macOS
systemctl --user status eu.thisisait.nos.ears-listen             # Linux
```
**Output:** load state, pid, last exit status. **Not loaded is the DEFAULT and
is not a fault** — `ears_always_listen` is false unless the operator set it.
Report the state; do not infer a problem from absence.

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
