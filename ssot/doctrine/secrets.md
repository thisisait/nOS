---
in_force: true
ruled: null
row: null
gates:
  - tests/anatomy/test_lexicon_holds.py
  - tests/anatomy/test_the_operator_file_is_the_last_word.py
---
# Secrets Doctrine

> 2026-07-17: a rotated HMAC secret split across two
> independent resolutions, so every event POST 401'd.

Shared-secret resolution lives here. Emitter fail-open is
[`observability.md`](observability.md). Why
`~/.nos/secrets.yml` is in the private sidecar, never `/tmp`, is
[`filesystem.md`](filesystem.md).

## 1. One resolved source

When a secret is consumed by both a host daemon (plist env) and an
in-process consumer (callback, script), both MUST read the same
already-resolved value from `~/.nos/secrets.yml`. They MUST NOT resolve
independently.

`wing_events_hmac_secret` lands in Bone's plist
(`roles/pazny.bone/templates/bone.plist.j2`) and is read by
`callback_plugins/wing_telemetry.py`. Separate resolutions drift; HMAC
fails.

## 2. Raw-var consumers reject templates

A self-referential play-var template MUST NOT reach a raw-var consumer.
`default.config.yml` may define `wing_events_hmac_secret: "{{ bone_secret }}"`.
That self-reference resolves only through Ansible's full hierarchy, where
the persisted value wins. `play.get_vars()` in a callback sees the literal
`{{ … }}`; templating it against play-vars hits the `default()` fallback,
not the persisted secret.

A raw-var consumer MUST read the resolved value from `secrets.yml` and MUST
REJECT any value still containing `{{`. The emitter MUST NOT sign with an
un-rendered template. (`wing_telemetry.py` `load_hmac_secret_fallback`.)

## 3. Self-heal a stale secret

Ansible handlers flush at end-of-play. A run that fails earlier leaves a
rotated secret on disk while the daemon keeps the stale env it booted
with; later runs 401 and never reach the flush.

The daemon MUST self-heal in-band: a signed-ping self-test detects the
desync and triggers an inline reload + re-verify. It MUST NOT wait for the
next clean run. (`roles/pazny.bone/tasks/post.yml`,
`roles/pazny.bone/files/hmac_selftest.py`.)

## 4. Pointers at rest

A secret at rest SHALL be a pointer, resolved at the edge.
AgentKit `agent_credentials.secret_ref` is NEVER plaintext — `env:VAR` /
`infisical:/path` resolved at session-open; plaintext lives only in
function-local memory. `secrets.yml` is the one resolved store; everything
else references it.

## 5. The process that uses it

A credential lives in the env of the process that USES it. Trace the
runtime, not the workflow.

Loop judges are subprocesses of Bone, so a judge's `requires:` credential
(`state/judge-sets.yml` → `judges.REQUIREMENT_ENV`) MUST be in
`bone.plist.j2`. The same secret in wing.plist, a Pulse job env, or
`~/.nos/secrets.yml` satisfies nothing the engine can see (2026-08-29:
judges skipped "requirement(s) absent"). Before adding a token to a plist,
name the process that will read it. Gate:
`test_judge_requirements_have_a_home.py`.

## 6. Eager-resolve

The plugin loader passes `template_vars: "{{ vars }}"`. A secret whose
value uses a non-stock filter, or a before-core-up undefined ref that
slips past `default()`, aborts the run. See CLAUDE.md operator gotchas;
do not re-derive it here.

## 7. Four kinds of secret

Every secret is exactly one kind (folded from the 2026-05-23 lifecycle pass,
[`docs/archive/secret-lifecycle-doctrine.md`](../../docs/archive/secret-lifecycle-doctrine.md)):

- **A, derived.** Cheap to recompute and not sensitive alone (a URL, a path).
  Re-derived every run. Nothing is persisted.
- **B, generated.** High entropy (an HMAC key, a JWT secret, an app key).
  Made once with `openssl rand`, kept in `~/.nos/secrets.yml`, reused. An
  operator override in `credentials.yml` wins when it is at least 32
  characters and is not the prefix-derived shape.
- **C, captured.** An identity a service holds after bootstrap (an admin
  email, a user id). Captured once; later runs read it instead of
  re-deriving it. The operator's `credentials.yml` still outranks the
  captured value (`test_the_operator_file_is_the_last_word.py`).
- **D, recoverable.** Every role that bootstraps an admin ships a tag-gated
  reset (`--tags <service>-reset-admin`, `never` by default) that refuses
  when the service holds data unless forced. Template:
  `roles/pazny.infisical/tasks/reset-admin.yml`.

An admin lockout SHALL NOT need a data wipe. If it does, a reset is missing.

## 8. At rest and in logs

A file that holds a secret is mode 0600 and its directory 0700: `~/.nos/`,
the launchd plists, rendered overrides, ACME private keys. Gate:
`tests/anatomy/test_security_file_modes.py`. An error message carries the
upstream HTTP code, never the upstream body. Host organs bind 127.0.0.1;
public access goes through Traefik with its middleware.

## 9. A published secret is burned

A value pushed to a public remote is burned for good, whatever is deleted
later. Rotate it at once. Never use the published value again: not as a
fixture, an assertion needle or a gitleaks allowlist entry. Rewriting public
history is the operator's call, never an agent's; the default is rotate and
record.

| First published | Was | Rotated |
|---|---|---|
| 2026-08-05 `710be435` (fingerprint `0c05d2…c751`) | `bone_secret` / `WING_EVENTS_HMAC_SECRET` | 2026-08-06 (`bone_secret_retired`) |
