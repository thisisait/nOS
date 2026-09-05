# Roadmap seed — the machinery is here, the CONTENT is private

The nOS Roadmap is a DataTable in KEAP. Its rows are authored as **one
markdown+frontmatter file per row** (`dtt-seed-per-row-file`,
`docs/plans/datatables-subsystem.md` §6) — readable, diffable, and atomic for
parallel agents (two agents editing two rows touch two files).

**The row files do NOT live here.** nOS is a public repo; the rows are the
operator's ideas, plans and security backlog. So the files live in a **separate
private repo**, and only the machinery ships in public nOS:

| public nOS (this repo) | your private seed repo (`NOS_SEED_DIR`) |
|---|---|
| `state/roadmap/_template.md` — the format | `<slug>.md` — one file per row |
| `state/roadmap/README.md` — this | committed there, never here |
| `tools/roadmap_seed_lib.py` — the parser | |
| `tools/roadmap-seed.py` — the loader | |
| `tools/roadmap-extract.py` — the extractor | |
| `state/keap-tables/roadmap.table.yml` — schema | |

## Where the files live

`NOS_SEED_DIR` (default `~/nos-seed`). Point it at your private clone:

```bash
export NOS_SEED_DIR=~/projects/nos-seed   # your private repo
```

## First-time migration (once)

The rows already exist in the live table. Extract them into the private repo:

```bash
NOS_SEED_DIR=~/projects/nos-seed tools/roadmap-extract.py           # dry run
NOS_SEED_DIR=~/projects/nos-seed tools/roadmap-extract.py --write   # write files
cd ~/projects/nos-seed && git add -A && git commit -m "roadmap rows"
```

## Day-to-day

```bash
tools/roadmap-seed.py --dry-run     # what would insert / (with --sync) reconcile
tools/roadmap-seed.py               # insert new rows (existing skipped)
tools/roadmap-seed.py --sync        # also reconcile the git-owned half of existing rows
```

**The split** (unchanged): git owns `title/parent/track/refs/body` (the files);
the table owns `status/target/occurred_at/verified*` (moved by
`tools/roadmap-update.py` and `tools/roadmap-verify.py`). `task_type` is authored
in the frontmatter now but is not yet a table column — it seeds nothing until
`roadmap.table.yml` gains the column and it is applied.

Read the board with `tools/roadmap-status.py` (never a file — the table is the
truth for status).
