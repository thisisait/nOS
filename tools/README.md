# tools/

Readers, entry points and one-offs. The estate's doctrine lives in `docs/`;
this is the machinery that answers questions about it.

## Where a new script goes

**The naming IS the structure, and it is load-bearing.** Every one of these is
referenced by path from CLAUDE.md, plugin manifests, pulse jobs, tests, docs and
the operator's memory — several hundred references in all — so a tidy-up that
moved files by category would break them for cosmetic gain. What holds instead
is a convention a reader can see from the filename:

| shape | means |
| --- | --- |
| `*-status.py` | a READER. Reports state, exits 0 whatever it finds, never writes. `--json` for a caller. An unreadable source is UNKNOWN, never green. |
| `nos-*` | an operator entry point — something a human runs by name. |
| `run-*.sh` | starts one bounded agent ceremony against the live estate. |
| `<family>-*.py` | one of a family: `loop-`, `roadmap-`, `devlog-`, `keap-`, `tofu-`, `ci-`, `sync-`. |
| `tools/<family>/` | a family with enough files to be its own directory and few enough callers to move (`retro-verify/`, `cc/`). |

Directories, and what is in them: `cc/` the control-centre pane registry ·
`retro-verify/` harnesses that reintroduce a defect and watch its gate go red ·
`workflows/` saved Workflow scripts · `git-hooks/` client-side push guards ·
`lib/` shell fragments other tools source · `orchestrator_hosts/` fleet host
definitions.

A new script that fits none of these is the signal to start a directory, not to
add a ninth prefix. Two rules that are not negotiable, because the estate has
paid for both: a reader may not write, and a script that cannot do its job must
not exit 0.

**This file is checked.** `tests/anatomy/test_the_tools_index_is_complete.py`
fails when a tool is added and not listed here — an index nobody maintains is
worse than none, because it reads as complete.

## Readers — what is true right now
- `_ledger_open.py` — One way to open the Wing ledger read-only, for readers that must not write.

- `agent-status.py` — What the agents are doing, and what came of the last ones.
- `agent-token-status.py` — agent-token-status — can each declared agent client mint a token RIGHT NOW.
- `anatomy-measure-margins.py` — Measure the nightly chain's temporal margins, and restamp the declared edges.
- `app-version.py` — What each container actually RUNS, against what the pin says it bundles.
- `awaiting-operator.py` — What is waiting for a HUMAN right now, across every source that asks for one.
- `caddy-status.py` — Can the caddy answer, is the ear listening, and what did it hear.
- `brew-pin-status.py` — How old is the version brew wants to give us, and is it old enough to adopt?
- `cortex-status.py` — What the cortex organ is, all of it — not just the part KEAP serves.
- `cortex-drift.py` — Compare the vendored cortex organ against the KEAP tree it was cut from.
- `discovery-scan.py` — Discovery: find two representations of one fact that disagree.
- `doctrine-cite.py` — Resolve every doctrine citation in the estate — or say exactly which do not.
- `graph-communities.py` — Computed communities vs the declared `stack`/`layer` axes; prints only the disagreement (docs/adr/0002-graphify-borrowings.md §2).
- `graph-report.py` — What the anatomy graph's SHAPE implies: god nodes, isolated nodes, and which measured edges cite a file that has moved since.
- `router-status.py` — The WAN router as a declared estate fact: presence probe + intent from state/router.yml; UNKNOWN when it cannot look.
- `elsewhere-status.py` — Estate work happening OUTSIDE the control centre, and how to get to it.
- `estate-status.py` — What is TRUE right now, across the three places a fact about nOS can live.
- `face-wiring-report.py` — nOS-face wiring report — the hard-doctrine linter for the web-desktop shell.
- `identity-status.py` — identity-status — the declared account roster vs what each realm holds.
- `loader-vars-report.py` — D1 scoping tool (2026-06-11) — the plugin-loader variable contract.
- `loop-status.py` — Which weakness sources actually produce proposals, and what came of them.
- `nos_identity.py` — The manifest row is the only place a service's spellings meet.
- `npm-ioc-scan.py` — Cross-check every installed npm package against a published IOC list.
- `plugin-wiring-report.py` — Plugin wiring report — capability matrix + contract checks.
- `permission-status.py` — What macOS will and will not let this estate do, in one place.
- `nos_work_uri.py` — Parse + match the nos-work:// routing address (dtt-routing-address); the planner's capability/assignment matcher.
- `red-status.py` — What is red on this estate right now.
- `reload-stale-config.py` — Make a running container read the config the estate rendered for it.
- `stale-config-status.py` — Containers running config the estate has already replaced.
- `rem-status.py` — What the security queue says, right now.
- `roadmap-status.py` — What the roadmap says, right now.
- `skill-status.py` — What is on the shelf, who should be holding it, and who actually is.
- `snapshot-status.py` — Is there a net under the next converge, and what exactly does it hold?
- `stuck-status.py` — What has STOPPED MOVING — which is a different question from what is broken.
- `task-types-render.py` — Render AGENTS.md (the task-type router) from state/task-types.yml.
- `tls-uptake.py` — How much of the datastore traffic on this estate is actually encrypted.
- `view-contract-drift.py` — Compare the face's `TableView` against KEAP's `viewMetaSchema`.
- `usage-status.py` — What each model budget has been spent on, and what is left.
- `wing-status.py` — What Wing actually is: every table, who writes it, who reads it, what it costs.

## Control centre — the tmux session and its panes

- `nos-cc.sh` — the terminal control centre.
- `nos-pane.py` — One control-centre pane. `nos-cc.sh` runs several; you can run one anywhere.
- `nos-statusline.sh` — one line of estate truth, for the tmux status bar.
- `nos-watch.sh` — render a reader's CURRENT OUTPUT on an interval, in place.
- `wf-panel.sh` — put the workflow tree in the nos-cc panel, and nowhere else.
- `workflow-lint.py` — Refuse a workflow script the runtime would reject — before it spends anything.
- `workflow-tree.py` — Draw a workflow definition as a tree, with live progress if a run is going.

## Agents and the loop

- `agent-report.py` — agent-report.py — print an agent's real report, losslessly.
- `aggregator-dry-run.py` — D3 — Authentik aggregator dry-run + parity report.
- `local-model-bench.py` — Measure a local model on the one job the estate has for it, with code as judge.
- `loop-diff.py` — Build a valid unified diff from a replacement an agent can state in words.
- `loop-pr.py` — The loop's driver: what happens after the judges say pass.
- `loop-propose.py` — The loop's ENTRY: hand one reported weakness to a model that may propose.
- `loop-review.py` — The reviewer: the only thing in the loop permitted to merge.
- `night-watch.py` — What we said the night would do, beside what it did.
- `nos-ops-harness.py` — nos-ops measurement harness — WHERE does the chain/tool-use boundary sit?
- `run-agent.sh` — tools/run-agent.sh — run an AgentKit agent against the LIVE estate.
- `run-journeys.sh` — tools/run-journeys.sh — run the e2e journeys against the LIVE estate.
- `run-librarian.sh` — operator-driven knowledge judgment (cortex Layer 2)
- `run-phase5-ceremony.sh` — operator-driven conductor self-test (Anatomy A8/A9)
- `run-surveyor.sh` — operator-driven surface survey (Anatomy A20)
- `run-upgrade-architect.sh` — operator-driven recipe authoring (W5-B5, 2026-05-27)

## Roadmap, devlog, docs

- `devlog-compile.py` — devlog-compile — validate nos-core devlog entries, emit the committed bundle.
- `devlog-post.py` — devlog-post — publish a devlog entry to an ON-SITE namespace via WP REST.
- `devlog-release.sh` — mechanical pre-flight for a release cut.
- `devlog-render.py` — devlog-render — static site generator for the nos-core devlog.
- `roadmap-apply-view.py` — Apply the roadmap definition's `view:` block to the live table.
- `roadmap-extract.py` — One-time: live roadmap table → per-row `<slug>.md` files in the PRIVATE seed repo.
- `roadmap-seed.py` — Seed / --sync the roadmap table from per-row files in the private seed repo (NOS_SEED_DIR).
- `roadmap_seed_lib.py` — Parser + public slug-index writer for the per-row seed files (machinery; content stays private).
- `roadmap-update.py` — Move a roadmap row's CLAIM. Not its verdict — that has a different writer.
- `roadmap-verify.py` — Write a roadmap row's VERDICT — which is an exit code, never an argument.

## KEAP / cortex

- `cortex-seed-fixtures.sh` — give the corpus diff something to measure
- `keap-branches-to-canonical.py` — Convert a fable branches-authoring JSON (structured pillars+blocks for empty
- `keap-fable-bundle.py` — Generate the raw-data bundle for the fable ontology-review pass.
- `keap-fable-to-bundles.py` — Transform the fable ontology-review output into per-domain import bundles.
- `dtt-capture.py` — File an idea/plan/spec into dtt as a per-row seed file in the private repo (the /dtt-capture skill's machinery).
- `keap_api.py` — Shared KEAP /api access for host tools: resolves the SEC-02 proxy secret + builds the human headers.
- `keap-recall-queries.py` — Emit the KEAP recall-query set from the estate's SKILLS.md trigger lines.
- `keap-reid-rows.py` — Make every row of a KEAP DataTable addressable by its own business key.
- `mcp-tables-server.py` — stdio MCP server giving external agents (Cursor/Codex/Claude Code) the DataTables verb surface.

## Release, CI, git
- `forge-sync.py` — The trunk's four holders, and the only tool that moves refs between them.
- `migration-pr.sh` — tools/migration-pr.sh — validate an authored migration record + its version
- `recipe-pr.sh` — tools/recipe-pr.sh — validate an upgrade recipe and (optionally) open a PR/MR
- `worktree-lease.py` — A lease over a worktree's SHAPE, so a long agent run cannot be cut from under.

- `ci-local.sh` — tools/ci-local.sh — run a command inside a FROZEN venv that reproduces the CI
- `deploy-from-ci.sh` — host-side deploy wrapper invoked by Wing's
- `promote-public.sh` — tools/promote-public.sh — promote a VETTED local change to a PUBLIC GitHub PR.
- `sync-trunk-to-gitea.sh` — tools/sync-trunk-to-gitea.sh — keep the writable Gitea agent forge's trunk
- `sync-trunk-to-gitlab.sh` — tools/sync-trunk-to-gitlab.sh — keep the GitLab agent forge's trunk

## Provisioning, secrets, identity
- `fetch-authentik-bootstrap-token.py` — Retrieve the ``nos-api`` Authentik token and persist it to secrets.yml.
- `nos-secret.py` — nos-secret — the operator's reader for the derived credential map (P1).

- `anatomy-graph-gen.py` — Compile the anatomy graph — every declared actor and edge, one address space.
- `apex-sign.py` — Sign the apex ruling — after showing what changed since it was last signed.
- `d12-annotate-plugins.py` — D1.2.b — add `name` + `enabled` to each plugin's authentik block.
- `e2e-auth-helper.py` — Provision / teardown ephemeral tester identities for Playwright e2e tests.
- `gdpr-dpa-register.py` — Generate the GDPR Article-30 DPA register (`state/dpa-register.md`).
- `gdpr-records.py` — Emit GDPR Article-30 records as a JSON array (machine-readable sibling of
- `genome-codegen.py` — Emit per-runtime artifacts from the nOS genome. One declaration, N languages.
- `import-coolify-template.py` — import-coolify-template.py — fetch a Coolify service template and emit a
- `nos` — operator entry point for the nOS playbook.
- `nos-os-update-arm.sh` — arm the cross-reboot continuation BEFORE a macOS update.
- `nos-smoke.py` — nos-smoke.py — post-run web-UI smoke test for nOS.
- `nos-stacks.sh` — run the Docker stack layer autonomously (no sudo, no prompt).
- `nos-upgrade-detached.sh` — run an upgrade DETACHED from the controlling TTY.
- `orchestrator-acceptance.py` — The four-item acceptance test every candidate orchestration host must pass.
- `pin-latest-scan.py` — What is each image pin missing, measured against its registry.
- `post-blank.sh` — tools/post-blank.sh — operator-facing post-blank verification runner.
- `scan-state-snapshot.py` — Record the nightly scan's output on its own branch, without touching yours.
- `tofu-authentik-adopt.sh` — tools/tofu-authentik-adopt.sh — ADR-0001 Phase 1 one-time tenant adoption.
- `tofu-authentik-gen-registry.py` — ADR-0001 Phase 1 — regenerate the OpenTofu Authentik service registry.
- `tofu-authentik-reconcile.sh` — tools/tofu-authentik-reconcile.sh — tofu-state ⇄ live-Authentik PK reconcile.
- `wing-telemetry-smoke.py` — wing-telemetry-smoke.py — end-to-end probe for the telemetry pipeline.
