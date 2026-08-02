---
id: 2026-08-02-release-v0-10-beta
title: "v0.10-beta — the estate stops believing its own success reports"
date: 2026-08-02
namespace: nos-core
summary: "179 commits in the eleven days after v0.9-beta, and one sentence describes most of them: a step recorded its own outcome as the fact of having attempted, and the record was written by the attempting code. Notifications that stamped delivery on failure, a scan that stamped freshness without scanning, a daemon four converges older than its code, and a wiring layer with 175 swallowed failures against 2 asserts — all found by turning the same question on the estate. Around that: the cortex corpus reaches measurable parity, the genome's first layer lands, face learns four ways to read a table, and one filesystem stops being a wish and becomes a measurement."
tags: [release, cortex, genome, backup, security, observability, nos-face, filesystem]
release: v0.10-beta
actors: [pazny, claude]
related: [RELEASE.md, docs/plans/nos-genome-and-organelles.md, docs/plans/one-filesystem-architecture.md, docs/plans/per-user-container-roadmap.md]
---

`v0.9-beta` gave nOS a face and a self-model. `v0.10-beta` asks a less
comfortable question about everything underneath: **when a step reports success,
who wrote that record?**

The answer, far too often, was *the step itself* — and a step that cannot do its
job is exactly the step least able to notice.

## The sentence, and the family of defects behind it

It started as a one-line observation during an audit and turned out to be a
diagnosis:

> *A step records its own outcome as the fact of having **attempted**, and the
> record is written by the attempting code.*

Once stated, it kept matching things:

- **Notification delivery** stamped `dispatched_at` on *failure* as well as
  success — and the pending query selects on that column. One unreachable moment
  for ntfy or SMTP lost the message permanently and left the row
  indistinguishable from a delivered one. GDPR breach alerts routed through it.
- **A scan that never ran** stamped `status=scanned` with fresh timestamps. That
  fabricated freshness is precisely what the drift watcher reads for staleness —
  so the alarm built to make scan rot loud was being fed the value that silenced
  it.
- **Pulse ran 07-27 code through four converges.** The role's restart handler
  keyed on stdout from `pip --quiet`, which prints nothing, so `changed_when` was
  permanently false. The daemon was older than the code it was running, and the
  mechanism designed to notice was structurally incapable of it.
- **The wiring layer** carried **175 `failed_when: false`** against **2** real
  asserts. One of those two — Gitea's SSO-lockout guard — tested `.status` on a
  `command` result and could never fire at all.
- **Backup** could lose a source and still report *"Backup OK — N sources"*,
  because an absent source recorded nothing rather than recording a failure.

The corollary took longer to accept and matters more:

> *A gate you can satisfy by editing the gate is not one.*

That one was earned. A gate written during this cycle passed — because the same
commit taught it to render a token production had never heard of. Rewritten to
import the real substitution map, it immediately found a Pulse job whose token
had been shipping unrendered braces since 2026-07-14.

The division of labour that came out of it is now doctrine: **pytest owns the
shape, `--tags verify` owns the effect, `nos-smoke --strict` owns end-to-end
truth**, and none of the three may claim another's job.

## Then the converge audited the audit

The best part is what happened when the fixed playbook met a live estate. Three
more defects, all one level up — **checks that had never once executed the branch
they claimed to cover.**

The FreeScout ownerless-gate fired, loudly and correctly by its own logic,
against a FreeScout that had its admin all along. The probe behind it had never
worked: wrong working directory, *and* an `--execute` flag that tinker does not
have. It returned empty stdout, which the old comparison read as `0` — "no admin
exists". The gate was right to be loud and wrong about what it was reading.

Metabase, meanwhile, turned out never to have run its setup task against a
*configured* Metabase. `setup-token` comes back as JSON `null` once setup
completes, and one-arg `default('')` substitutes only *undefined* — so the None
reached `| length` and aborted the entire run. It worked for as long as it did
because it had only ever been exercised on a fresh install.

And the gate written to catch that class caught its own unsoundness first. The
real defect spans two lines — the `default()` in a `set_fact`, the `| length` in
a later `when:` over a differently-named fact. A single-expression scanner would
have shipped green against the very bug it was written for. It now follows the
laundered fact through the file, and found three more instances immediately.

## The cortex corpus agrees with itself, measurably

Verdict **`AGREE`** on all six clauses, `agreeStreak: **6**` — read from the
ledger on release morning rather than quoted from the gate night. KEAP and the
vendored organ each carry **2 500** taxonomy nodes with zero on either side
alone; `knowledge_objects[fs:]` **317/317**, `relations` **1 438/1 438**.

Getting there was mostly teaching the harness to stop inventing divergence it
could not see: the denominator was seeded, the capture queue made enumerable,
the vendored knowledge tree caught lagging the pin by ten nodes, and the organ's
corpus reader correctly identified as a *port* rather than a stray. Asymmetries
are now **named** rather than counted as drift — the estate's own 1 088 doc
nodes, the 97 nodes outside the referee's jurisdiction, the KEAP-only table
cards.

## The genome — L1, and the write path it needed

`state/genome/entity.schema.json` lands: a base entity with `identity` /
`compliance` / `access` / `cortex` / `face` facets, composed with `$ref` +
`allOf` — the first cross-file `$ref` in a repo whose eight schemas previously
contained **zero** composition between them.

The `access` facet reconciles five separate declarations of *"how is this
service reached and what gates it"* — the exact split that produced REM-144, an
unauthenticated Traefik dashboard on the edge leaking the global password prefix.

Then **L1 field concepts**: a closed, git-owned vocabulary so that every column
says what it *means*. All 76 columns across the five seeded DataTables carry a
`concept:` — and, crucially, they reach the **database** rather than only git,
because the same change added the write path `data_tables.schema_json` had never
had. Until then a table's columns were immutable for its lifetime: a changed
definition was a **silent no-op on every converged install**.

Honest scope, stated in the notes because it is easy to overclaim: the concept
token in a row body buys the *lexical* retrieval leg. It does not make embeddings
concept-aware. That is L2's job and is not claimed here.

## face — four ways to read a table

A DataTable now declares how it wants to be read — `grid`, `blog`, `timeline` or
`tiles` — persisted in the card's frontmatter beside the existing `graph` block,
with a prose editor for the body column. Declaring a style the data cannot
support **degrades and says so** instead of rendering an empty frame.

`/explore` gained a core mode that clusters by type, with θ frozen by hash so a
node keeps its position between sessions — spatial memory was the whole point of
the view, and rehashing on every load destroyed it. LOD opens roughly 2.5×
earlier and labels appear on hover rather than at point-blank range.

The reported *"skills appear twice, red and green"* was chased to ground and
**disproven at three levels** — object identity, graph payload ids, and the
placement branches, which are mutually exclusive. What looked like duplication
was two cluster envelopes drawn over one set of nodes. Worth recording as a
finding that wasn't: the honest outcome of an investigation is sometimes *no
bug*, and saying so is cheaper than a fix that changes nothing.

## One filesystem — measured, not built

The estate can hold the same document in three disjoint places and has no answer
to *"where does this file live"*. This release does not fix that. It establishes
what is true, which is the part that was missing.

**S-0 identity, first cut.** Nextcloud was the single service keying accounts on
a *hash* of the canonical uid. The subtle part: `mapping-uid` was already
`preferred_username`, so the configuration read correctly — the hashing comes
from a second setting, `uniqueUid`, layered on top. The config looked right and
the result was wrong, which is why reading it never caught it.

`--unique-uid=0` on both provider paths, plus a read-back that verifies the
**effect** — a 64-hex id is a hash whatever the provider table claims. And the
honest scope, which the converge itself prints: **this fixes the next login.**
The existing hashed account is still there, is not migrated, and moving it needs
`occ files:transfer-ownership` before any deletion.

Three architectures were written down and one rejected on the record, including
an uncomfortable finding: **POSIX mode bits are decorative on this estate.**
VirtioFS remaps ownership and every container runs as a different uid, so a
design depending on `chmod` would work on the Linux port and be theatre on the
operator's Mac.

Then `apple/container` was measured against Docker on a real 1.09 GB image
rather than a toy. Start time is a tie (2.1 s vs 2.4 s), bulk I/O favours apple
by ~30 %, `stat` favours Docker by **9×**, and the memory figures are *not* the
85× they appear to be — that is one container against a whole estate's shared
VM. The blocker is not performance: macOS gates published ports behind the
**Local Network** privacy permission, which no playbook can grant, and whose
failure mode is a listening socket that silently drops traffic.

Per-user containers are sequenced as their own roadmap, explicitly after this
tag.

## Security

**0 pending CRITICAL** — re-derived from the running estate rather than
inherited, which matters because this number has been wrong twice by
inheritance. Six queue items were already live at their fix version and had
simply never been reconciled. Both former CRITICALs are now confirmed against
`docker ps`, not merely pinned: Gitea `1.27.0` and Metabase `v0.61.9`.

Cycle-21 ran **unattended at 02:14 on release morning** — the nightly Pulse
scan, whose verdict pipeline had never once produced output until it was fixed
earlier in this cycle. Queue at cut: 152 items, 128 resolved, 15 pending.

Two open HIGHs a reader should weigh: `global_password_prefix` still defaults to
`changeme` with the weak-prefix assert not covering local tenants (REM-151 — the
other half of the REM-144 surface), and an n8n 17-GHSA advisory wave (REM-152).

The methodological lesson of the cycle recurred three times in one batch: **a
GHSA with no CVE id.** A scan phrased as *"no new CVE past the pin"* was
literally true and wrong by six days. Scan the vendor's advisory endpoint, not
the CVE feed.

---

The theme of `v0.9-beta` was *nOS can show you itself*. The theme of this one is
narrower and less flattering: **nOS can now be caught lying about itself** — by
gates that observe effects rather than attempts, and that were, in several
cases, made to fail against the defect before being trusted to pass.
