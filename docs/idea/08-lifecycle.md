# 08 — Lifecycle: blank, upgrade, coexist

**Status: mid-build. The engines are mature; two of their headline claims are
still unexercised.**
**Detail:** [`blank-uninstall-managed-resources.md`](../archive/blank-uninstall-managed-resources.md) ·
[`agentic-upgrade-migration-coexistence.md`](../archive/agentic-upgrade-migration-coexistence.md) ·
[`macos27-golden-gate-readiness.md`](../archive/macos27-golden-gate-readiness.md)

## The removal ladder — shipped

`nos --remove=none|data|deep|all`, dry-run without `--confirm`, `--leave` for a
non-interactive teardown. The install↔leave loop closes.

**The open half is reconciliation, not removal.** A blank wipes an *allowlist*,
not a manifest of what the estate actually manages — so a service added since
the list was written (KEAP was one) survives a wipe and becomes drift. The fix is
a manifest of managed resources, and the two-layer case is real: KEAP has derived
`/data` and source `/user-files`, and the filesystem must be cleared before the
database, not after.

## The upgrade engine — built, barely exercised

Recipes, migrations and coexistence all exist and are agent-authorable. What has
actually run end-to-end is thin:

- **Gitea 1.26 → 1.27** — a real agent-authored recipe, applied.
- **PG 16 → 17** — pg17 verified running *beside* pg16 on the coexistence track.
  **The cutover itself has never been performed.** That is the headline
  acceptance criterion of the whole framework and it is unmet.

A lesson already paid for: **a dry run is a false positive.** It short-circuits
before handlers, so "success" means nothing about the apply path. And an applied
upgrade **must bump the role-default version var**, or a plain re-render reverts it.

## macOS 27 "Golden Gate"

A readiness sweep exists; the 16 `v07-darwin27-*` documents behind it were
archived unimplemented. The live successor is the readiness plan, and the
ansible-core 2.24 jump is tracked in CLAUDE.md's tech debt — a floor bump plus a
collection review, ~4 hours, not a track.

## The gate that reports success it did not earn

`stack-health-probe.py` passes an **empty stack** as `0/0 ready`. That is why the
Linux wet-test was green for weeks with no infra rendered at all.

v0.10-beta improved this by accident and then on purpose: the playbook now runs
end-to-end on Linux (`ok=550`, up from 226) and fails honestly at the smoke gate
— `Infra: FAILED`, 1 of 8 probes. **The estate does not serve on Linux.** The
gate is honest now; the port is not done.

## Next

PG 16→17 cutover, as the framework's own acceptance test · the managed-resource
manifest · make an empty stack a failure, not a pass.
