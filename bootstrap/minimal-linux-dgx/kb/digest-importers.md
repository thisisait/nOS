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
re-importing the same file **patches** the same rows instead of duplicating them.

## Repositories (git)

A directory of repos → the **repo → application → package** chain, each repo owned
by a party resolved against the spine above (so a repo owner is the same row a
contract references — never a duplicate).

```
digest-import-repos.py /path/to/repos             # gate + print
digest-import-repos.py /path/to/repos --absorb    # upsert into KEAP
```

Each repo is a subdirectory; the importer reads its dependency manifests
(`package.json`, `requirements.txt`, `go.mod`) and its git remote/head. An owner
it cannot resolve to a known party is **skipped for review** — the importer never
invents a counterparty.

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
