# Multi-Agent Batch Playbook

> **Status:** Phase 1 retro doctrine. Pin this before spawning the next
> wave (Phase 3 alloy consumers, A8 conductor sub-batches, A10 audit
> presenter updates).
>
> **Last incident:** 2026-05-04/05 Phase 1 batch, 10 workers in parallel
> worktrees, multiple cross-leak failures. Forensic + mitigation below.

## Why this doc exists

Spawning 10+ agents in parallel `isolation: "worktree"` mode looked clean
on paper: each worker gets a temporary git worktree (own working tree,
own branch), works in isolation, opens a PR. In practice:

| Symptom (Phase 1) | Mechanism | Worker(s) affected |
|---|---|---|
| Files showed up as untracked in the **main** worktree after agent quota cut | Worker used absolute path `/Users/pazny/projects/nOS/...` for Write calls instead of its assigned worktree path | U6 (7 plugin dirs) |
| Worker B's commit landed on Worker A's branch | Worker B `cd`'d (or did `git checkout`) into Worker A's worktree path | U7's commit on `feat/u9-wing-docblocks-a` |
| Worker reported pre-existing dirty state on first checkout | Sibling workers had already dropped files into the same parent path | U9 saw U6 + U10 edits |
| Branch existed at master HEAD with no commits | Worker quota cut before any `git add && git commit` reached its branch | U6, U7 (later recovered via parent-worktree leak) |

## Root cause

**Prompt engineering, not git.** The Phase 1 worker prompts opened with:

> Project root: `/Users/pazny/projects/nOS` (your worktree is an isolated copy).

Agents took the **absolute** path literally. Their tools (Read / Write /
Bash with absolute paths) bypass the worktree's working-directory
boundary because git worktrees are filesystem-isolated by location, not
by namespace. Once an agent uses `/Users/pazny/projects/nOS/...` paths,
it's writing to the parent — not its own copy.

There is no bug in `git worktree`. There is a bug in how the
coordinator briefs workers.

## Worker-prompt doctrine (use this template)

```text
You are worker U<N> in the nOS <Phase-name> multi-agent batch. Plan:
~/.claude/plans/<plan-file>.md

WORKTREE — CRITICAL:
- Your CWD is your isolated git worktree (assigned by the runtime).
- DO NOT hardcode `/Users/pazny/projects/nOS/...` ANYWHERE. That is the
  parent repo and writing there leaks into other workers.
- Use RELATIVE paths from CWD only: `files/anatomy/plugins/...`,
  `roles/pazny.x/...`, etc.
- Before any Write/Edit, run:
    pwd
    git rev-parse --show-toplevel
  These two MUST be equal AND must NOT be `/Users/pazny/projects/nOS`.
  If they are, STOP and report `worktree-not-isolated`.
- Before any Bash with `cd ...`, prefer no `cd` at all (rely on CWD).
  Never `cd /Users/pazny/projects/nOS` — that breaks isolation.
- Branches: assigned automatically (`worktree-agent-<id>` or operator
  pre-named). Do NOT `git checkout` into another worktree's path.

GOAL: <one-line>
YOUR UNIT: <title>
FILES TO CREATE/EDIT: <list of relative paths>
PATTERN to follow — read first: <list of relative reference paths>
FORBIDDEN WRITES (operator-only Phase 2): <list>
E2E TEST RECIPE: <commands using relative paths>

After you finish:
1. Skill `simplify` to clean up.
2. Run e2e recipe. If anything fails, fix or stop and report.
3. `git status` — should show ONLY files in your unit's scope.
4. Commit (Conventional Commits + surgeon-style; NO Co-Authored-By).
5. Push branch: `git push -u origin <branch>` (or report "PR: none — <reason>").
6. End with: `PR: <url>` (or `PR: none — <reason>`).
```

## Coordinator pre-spawn checklist

Before launching a parallel batch:

1. **Pin the plan**: `~/.claude/plans/<name>.md` written + reviewed.
2. **Forbidden-writes contract**: list the shared-spine files no worker
   may touch (`default.config.yml`, `state/manifest.yml`, `tasks/stacks/
   core-up.yml`, `files/anatomy/module_utils/load_plugins.py`,
   `files/anatomy/skills/contracts/*`).
3. **Non-overlapping scope**: every worker's file list must be disjoint
   from siblings'. If two units touch the same file (e.g. U5 + U8 both
   creating `nextcloud-base/plugin.yml`), explicitly mark it in BOTH
   prompts as a "coordinate-on-collision" and pre-decide who lands
   first.
4. **Per-worker prompt**: copy the worker-prompt doctrine above
   verbatim.
5. **E2E recipe**: every worker has a runnable verification step. For
   plugin work: `PYTHONPATH=files/anatomy python3 -m
   module_utils.load_plugins smoke --root files/anatomy/plugins` is the
   universal smoke gate.
6. **Throttle**: max 5 workers in parallel until the worktree-isolation
   discipline is verified by a small (3-worker) trial. Phase 1's 10-way
   parallel was too wide; the leak rate scales with parallelism.

## Coordinator post-batch checklist

When notifications arrive:

1. **Trust but verify** — read the actual diff in each merged PR / merged
   branch. Don't trust the agent's summary alone.
2. **Check for cross-contamination** — `git status` in the main
   worktree should be **clean** before any merge. If untracked files
   appeared, a worker leaked.
3. **Smoke gate before merging** — checkout each branch, run smoke,
   reject if degraded. Or run smoke on the merged result and revert
   the offending branch if it fails.
4. **Schema validation** — for plugin contributions: `python3 -c "import
   yaml,json,jsonschema; jsonschema.validate(yaml.safe_load(open('state/
   manifest.yml')), json.load(open('state/schema/manifest.schema.
   json')))"`.

## Mitigation menu (in increasing strength)

| Option | When | Trade-off |
|---|---|---|
| Better prompts (doctrine above) | Default | Cheap, high leverage; assumes agent compliance |
| Throttle parallelism (≤5) | Until 3-worker trial passes | Slower walltime |
| Pre-flight asserts in prompts | Always | Catches the 5% of agents that ignore prompt rules |
| Serial single-thread agents | When stakes are high (Phase 3 gates A8) | Fully eliminates cross-leak; lose the parallelism win |
| File-level `chattr +i` lock outside worktree | Last resort | OS-specific, fragile |

## Reference Phase 1 forensic

- Plan: `~/.claude/plans/cuddly-fluttering-lecun.md`
- 10 workers (U1-U10), 5 hit Anthropic quota mid-work
- 4 PRs landed cleanly (#1 grafana-prom, #2 grafana-loki, #3
  grafana-tempo, #4 wing docblocks A, #5 alloy-base)
- Operator manually consolidated the rest into linear master commits
  in commit `5dc5447` and follow-up `36ccb64`
- Total Phase 1 yield: 33 new plugins (9 → 42 live), 80/80 OpenAPI
  summaries, 0 schema errors
- Despite the leak, no work was lost — the consolidation pass
  recovered everything that was on disk

## Doctrine summary

> The worktree is **filesystem-isolated**, not **namespace-isolated**.
> If a worker uses absolute paths to the parent repo, isolation
> evaporates. Brief workers in **relative paths only** + assert their
> CWD is correct before any write.
