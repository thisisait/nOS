---
title: Importing your data (the digest organ)
section: dev
order: 6
summary: Turn your counterparties and git repos into governed DataTables — parse → gate → absorb, idempotent and reversible.
---

## What it is

The **digest organ** ingests real data into the DataTables you already browse at
`:8443`, through one firebreak: **parse → normalize → GATE → absorb**. A bundle
that fails the gate never touches a live table. Every importer is a small Python
tool in `/srv/nos/tools/`; they all share the same gate (`nos_digest.check_bundle`)
and the same absorb (`digest_absorb`), so a new source is just a new parse step.

Two importers ship today. Both are **dry by default** (they print the bundle and
touch nothing) — add `--absorb` to write.

## Counterparties (CSV)

A CSV of the organisations you work with → the shared **party** spine. Columns:
`legal_name,ico[,trading_name][,country]`.

```
digest-import.py clients.csv            # gate + print, no writes
digest-import.py clients.csv --absorb   # upsert into KEAP
```

Identity is deterministic: the slug is derived from the IČO (`party-ico-<8>`), so
re-importing the same file **addresses the same rows** instead of duplicating them
(it dedups — a row already present is left as-is; field updates are not propagated
back yet).

## Repositories (git)

A directory of repos → the **repo → application → package** chain, each repo owned
by a party resolved against the spine above (so a repo owner is the same row a
contract references — never a duplicate).

```
digest-import-repos.py /path/to/repos             # gate + print
digest-import-repos.py /path/to/repos --absorb    # upsert into KEAP
```

Each repo is a subdirectory carrying a small `nos-repo.yml` sidecar (its owner IČO,
remote and head commit) plus its dependency manifests (`package.json`,
`requirements.txt`, `go.mod`). The sidecar is needed today because a repo's OWNER
IČO cannot be read from git — reading remote/head straight from `git -C` is a
planned convenience, but the owner→party mapping stays explicit. An owner it cannot
resolve to a known party is **skipped for review** — the importer never invents a
counterparty.

## Invoices (ISDOC + vision)

Two more importers ship: `digest-import-isdoc.py` (deterministic ISDOC e-invoice
XML) and `digest-import-vision.py` (vision-extracted `.extract.json` sidecars,
gated by an operator-verify + confidence-floor rung). Both compose the SAME
`invoice` row shape, each stamping which one produced it
(`invoice.source: isdoc|vision`, plus `verified`/`overall_confidence` for the
vision path — a row keeps its own provenance instead of looking identical
regardless of source).

**Storage convention — one root, a subdirectory per client (Model C: clients
are DATA, never a separate tenant):**

```
{nos_data_root}/tenants/<tenant>/users/<uid>/inbox/accounting/<book_owner-slug>/
├── incoming/    # operator-supplied originals: *.isdoc.xml, rendered PDF/image
├── extracts/    # invoice-vision-ocr agent output: <doc-id>.extract.json
└── processed/   # moved here by hand after a successful --absorb run
```

`<book_owner-slug>` is the resolved party slug — organization only, never an
RBAC/tenant boundary. Point either importer at `incoming/` or `extracts/` and
it reads the slug straight off the directory name:

```
digest-import-isdoc.py  .../accounting/synthetic-client-alfa/incoming
digest-import-vision.py .../accounting/synthetic-client-alfa/extracts
```

`--book-owner-ico` is still accepted and now cross-checked against the
directory: if both are given and disagree, the run refuses outright rather
than guess which one is right. Given only the directory, the slug must
already be a known party (never minted from a folder name).

## Undo (test freely)

Any bundle is reversible, leaf-first, and a row another table still needs is
**retained**:

```
digest-import-repos.py /path/to/repos --out /tmp/b.yml   # write the bundle
digest-teardown.py /tmp/b.yml                             # dry-run: what would go
digest-teardown.py /tmp/b.yml --confirm                   # delete this import
```

So a from-scratch retry is cheap: absorb, inspect, tear down, repeat. Tokens come
from your shell environment (`/etc/profile.d/nos.sh`); a tier-3 user reads, a
maintainer writes — the same rules KEAP applies to everyone.
