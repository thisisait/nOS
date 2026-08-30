# 37 — A deletion that passed five thousand gates

**Found 2026-08-30 06:00, by `tools/red-status.py` on the first check of the day.**

Five scheduled agent jobs red, all with the same stderr:

```
runtime error: Error: Class "App\AgentKit\VaultRequirement" not found
```

`conductor:self-test-001`, `librarian:judge-lint-queue`,
`librarian:brief-taxonomy`, `librarian:describe-taxonomy`,
`surveyor:surface-survey` — every AgentKit agent the estate runs on a schedule.

## Whose fault, and how it hid

Commit `1a54dcb0`, *"refactor: cut the coordinator surface, three otel deps, 26
dead vars"*, an over-engineering sweep. The coordinator subsystem was genuinely
dead — `Coordinator.php` and `ProcessPool.php` were ~800 unreachable lines, and
`RosterEntry` was its manifest type. `RosterEntry` lived in `Agent.php`, which
declares four classes, and **`VaultRequirement` went out beside it**.

`AgentLoader::load()` still constructs one per entry in a manifest's
`vault: required_credentials:` block. All eight agent manifests carry that
block. So the loader was calling `new` on a class that no longer existed.

**The full suite was green.** 5 174 gates at the time, and not one of them
loaded a real manifest through the real loader:

| gate | what it looks at |
| --- | --- |
| `test_agent_schema.py` | the YAML, against a JSON-Schema |
| `test_agentkit_naming.py` | class names, by grep |
| the tool-scope gates | their subjects, constructed directly |

Every check looked at a piece. Nothing assembled one.

## The sixteen hours

The deletion landed 2026-08-29 at ~09:00. The first failure was at 01:14 the
next morning — and the only reason the gap was that short is that a converge
happened to run in between and push the source to the host. **The repo was
broken for the whole day and the estate could not have known**, which is
CLAUDE.md's first section stated as a defect rather than as doctrine: a git ref
answers "what is in the repo", never "what is running".

Had nobody converged, the break would have waited for the next release.

## What was done, 2026-08-30

`VaultRequirement` restored with the account above in its docblock, converged
(`--tags wing`, 436 ok / 0 failed), and verified against the **deployed** tree,
not the repo: conductor 3 credentials / 3 tools, librarian 4/5, surveyor 3/4,
curator 4/4, proposer 2/3.

Gate: `tests/anatomy/test_every_agent_manifest_loads.py` builds every committed
manifest through `AgentLoader` and asserts the vault block reaches an object.
Retro-verified two ways — re-deleting the class reproduces the exact production
error, and making the loader drop the vault block fails the second assertion
while the first stays green.

## The ceiling this uncovered, unfixed

`Agent.php` declares four classes and PSR-4 resolves only the one named after
the file. `ToolSpec`, `VaultRequirement` and `SubscriptionSpec` exist solely
because something loads `Agent` first. That is true in production, and it was
true of the gate's own harness — whose first draft fatalled on `ToolSpec` and
looked like a broken tree.

So a future caller that constructs a `ToolSpec` without having touched `Agent`
fails exactly the way this fee did. **Splitting the file into four is the fix
and it is not done**, because it is a rename across the AgentKit surface and
this entry is a restore, not a refactor.

## The rule

A deletion sweep is the one change where "the tests pass" carries the least
information, because a suite is built from the shapes that exist. Removing a
shape removes the thing that would have complained. The cheap countermeasure is
not more unit tests — it is one gate per subsystem that **assembles the real
thing from the real inputs**, which is the only check whose passing depends on
everything the path touches still being there.
