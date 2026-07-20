# Devlog screenshots — repo-hosted images in nos-core blog posts

> **SHIPPED 2026-07-20.** Implemented as designed, with the open decisions
> resolved as: flat `media/` folder (favours the stable-filename contract);
> no dedicated featured-image field (first inline image is enough today);
> orphan media GC included, under the same author+prefix guards the post
> collector uses. Media hashes fold into the entry content hash — without that
> a replaced image uploads but no post ever points at it. Verified by a live
> dry-run (created 2 / media_created 2) and pinned by
> `tests/anatomy/test_devlog_media.py`. First post using it:
> `2026-07-20-face-and-cortex-tour`.


**Status:** OPEN (requested 2026-07-19). Extends the devlog `nos-core` pipeline
(`docs/devlog/README.md`): repo is SoT → `state/devlog-bundle.jsonl` → playbook
syncs to WordPress (WP side disposable, last-run-wins). Today the sync handles
post text only — **no image/media**. This adds repo-hosted screenshots that
render inside posts, with a filename-stable replace-and-resync workflow.

## Operator intent (verbatim requirements)
- A **separate folder in the repo** for screenshots.
- Screenshots **appear in the blog posts** (the next nos-core post already ships
  with images).
- **Filename-stable replace:** overwrite an image's *content* in the repo while
  keeping its filename → re-run the playbook → the live post shows the new image.

## Design (mirrors the "repo SoT, WP disposable, last-run-wins" model)

1. **Repo media folder.** `docs/devlog/nos-core/media/` (flat, descriptive stable
   filenames — the filename IS the stable key, per the replace workflow). Posts
   reference them repo-relative in the markdown body:
   `![alt text](../media/<name>.png)` (or a `media:` frontmatter list for the
   featured/lead image).
2. **Compile** (`tools/devlog-compile.py`): for each nos-core entry, resolve the
   referenced media, attach `{filename, sha256, alt}` to the bundle entry (the
   hash is what makes "replace content, same name" detectable).
3. **Sync** (`tasks/devlog-sync.yml` → the WP writer): upload each image to the
   WP **media library** keyed by a deterministic slug derived from the repo
   filename (so re-upload targets the SAME media item / URL). On re-sync, compare
   the bundle sha256 to the last-synced hash; if changed, **re-upload in place**
   (replace the media bytes, keep the attachment ID + URL) so every post already
   referencing it shows the new content — no post edit needed. Rewrite the body's
   repo-relative image paths → the WP media URLs at render time.
4. **Replace workflow (the ask):** edit `docs/devlog/nos-core/media/<name>.png`
   (same filename, new bytes) → `ansible-playbook main.yml --tags devlog` (or a
   full run) → sync detects the hash delta → replaces the WP media → live posts
   update. Last-run-wins + WP-disposable stays intact (a full re-sync from a fresh
   repo re-uploads all media deterministically).

## Open decisions
- Featured image: dedicated `image:` frontmatter field vs. first inline image.
- Media folder layout: one flat `media/` vs. per-year `nos-core/<YYYY>/media/`
  (flat favours cross-post reuse + the stable-filename contract; per-year favours
  locality). Lean flat.
- GH Pages path: Pages publishes nos-core too — image URLs must resolve there
  (relative paths work if media ships in the Pages artifact).
- Orphan media GC: a WP media item whose repo file was deleted should be pruned
  on sync (same triple-guard discipline the posts use).

## Acceptance
- A nos-core post with `![](../media/foo.png)` renders the image on the live WP
  site after a playbook run.
- Overwriting `foo.png` (same name) + re-running the playbook updates the image on
  the live post with no manual WP step.
