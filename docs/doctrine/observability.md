# Observability Doctrine

> Canonical decisions. The 2026-07-17 telemetry saga (a broken HMAC pipeline
> CRAWLED a release blank to a halt) is why this file exists.

**Observability is best-effort. It must NEVER slow, block, crash, or fail a run.**
Telemetry, event callbacks, the JSONL lifecycle log, notification fan-out, audit
emit — all of it is *watching* the system, never *gating* it. A broken sink
degrades observability; it must not degrade the thing being observed.

**Fail-open, with a circuit-breaker.** A sink that can't deliver must give up, not
retry forever and not spill forever. After **N consecutive failures** (default 15)
the emitter DISABLES itself for the rest of the run — no more sends, no more
fallback writes — and logs **one** warning. One broken pipeline must not turn into
thousands of slow retries. (`callback_plugins/wing_telemetry.py`, `_flush`.)

**No unbounded work in the hot path.** Bounded timeouts (≤2–5s), no unbounded
retries, **4xx is not retried** (a client/auth error is not transient), and any
on-disk fallback is a **ring buffer** with a hard row cap — never unbounded growth.
A 258 MB fallback db that thrashed the page cache is the anti-pattern this closes.

**Sidecar, not /tmp.** Observability state lives in the private runtime sidecar
`~/.nos/`, never world-shared `/tmp` — an unrelated process (an IDE indexer) must
not be able to open our db and starve a writer on a lock. See [[filesystem.md]].

**One resolved source for a shared secret.** When a host daemon (Bone) and an
in-process emitter (the callback) both authenticate with the same HMAC secret,
BOTH read the SAME already-resolved value (`~/.nos/secrets.yml`) — never a
self-referential play-var template the emitter renders in its own variable
context. `wing_events_hmac_secret: "{{ wing_events_hmac_secret | default(...) }}"`
rendered against play-vars resolves to the WRONG value; the emitter reads
secrets.yml directly and rejects any raw `{{ … }}` it's handed. If a daemon can
hold a stale secret across a failed run, it **self-heals** (signed-ping self-test →
inline reload), not "wait for the next clean run."

**Loud is for gates, silent-degrade is for observability — know which you're
writing.** A *security/SSO verify* (is the OIDC source registered? is OAuth2
active?) is a GATE: it must fail LOUD and stop the run, because a silent failure
ships a dead-SSO/insecure system (the Nextcloud/Gitea silent-OIDC sagas). A
*telemetry emit* is OBSERVABILITY: it must fail SILENT and continue. Putting a
`failed_when` on the wrong one is the recurring mistake — gate the verify, never
the emit.

**Corollary — the emit path is not a test surface for the sink.** If a run's health
depends on whether Wing/Bone/ntfy is up, the coupling is wrong. Verify sinks with
their own explicit health checks; never let a task's success ride on a telemetry
POST landing.
