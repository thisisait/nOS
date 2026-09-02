# Ears — the listening organ

Ears turns speech into a *proposal*, never into an effect.

A deliberate Terminal session (`s` in nos-cc) captures the microphone through
**ffmpeg** (avfoundation on macOS) and transcribes locally with **Parakeet MLX**
(`mlx-community/parakeet-tdt-0.6b-v3`). Nothing is sent anywhere to be
understood. It wakes on a spoken phrase, submits on another, and hands the text
to an agent for a proposal that the **Cortex** daemon typechecks. It cannot
execute a chain: effects stay behind `CortexBindingGate`.

## Why it is off by default

An always-open microphone records whoever else is in the room, so listening is
a **deliberate session**: `s` in nos-cc opens a Terminal window running the
listener, and closing the window stops the recording. There is **no launchd
agent and no config flag** — macOS binds the mic grant to the responsible
process, and a launchd agent has none to offer (the `ears_always_listen` flag
that claimed otherwise gated nothing and was deleted 2026-09-02). A
reboot-proof ear waits on a real signing identity: roadmap row
`ears-app-bundle`. Ears not running is the correct state, not a fault.

That is also why its manifest entry carries no `health_check` and no
`domain_var` / `port_var`: Ears serves nothing over HTTP, and a health probe
would report a deliberately-off organ as broken.

## Wake and submit

| var | default |
|---|---|
| `ears_wake_phrase` | `hej jeffe, hej jefe, hej dzefe, hey jeff, hey jeffe, hej jeff` |
| `ears_submit_phrase` | `makej jeffe, makej jeff, makey jeffe` |
| `ears_silence_seconds` | `7` |
| `ears_silence_gap` | `1.2` |

The multiple spellings are not a nicety. Parakeet returns what it heard, and a
Czech speaker saying "hej Jeffe" lands on several transcriptions; a single
spelling meant the organ reported LISTENING and never woke.

## What it installs

A venv with `parakeet-mlx` under `~/ears` (`ears_runtime_dir`), the listener,
the launcher, the speech half, and `ears-listen` + `caddy` on PATH.

It deliberately does **not** install ffmpeg or portaudio: ffmpeg is already in
`homebrew_installed_packages` and the listener captures through it, precisely so
no second audio dependency exists.

## Related

- `roles/pazny.ears/` — the role
- `docs/systems/cortex/` — the typechecker that gates every proposal
- Taxonomy node `nos.host.ears`
