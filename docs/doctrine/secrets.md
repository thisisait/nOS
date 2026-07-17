# Secrets Doctrine

> Canonical decisions. The 2026-07-17 telemetry saga (a rotated HMAC secret split
> across two independent resolutions → every event POST 401'd) is why this file exists.

**One resolved source for a shared secret.** When a secret is consumed by BOTH a host
daemon (rendered into its launchd/systemd plist env by Ansible) AND an in-process
consumer (an Ansible callback plugin, a script), both MUST read the SAME already-resolved
value — the persisted `~/.nos/secrets.yml` — never two independent resolutions that can
diverge. Concrete case: `wing_events_hmac_secret` lands in Bone's plist env
(`roles/pazny.bone/templates/bone.plist.j2`) AND is read by the callback emitter
(`callback_plugins/wing_telemetry.py`). If they resolve separately, they drift, and the
HMAC signature check fails.

**Never let a self-referential play-var template reach a raw-var consumer.**
`default.config.yml` defines the secret as a template
(`wing_events_hmac_secret: "{{ bone_secret }}"`, historically the self-referencing
`"{{ wing_events_hmac_secret | default(bone_secret | default(...)) }}"`). A self-reference
resolves correctly **only** through Ansible's full variable hierarchy — where the persisted
value has lower precedence and the template collapses to it. A consumer that reads the var
RAW (`play.get_vars()` in a callback) gets the literal `{{ … }}` string, and if it naively
templates that against play-vars it resolves to the WRONG value — the `default()` fallback,
not the persisted secret. **Rule:** a raw-var consumer reads the RESOLVED value straight
from `secrets.yml` and REJECTS any value still containing `{{`. The emitter never signs
with an un-rendered template. (`wing_telemetry.py` `load_hmac_secret_fallback` + the
`"{{" in v` guards.)

**Self-heal a stale secret; don't wait for a clean run.** Ansible handlers flush only at
end-of-play, so a run that FAILS earlier leaves a freshly-rotated secret on disk (in the
plist and `secrets.yml`) while the daemon keeps the STALE env it booted with → every
subsequent run's auth fails, and the run never reaches the flush that would fix it. The
daemon must self-heal in-band: a signed-ping self-test detects the desync and triggers an
INLINE launchd reload + re-verify, right then — not "it'll clear on the next clean run."
(`roles/pazny.bone/tasks/post.yml` + `roles/pazny.bone/files/hmac_selftest.py`.)

**Secrets are pointers at rest, resolved at the edge.** AgentKit credentials
(`agent_credentials.secret_ref`) are NEVER plaintext — `env:VAR` / `infisical:/path`
pointers resolved at session-open; plaintext lives only in function-local memory. Same
spirit here: `secrets.yml` is the one resolved store, everything else references it.

**Beware the eager-resolve / stock-Jinja trap.** The plugin loader passes
`template_vars: "{{ vars }}"`; a secret whose value uses a non-stock filter, or a
before-core-up undefined ref that slips past `default()`, aborts the whole run. See
CLAUDE.md "Operator gotchas" — don't re-derive it here.

See [[observability]] for the emitter-side circuit-breaker/fail-open contract (this same
secret pipeline is what CRAWLED that release blank), and [[filesystem]] for why
`~/.nos/secrets.yml` lives in the private runtime sidecar and never `/tmp`.
