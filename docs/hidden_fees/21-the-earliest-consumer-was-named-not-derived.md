# 21 — The earliest consumer was named, not derived

**Found 2026-08-22 by the first FULL converge since Secrets P1 landed. It died.**

```
TASK [[pre-migrate] Introspect services against manifest]
[ERROR]: Error while resolving value for 'role_vars': 'nos_derived_secrets' is undefined
Origin: default.credentials.yml:190:20
        rustfs_access_key: "{{ nos_derived_secrets.rustfs_access }}"
failed=1
```

## The mechanism

P1 rewrote 73 credential declarations to read `{{ nos_derived_secrets.<key> }}`.
That fact is set at `main.yml:1231`. `tasks/pre-migrate.yml` passes
`role_vars: "{{ vars }}"`, which resolves the **entire** play-var namespace
eagerly — and it is imported at `main.yml:966`, **265 lines earlier**.

## Why nobody saw it, and this is the part worth keeping

Two independent readers reached the same wrong conclusion, in the same words.

**P1's own comment**, at `main.yml:1183`:

> this must run BEFORE the earliest consumer (`tasks/restore.yml`) and it does
> — constraint 2 (values exist before **core-up's** eager `{{ vars }}` resolve)
> is satisfied with room to spare.

**The gate that exists for exactly this class**,
`tests/anatomy/test_config_stock_jinja_only.py`, whose function was called
`_defined_before_core_up()` and whose failure message read *"undefined at
core-up"*.

Both named **core-up** as the earliest eager consumer. Neither derived it.
Core-up is not first; `pre-migrate` is.

And the gate was worse than its name suggested: `_defined_before_core_up()`
collected every key defined **anywhere** in `main.yml`, with no line numbers at
all. It tested EXISTENCE while its name and its message both promised ORDER.
`nos_derived_secrets` is defined in `main.yml`, so it passed — and would have
passed if the fact were set on the last line of the file.

The suite was green at 3969 tests throughout.

## Why it waited

The estate's day-to-day loop is `tools/nos-stacks.sh` (no sudo, no vars_prompt)
and `--tags <service>` runs. A **full** `ansible-playbook main.yml` had not run
since P1 landed. The break was not dormant because it was rare; it was dormant
because the one path that exercises it is the one nobody runs casually — which
is also the path a release depends on.

## Fixed, in two places

**The break.** `pre-migrate` no longer passes `{{ vars }}`. `nos_state` reads
exactly three keys per service — `version_var`, `data_path_var`, `install_flag`
(`nos_state_lib.py:418-426`) — all named by `state/manifest.yml`: 152 names
across 64 services, not one a credential. They are now resolved one at a time
with `lookup('vars', …)`, so an undefined credential elsewhere in the play
cannot abort a read that never wanted it. Verified by a real run, not a
syntax-check: `--tags migrate`, `failed=0`, ok=387.

The secrets block could not simply move earlier: its input
`global_password_prefix` is set at `main.yml:1117` from the removal prompt,
after `pre-migrate`.

**The gate.** `_first_eager_consumer()` now *derives* the boundary — every
`{{ vars }}` in `main.yml` plus every import whose target uses one, at the line
of the import — and only definitions before that line count. It reports
`main.yml:1347 (tasks/blank-reset.yml)` today, which is after the secrets block
at 1231, so the ordering is now structurally sound rather than incidentally so.

Proven in both directions: green on the fixed tree, and with the boundary forced
back to 966 it names two offenders, `default.config.yml:257` and
`default.credentials.yml:46`, both `nos_derived_secrets`.

**One layer up, the same bug again.** The first cut of `_first_eager_consumer()`
matched `{{ vars }}` as raw text, and reported `pre-migrate` as an eager
consumer *after it had been fixed* — because the comment explaining the fix
quotes `{{ vars }}` four times. A detector that reads prose is the mistake this
gate exists to catch. It now reads code.

## What is still owed

- **The strategic fix is untouched.** `{{ vars }}` is still passed wholesale by
  `blank-reset.yml`, `core-up.yml` and others. CLAUDE.md files that under the
  ansible-core 2.24 track; this incident is evidence for moving it up, because
  every one of those sites carries the same latent ordering constraint and only
  one of them is now derived rather than assumed.
- **A full converge is not in any gate.** The suite cannot catch an ordering
  break that only a real play exposes. `tools/ci-local.sh` runs a syntax-check
  and a filter-load probe — neither reaches `pre-migrate`. The honest options
  are a wet-test that actually runs, or naming this as a known blind spot.
- The 73 credential references were being handed to a module that reads none of
  them, and were echoed back in `invocation.module_args` at `-vvv`. That surface
  is now closed for `pre-migrate` and open everywhere else.
