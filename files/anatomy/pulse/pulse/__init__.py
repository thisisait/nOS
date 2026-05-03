"""nos-pulse — scheduled-job heartbeat for the bones-and-wings platform.

A4 PoC scope (2026-05-03): non-agentic only. Tick loop polls
``wing.db.pulse_jobs`` via Wing API, fires due jobs as subprocess, logs
runs to ``wing.db.pulse_runs``. Agentic mode (claude SDK invocations) is
A8 phase work.

Authoritative spec: ``docs/bones-and-wings-refactor.md`` §4.4 +
``files/anatomy/docs/plugin-loader-spec.md``.
"""

__version__ = "0.1.0"
