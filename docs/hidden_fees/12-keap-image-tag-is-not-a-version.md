# 12 — `nos/keap:<version>` means "whatever the last build produced"

## The fee

`compose.yml.j2:30` is `image: nos/keap:{{ keap_version }}` with `build:` running
on every converge. The tag is not immutable: `nos/keap:1.29.0` means whatever the
last `up -d --build` produced from `~/keap/src`, not the v1.29.0 tree.

Two halves of one checkout reach the container by two different mechanisms —
application code baked at **image build time**, `knowledge/` bind-mounted and read
**live** — and nothing asserts they are the same commit. Within one converge they
are, because the `git` task runs before both. Between converges they can diverge,
and nothing would say so: there is no version handshake before `ingest.mjs` runs.

## When the bill comes due

- **Rollback.** Setting `keap_version` back to an earlier release does not get
  that release's image unless it is also rebuilt from that ref. The version
  number cannot be used to roll back, which is the one thing a version number is
  for.
- **A hand-pulled checkout.** `git pull` in `~/keap/src` changes what the running
  container ingests, immediately, with no rebuild and no signal.

## How it was found

Written up in full by the KEAP side on 2026-07-25
(`docs/specs/deploy-knowledge-mount-split.md`) as an actionable six-item list, and
re-scored on 2026-07-26. The two items that had actually fired were fixed — the
mount now covers all of `knowledge/`, and the `git` task no longer reclassifies an
unfetchable ref as `ok`, so a bad pin fails the converge instead of silently
building the previous checkout. These two never fired, so they were never fixed.

## What closes it

Either of these, independently:

- **Tag with the resolved commit** (`nos/keap:1.29.0-<sha8>`), or stop rebuilding
  an already-present tag. Makes `keap_version` mean something.
  **PAID 2026-08-18.** `tasks/main.yml` runs `git rev-parse --short=8 HEAD` in
  the checkout and sets `keap_image_tag`; the compose fragment renders
  `nos/keap:{{ keap_version }}-{{ sha }}`. A different tree is now a different
  tag, so the image either already exists and IS that tree, or is built.

  Read from the CHECKOUT, not from `_keap_clone.after`: the registered result is
  undefined on every pass that did not re-clone (`--tags keap` with the source
  present, check mode, a skipped `when`), and a tag that depended on whether a
  clone happened would be worse than one that depended on a version. There is
  deliberately **no `| default(keap_version)`** in the template — that fallback
  reads as caution and restores the whole defect on exactly the `--tags` passes
  where someone is iterating and not looking. A missing fact is a loud render
  failure. Gate: `tests/anatomy/test_the_keap_tag_names_a_tree.py`.

  **Cost accepted:** one image per commit rather than one per version, so the
  local image store grows with iteration. `nos --remove=deep` prunes it; that is
  cheaper than a version number that cannot roll back.

- **A version handshake before the ingest.** KEAP has offered a
  `knowledge/version-check.mjs` + generated `release.json`, run via `docker exec`
  before `ingest.mjs` and refusing on skew. It costs one more generated file to
  keep in step at every release. **Still unclaimed** — and it is the half that
  catches a LIVE skew (a hand-pulled checkout mid-run) rather than preventing a
  stale tag, so the two are complements and this entry stays open until it lands.
