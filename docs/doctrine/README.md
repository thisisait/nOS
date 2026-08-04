# nOS Doctrine

**The constitution layer.** Each file here states *one* set of absolutely-key,
load-bearing decisions in **10–80 lines** — terse enough to read in a minute, stable
enough that changing one is a deliberate act. Detail, rationale, and phasing live in
`docs/idea/` and `docs/` guides; doctrine files are the *canonical decision*, not the
essay.

**Rule:** if a design choice is one that a future contributor (or agent) could
plausibly get wrong by guessing, it belongs here. Keep each file short — if it grows
past ~80 lines, the detail belongs in a `docs/idea/` or `docs/` companion, linked from
the doctrine file.

## Files

| Doctrine | Defines | Status |
|---|---|---|
| [filesystem.md](filesystem.md) | storage layout, `nos_data_root`, data classes, isolation | ✅ v1 |
| [observability.md](observability.md) | telemetry/callbacks are best-effort, never gate a run; circuit-breaker, sidecar, secret single-source | ✅ v1 |
| [secrets.md](secrets.md) | shared-secret single resolved source (`~/.nos/secrets.yml`); no self-ref template to raw consumers; daemon self-heal | ✅ v1 |
| [virtiofs.md](virtiofs.md) | Docker Desktop VirtioFS bind risk; sockets/locks/mmap-DBs off the bind (tmpfs/named volume); `# VFS-DOCTRINE:` markers; macOS-27 tightening detectable | ✅ v1 |
| [face.md](face.md) | nOS-face: vendored-in-repo, edge-token identity, SoC→DataTable→user-state, native-over-iframe, XSS/filename/UTF-8 safety, the enforcement triplet | ✅ v1 |
| [gates.md](gates.md) | a gate that can pass without checking is worse than none; missing evidence = FAIL, and a green check pointed at a stale artifact is the same defect from the other side; assert on substance, never on silence | ✅ v1 |
| [cross-repo-contracts.md](cross-repo-contracts.md) | shared surfaces with a sibling repo: one spec, a producer-owned fixture, **symmetric** gates; peer rules (no hierarchy, objections block a version bump); identity/visibility/removal invariants | ✅ v1 |
| [workflows.md](workflows.md) | multi-agent fan-out must be **union** or **veto** (selection banned); a chain is not a fan-out; the gate reads evidence, not model trust; discovery files / implementation authorises via a COMMITTED spec, never a status; recursion needs asymmetric judgement + a retro-red ratchet | ✅ v1 |
| [four-trees.md](four-trees.md) | branch vs checkout vs worktree vs estate: nothing propagates on its own; `config.yml` is a fifth surface that outranks the defaults and is not in git | ✅ v1 |
| table-naming.md | DB table / column naming conventions | planned |
| taxonomy.md | taxonomy / ontology term definitions (L0–L4, node/pillar/block, relations) | planned |
| agentkit.md | agent tool-mediation, scopes, FS/RBAC gating | planned |
| pulse.md | scheduled-job contract (job ids, tokens, catalog substitution) | planned |
| wing.md | Wing identity, RBAC tiers, DB-writer contract | planned |

Add a row when you add a file. Doctrine files are **live doctrine** (per
`docs/devlog/README.md` — `.md` = doctrine, devlog = history).
