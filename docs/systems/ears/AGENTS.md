# Ears — for agents

**What you may assume:** nothing. Ears binds no port, exposes no API and answers
no query. It is an INPUT organ: it produces proposals, it does not accept them.

**Liveness** is a Terminal session the operator opened (`s` in nos-cc; ask
`tools/caddy-status.py`), and *not running is a valid state* — an always-open
microphone records whoever else is in the room, so there is no daemon at all.
Do not report an absent Ears as a fault, and do not start it: that is an
operator decision.

**The boundary that matters.** Ears asks an agent for a proposal and has the
Cortex daemon typecheck it. Nothing in this role executes a chain; effects stay
behind `CortexBindingGate`. An agent reasoning about Ears should treat "it heard
something" and "something happened" as strictly separate facts.

**Transcription is local.** Parakeet MLX on this host. There is no cloud ASR
call to account for in a GDPR record — the audio does not leave the machine.
