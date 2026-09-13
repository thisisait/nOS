# Observability Doctrine

> Canonical decisions. The 2026-07-17 telemetry saga (a broken HMAC pipeline
> CRAWLED a release blank to a halt) is why this file exists.

## 1. Best-effort

Observability **must** never slow, block, crash, or fail a run.
Telemetry, event callbacks, the JSONL lifecycle log, notification fan-out,
audit emit — all of it is watching the system, never gating it. A broken
sink degrades observability; it **must** not degrade the thing being
observed.

## 2. Fail-open

A sink that cannot deliver **must** give up: not retry forever, not spill
forever. After N consecutive failures (default 15) the emitter **shall**
disable itself for the rest of the run — no more sends, no more fallback
writes — and log one warning. One broken pipeline **must** not become
thousands of slow retries. (`callback_plugins/wing_telemetry.py`, `_flush`.)

## 3. Bounded hot path

Timeouts **shall** be bounded (≤2–5s). Retries **must** be bounded. **4xx
is not retried** (a client/auth error is not transient). On-disk fallback
**must** be a ring buffer with a hard row cap — never unbounded growth.
A 258 MB fallback db that thrashed the page cache is the anti-pattern this
closes.

## 4. Sidecar

Observability state **shall** live in the private runtime sidecar `~/.nos/`,
never world-shared `/tmp`. An unrelated process (an IDE indexer) **must**
not be able to open the db and starve a writer on a lock. See
[`filesystem.md`](filesystem.md).

## 5. Shared secret

The rule — one resolved source for a shared secret, plus the raw-`{{ … }}`
rejection and daemon self-heal that follow from it — is owned by
[`secrets.md`](secrets.md).

## 6. Loud vs silent

A security/SSO verify (is the OIDC source registered? is OAuth2 active?)
is a GATE: it **must** fail loud and stop the run, because a silent failure
ships a dead-SSO/insecure system (Nextcloud/Gitea silent-OIDC). A telemetry
emit is OBSERVABILITY: it **must** fail silent and continue. Putting
`failed_when` on the emit is the recurring mistake — gate the verify, never
the emit.

## 7. Emit is not a test

If a run's health depends on whether Wing/Bone/ntfy is up, the coupling is
wrong. Sinks **shall** be verified with their own explicit health checks.
A task's success **must** not ride on a telemetry POST landing.

## 8. Observable path

If the API is the only observable path, an in-process shortcut is an
unobservable call and is forbidden, however trivial. Applies wherever a
consumer and its backend end up colocated: the cortex organ, the KEAP UI
once it runs natively on the host, Pulse jobs, Wing's AgentKit. All of
them reach the knowledge backend over `/agent/v1`, so every read and write
lands in one audited lineage. The rule exists because it will be tempting
exactly when it is easiest — same host, same process tree, the store
sitting right there. A performance argument does not override this; a
measured, named, and documented cache in front of the API **may**.
