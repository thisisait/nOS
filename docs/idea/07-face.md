# 07 — face: the desktop and its tables

**Status: active. Four render styles ship; the settings surface is the open half.**
**Detail:** [`nos-face.md`](../archive/nos-face.md) ·
[`roadmap-table.md`](../archive/roadmap-table.md)

## What exists

A real window manager — snap/tiling, dock, live taskbar thumbnails, Ctrl+Space
palette — with native apps over Bone's VFS (Files, Tables, Explore) and every
other service as an iframe window rather than a new tab.

**DataTables now declare how they want to be read**: `grid`, `blog`, `timeline`,
`tiles`, persisted in the card frontmatter beside the `graph` block.

One design decision worth keeping: **the body column is never auto-picked.** A
`blog` with no named body degrades to `grid` and *says so* — because a style that
silently renders an untitled, bodyless list looks like it is working, which is
worse than an obvious fallback.

## `/explore`

Core mode clusters by type with θ frozen by hash, so a node keeps its position
between sessions — spatial memory was the point of the view, and rehashing on
every load destroyed it. LOD opens ~2.5× earlier; labels on hover.

The reported *"skills appear twice, red and green"* was **disproven at three
levels** — object identity, graph payload ids, and the placement branches, which
are mutually exclusive. It was two cluster envelopes over one set of nodes. A
finding that is not a bug is still a result.

## The open half — the operator's asks, 2026-08-02

1. **Style is chosen at table creation**, not patched afterwards.
2. **A dropdown beside `+ Add row`** to switch render style, so there is always a
   way back to the plain grid.
3. **Per-style settings** — for `blog`: which columns show, and the ellipsis
   length.
4. **A view action beside edit** — a modal with the full content, the title
   alongside, and a copy-to-clipboard icon.
5. **Tree rendering** for tables that nest.

## The roadmap table, and why it is not a fixture

A live KEAP table (38 rows, 14 top-level, 24 nested) holding the forward view
with citations. **One table, self-nesting via a `parent` slug** — an epic and a
step are the same shape, and depth is not fixed at two.

It is **not** in `state/keap-tables/` because no L1 concept accepts `kind: date`
(see [06](06-genome.md)). Until `time.occurred_at` exists on both sides, the
table is live and useful but **not reproducible from git** — a fresh blank would
not recreate it. `tools/roadmap-seed.py` is the interim reproducible path.

## Known

The sidebar's hardcoded three-slug fallback is **dead code**: KEAP's list-all
endpoint now accepts the agent bearer (verified — 200 with it, 401 without), so
the live list is used. The `TODO` above it is stale and should go.
