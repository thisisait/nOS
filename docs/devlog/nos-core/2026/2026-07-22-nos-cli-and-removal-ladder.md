---
id: 2026-07-22-nos-cli-and-removal-ladder
title: "One command, four levels — and the gates that had never run"
date: 2026-07-22
namespace: nos-core
summary: "blank, flush=deep and uninstall become one ladder behind a nos CLI: remove=none|data|deep|all, dry-run unless confirmed, --leave to stop after teardown. The plan was written, independently reviewed, REJECTED, rebuilt and only then built. Then the first live run found four more defects the whole review missed — including a preflight that had never once succeeded, and a removal that deleted paths the deploy had stopped writing to."
tags: [cli, lifecycle, removal, doctrine, gates, hidden-fees, keap, contracts]
release: v0.9-beta
actors: [pazny, claude, fable]
related: [docs/nos-cli.md, docs/doctrine/gates.md, docs/doctrine/cross-repo-contracts.md, docs/hidden_fees/README.md]
---

The operator's question was small: *"shouldn't we get rid of `--blank`? It is
against the whole idea of idempotence."* The answer took three design passes, a
rejection, and a live estate torn down and rebuilt twice.

## The ladder

`blank=true`, `flush=deep` and `uninstall=true` were three switches that had
grown independently, overlapped in scope, and disagreed about what they
preserved. They are now one ordered ladder behind a `nos` CLI:

| | removes | keeps |
|---|---|---|
| `--remove=data` | derived state (DBs, app data, stacks) | source, images |
| `--remove=deep` | + images, build + Homebrew caches | source |
| `--remove=all` | + user source, anatomy runtime, `~/.nos` | media, library, checkout |

`--leave` is orthogonal: end the play after removal instead of reconverging —
the machine-handoff case. Every level is a **dry run** unless confirmed: it
prints the resolved inventory, path by path, with `[exists]`/`[absent]` against
the live filesystem, and stops. The old switches still work; a shim maps them
in, unconditionally, so a legacy `-e blank=true` behaves exactly as before.

Two properties matter more than the vocabulary. First, `tasks/removal-set.yml`
is now the **single source of truth** for what each level touches — the dry-run
printer, the wipe, the source removal and the verifier all read the same list,
so they cannot drift apart. Second, there is a **post-removal absence
assertion**: after removing, the run stats every path it claimed to remove and
fails loudly listing survivors. That exists because of the 2026-07-21 incident
where an uninstall reported success while leaving 2.1 GB of `~/keap` and a
Nextcloud tree behind, and the surviving config then broke the next install.

## The plan was rejected, and that was the point

The design was produced by one multi-agent workflow, then handed to an
independent reviewer with a fresh context and no stake in it. The verdict was
**DO NOT BUILD YET**, and the reason was exact:

> the entire safety contract — confirm gates execution, dry-run is the default,
> `remove=all` removes what the ceremony names, `-y` is non-interactive,
> `--leave` stops — exists only in prose. Not one of those five behaviours
> appears in any commit's contents.

It was right. The plan documented a machine it never built, and every gate it
specified would have gone green over the gap. The rebuild made each documented
invocation trace to an implementing diff at every intermediate commit window;
the second review passed it with one change.

That review also demolished a premise the author had written into the brief as
fact — that `blank=true` does not prompt. It prompts twice, and the spec would
have deleted both gates. *An assertion from memory is not evidence, even when
it is your own.*

## Then it ran, and the review's blind spots showed

Four defects survived design, review and 1887 passing tests, and were found in
the first hours of live use. All four share a shape.

**The removal answered a question the deploy had stopped asking.** The
external-SSD path overrides were applied to the removal list whenever
`external_storage_root` was non-empty — which it is *by default* — while the
deploy applies them only under `configure_external_storage`. Post-FS-doctrine
those two diverged, so the removal deleted `/Volumes/SSD1TB/*` paths that were
mostly absent while the real platform data survived. And the absence assertion
went **green**, because it measured the same wrong list. One gate now pins both
conditions to each other: *whatever decides where data is written must decide
where it is removed.*

**A preflight that had never once succeeded.** The Docker external-mount probe
re-registers its result inside a self-heal block. A skipped task still
registers — as `{skipped: true}`, with no `rc` — so on every run where self-heal
did not fire, the healthy probe's result was overwritten by a skip,
`rc | default(1)` read 1, and the preflight failed on a working mount. Every
time. It had gone unseen because the probe only arms when `nos_data_root` is
under `/Volumes`, which became true for the first time on this very day.

Before that was found, the same preflight told the operator, with confidence and
a specific remedy, that Docker's VM held a stale mount — when the real cause was
a pruned probe image. The file had *already computed* the classification that
distinguishes the two; only the failure message ignored it. The nastiest part is
the remedy: restarting Docker Desktop takes long enough for the image to pull,
so the run passes on the retry and the false diagnosis appears to be cured by
its own medicine. **A misdiagnosis that appears to work will never be
reported.**

**The banners described a run that no longer existed.** `remove=all --leave`
tore the estate down correctly and stopped exactly as designed — while
announcing `BLANK RESET COMPLETE … Playbook now continues with clean
installation`. The confirmation box listed `~/nos/tenants/**` under *"Will
remain"* during the one level that deletes it. The sudo prompt promised that
pressing Enter would make root tasks "fall back to manual mode"; they hard-fail,
and it cost a live install. These are now [`hidden_fees/07`](../../hidden_fees/07-messages-that-outlive-their-mode.md):
text is a claim about the current run, and if its truth depends on a flag it
must read that flag.

## The gates were the subject

The pattern under all of it is in [`docs/doctrine/gates.md`](../../doctrine/gates.md),
and this arc kept proving it in new ways:

- The confirmation gate pinned the **literal** string `remove=deep`. A
  `remove=all` run printed it verbatim — so the gate had *certified* the lie it
  existed to prevent. It now asserts the line renders the running level.
- The gate that guards the ENTER box did not guard the closing banner, because
  it had been written around the fix that touched the box. **A gate written
  around an existing fix certifies the fix, not the class.**
- Two gates went red on *documentation* naming the thing they police — and the
  reflex that fixes is to delete the sentence, which is backwards. They now skip
  comments and assert on the live template.
- One new gate initially forbade a string everywhere, which forbade its own fix;
  it now measures semantics (failure conditions and messages) instead of text.

## Cross-repo, as peers

In parallel, the self-model contract with KEAP was negotiated to **v1** and
flipped live: slug taxonomy ids (`nos`, `nos.infra.postgresql`), a canonical
knowledge format, a producer-owned golden fixture, and **symmetric** gates —
each repo pins the other's half. The protocol is written down in
[`docs/doctrine/cross-repo-contracts.md`](../../doctrine/cross-repo-contracts.md),
including the rule that made it work: no hierarchy between the agents, and an
objection blocks a version bump. Both halves of the contract failed on their own
scaffolding before they ever failed on data — nOS's producer gate never passed
`--schema`, so the path it guarded was inert and every check was green over
nothing.

## Where the estate lives now

`nos_data_root` moved to the external SSD — one line, because every service and
tenant path derives from it. Deliberately *not* the older
`configure_external_storage` mechanism, which redirects per-service variables:
mixing them would put data under two roots and desync removal from deploy again.

The arc closed the way it should: a full teardown at `--remove=all --leave`, then
a clean all-on install — **1531 tasks, `failed=0`, 63 containers, none
unhealthy**.

## Still owed

[`docs/hidden_fees/`](../../hidden_fees/README.md) is the ledger, and it is
honest about being unpaid: disabled-service overrides still linger, the
DB-blind-healthcheck class is closed for one service out of many, `docs/systems/`
covers a third of the estate. Fee 07 has a mechanism nobody has explained yet —
a long task's log banner arrived five minutes after the task provably started,
so the log named the wrong current task — and it is recorded *without* a
guessed remedy, on purpose.
