# nOS Doctrine

**The constitution layer.** Each file here states *one* set of absolutely-key,
load-bearing decisions — terse enough to read in a few minutes, stable
enough that changing one is a deliberate act. Detail, rationale, and phasing live in
`docs/idea/` and `docs/` guides; doctrine files are the *canonical decision*, not the
essay.

**Rule:** if a design choice is one that a future contributor (or agent) could
plausibly get wrong by guessing, it belongs here. Keep each file short — the target
is well under ~130 lines (an axis-owning file like `layers.md` may run longer); when
one grows past that, the detail belongs in a `docs/idea/` or `docs/` companion,
linked from the doctrine file. (The old "10–80 lines" ceiling was asserted while six
of twelve files exceeded it and nothing enforced it — retracted 2026-08-18 rather
than kept as a rule that only ever reports its own defeat.)

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
| [foreign-properties.md](foreign-properties.md) | upstream facts we cannot fix, only route around: a healthcheck that cannot RUN in a minimal image is not a sick service; LSIO code-server is plain HTTP on 8443, so an upstream is HTTP until measured otherwise; `sslmode=require` means encrypt-and-verify in node-postgres and encrypt-without-verify in libpq — and the contract belongs to whoever PARSES the string, not to the driver under it | ✅ v1 |
| [four-trees.md](four-trees.md) | branch vs checkout vs worktree vs estate: nothing propagates on its own; `config.yml` is a fifth surface that outranks the defaults and is not in git | ✅ v1 |
| [layers.md](layers.md) | the `layer` axis (L0–L3, derived, `withheld` over guessed) and what the word `tier` may mean | ✅ v1 |
| [face-app-tiers.md](face-app-tiers.md) | face-app `form` + build-complexity (F1–F4/H) axes | ✅ v1 |
| [generative-ui.md](generative-ui.md) | a model FILLS a declarative render contract, never extends one: `TableView` twice at a repo boundary, one narrowing door, an action catalog that stays code; deterministic first, generation design-time; and the two rules a learning loop needs (it may not grade its own offers, and it proposes rather than applies) | ✅ v1 |
| [loops.md](loops.md) | the sequence axis: SERE + the nOS loop proper as verified Mermaid — every edge marked live/partial/target, the refusals, the missing-edge ranking, edge gates | ✅ v1 |
| [identity.md](identity.md) | the declared account roster is the one source; a realm's admin/allowlist is a projection of it; presence checked both directions (MISSING / UNDECLARED / `?`) | ✅ v1 |
| [security-floor.md](security-floor.md) | severity picks what is noticed now; what a row is *blocked on* picks whether a release boundary means anything to it — three lanes, four refused designs logged | ✅ v1 |
| [ponytail.md](ponytail.md) | the 7-rung ladder answered before code is written; deliberate shortcuts carry a `# ponytail:` marker harvested by `/ponytail-debt` | ✅ v1 |
| [agentkit.md](agentkit.md) | how an agent runs, spends, and satisfies: one runner door, scope-verb match, backend≠provider (gates 1–8), satisfaction is a gate run, one join key, roster status; §6 = operator's open rulings | proposed |
| [organs.md](organs.md) | four incompatible meanings of "organ" named; proposes the 3-axis fix (`stack`/`organ`/`layer`) — §3 awaits the operator's ruling | proposed |
| table-naming.md | DB table / column naming conventions | planned |
| taxonomy.md | taxonomy / ontology term definitions (KEAP taxonomy depth levels, node/pillar/block, relations — NOT the service `layer` L0–L3 axis, which layers.md owns) | planned |
| operator-model.md | the operator's five steps + who may decide what without them | live |
| agentkit.md | agent tool-mediation, scopes, FS/RBAC gating | planned |
| pulse.md | scheduled-job contract (job ids, tokens, catalog substitution) | planned |
| wing.md | Wing identity, RBAC tiers, DB-writer contract | planned |

Add a row when you add a file. Doctrine files are **live doctrine** (per
`docs/devlog/README.md` — `.md` = doctrine, devlog = history).
