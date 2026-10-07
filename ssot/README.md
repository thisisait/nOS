# nOS Doctrine

**The constitution layer.** Articles live in `doctrine/` (realm map:
[`INDEX.yml`](INDEX.yml)); `proposed` rows are warehouse originals under
`docs/doctrine/`, not law. Each article states *one* set of absolutely-key,
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
| [filesystem.md](doctrine/filesystem.md) | storage layout, `nos_data_root`, data classes, isolation | ✅ v1 |
| [observability.md](doctrine/observability.md) | telemetry/callbacks are best-effort, never gate a run; circuit-breaker, sidecar, secret single-source | ✅ v1 |
| [secrets.md](doctrine/secrets.md) | shared-secret single resolved source (`~/.nos/secrets.yml`); no self-ref template to raw consumers; daemon self-heal | ✅ v1 |
| [virtiofs.md](doctrine/virtiofs.md) | Docker Desktop VirtioFS bind risk; sockets/locks/mmap-DBs off the bind (tmpfs/named volume); `# VFS-DOCTRINE:` markers; macOS-27 tightening detectable | ✅ v1 |
| [face.md](doctrine/face.md) | nOS-face: vendored-in-repo, edge-token identity, SoC→DataTable→user-state, native-over-iframe, XSS/filename/UTF-8 safety, the enforcement triplet | ✅ v1 |
| [gates.md](doctrine/gates.md) | a gate that can pass without checking is worse than none; missing evidence = FAIL, and a green check pointed at a stale artifact is the same defect from the other side; assert on substance, never on silence | ✅ v1 |
| [cross-repo-contracts.md](doctrine/cross-repo-contracts.md) | shared surfaces with a sibling repo: one spec, a producer-owned fixture, **symmetric** gates; peer rules (no hierarchy, objections block a version bump); identity/visibility/removal invariants | ✅ v1 |
| [workflows.md](doctrine/workflows.md) | multi-agent fan-out must be **union** or **veto** (selection banned); a chain is not a fan-out; the gate reads evidence, not model trust; discovery files / implementation authorises via a COMMITTED spec, never a status; recursion needs asymmetric judgement + a retro-red ratchet | ✅ v1 |
| [foreign-properties.md](doctrine/foreign-properties.md) | upstream facts we cannot fix, only route around: unrunnable healthchecks, HTTP-until-measured upstreams, the `sslmode` contract belongs to whoever PARSES the string; full measured stories in [docs/foreign-properties-companion.md](../docs/foreign-properties-companion.md) | ✅ v1 |
| [four-trees.md](doctrine/four-trees.md) | branch vs checkout vs worktree vs estate: nothing propagates on its own; `config.yml` is a fifth surface that outranks the defaults and is not in git | ✅ v1 |
| [layers.md](doctrine/layers.md) | the `layer` axis (L0–L3, derived, `withheld` over guessed) and what the word `tier` may mean | ✅ v1 |
| [face-app-tiers.md](doctrine/face-app-tiers.md) | face-app `form` + build-complexity (F1–F4/H) axes | ✅ v1 |
| [generative-ui.md](doctrine/generative-ui.md) | a model FILLS a declarative render contract, never extends one: `TableView` twice at a repo boundary, one narrowing door, an action catalog that stays code; deterministic first, generation design-time; and the two rules a learning loop needs (it may not grade its own offers, and it proposes rather than applies) | ✅ v1 |
| [loops.md](doctrine/loops.md) | the sequence axis: SERE + the nOS loop proper — the refusals, the missing-edge ranking, edge gates; the verified Mermaid diagrams and full accounts in [docs/loops-companion.md](../docs/loops-companion.md) | ✅ v1 |
| [loop-contract.md](doctrine/loop-contract.md) | the loop engine contract: Bone owns the ledger, budget and judges; HTTP is the only implementation; what a proposal may never touch (promoted from `docs/idea/11-agentic-loop-contract.md` 2026-10-07) | ✅ v1 |
| [sso.md](doctrine/sso.md) | one SSO mode per service (`native_oidc`, `header_oidc`, `forward_auth`, `none`), one spelling, never gated twice, `tier` means RBAC | ✅ v1 |
| [identity.md](doctrine/identity.md) | the declared account roster is the one source; a realm's admin/allowlist is a projection of it; presence checked both directions (MISSING / UNDECLARED / `?`) | ✅ v1 |
| [security-floor.md](doctrine/security-floor.md) | severity picks what is noticed now; what a row is *blocked on* picks whether a release boundary means anything to it — three lanes, four refused designs logged | ✅ v1 |
| [session-threat-model.md](doctrine/session-threat-model.md) | the attacker is the assistant session: assets, persistence + trigger traces, the same-user ceiling (separate macOS user is the only boundary), the push-time decision model; monthly review as front-matter data | ✅ v1 |
| [immune-system.md](doctrine/immune-system.md) | indicators are senses with one indicator contract (antigen, receptor, effector, heartbeat, lifespan, tolerance, verdicts, definition); Pulse runs them on a clock, the inbox is the nervous system, silence is a red, crawlers die, a regulator demotes indicators that cry wolf; monthly review as front-matter data | ✅ v1 |
| [ponytail.md](doctrine/ponytail.md) | the 7-rung ladder answered before code is written; deliberate shortcuts carry a `# ponytail:` marker harvested by `/ponytail-debt` | ✅ v1 |
| [agentkit.md](../docs/doctrine/agentkit.md) | how an agent runs, spends, and satisfies: one runner door, two scope vocabularies, backend≠provider, vault is a pointer, satisfaction is a gate run — §6 awaits the operator | proposed |
| [body-plan.md](doctrine/body-plan.md) | one word, one meaning: the lexicon is the source, the glossary its rendering, a gate keeps both true; the levels genome → habitat; where the four old meanings of "organ" went | proposed |
| [backoffice.md](../docs/doctrine/backoffice.md) | organ system **backoffice**; the backoffice **tissue** (installed by the `praxis` profile) is the set inside it, not a daemon; KEAP tables SoT, Espo join, digest is the intake | proposed |
| [genome.md](doctrine/genome.md) | the genome as shipped: lexicon, entity schema with its facets, genes, codegen; facts are data, capabilities are code | proposed |
| [tissue.md](doctrine/tissue.md) | a tissue is one manifest of existing ids (cells, skills, tables, services, reflexes); Art. 30 inherited from its members; install = profile, remove through the ladder, export carries files not rows; accepted by a fixture | proposed |
| [n8n-packs.md](../docs/doctrine/n8n-packs.md) | external HTTP pulls into KEAP DataTables: n8n is the runner, nOS the contract (pack graph, keap_write, one Pulse reader) | proposed |
| [ssot.md](doctrine/ssot.md) | address + INDEX map; in-force articles live under `ssot/doctrine/` | live |
| table-naming.md | DB table / column naming conventions | planned |
| taxonomy.md | taxonomy / ontology term definitions (KEAP taxonomy depth levels, node/pillar/block, relations — NOT the service `layer` L0–L3 axis, which layers.md owns) | planned |
| [operator-model.md](doctrine/operator-model.md) | the operator's five steps + who may decide what without them | live |
| pulse.md | scheduled-job contract (job ids, tokens, catalog substitution) | planned |
| wing.md | Wing identity, RBAC tiers, DB-writer contract | planned |

Add a row when you add a file. Doctrine files are **live doctrine** (per
`docs/devlog/README.md` — `.md` = doctrine, devlog = history).
