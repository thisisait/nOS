#!/usr/bin/env python3
"""devlog-sync — reconcile state/devlog-bundle.jsonl into WordPress (nos-core).

Repo is the source of truth for the nos-core namespace; the WordPress side is
disposable presentation (docs/devlog/README.md). Last run wins — WP-side edits
to nos-core posts are overwritten, and posts absent from the bundle are
deleted under a TRIPLE GUARD: (a) post is in the nos-core category, (b) post
is authored by the devlog bot, (c) slug missing from the bundle. On-site
namespaces (site/tenant/machine/user) live in other categories under other
authors and are structurally untouchable here.

Invoked by tasks/devlog-sync.yml. Env contract:
  WP_BASE_URL       http://127.0.0.1:<wordpress_port>
  WP_BOT_USER       nos-devlog-bot
  WP_APP_PASSWORD   from ~/.nos/secrets.yml (wordpress_devlog_app_password)
  BUNDLE_PATH       state/devlog-bundle.jsonl
  MEDIA_DIR         docs/devlog/nos-core/media (optional — derived from BUNDLE_PATH)
  BONE_URL          http://127.0.0.1:<bone_port>   (optional — skip emit if empty)
  WING_EVENTS_HMAC_SECRET                          (optional — skip emit if empty)
  NOS_RUN_ID        playbook run id (actor_action_id lineage)
  DRY_RUN           "1" = print the plan, change nothing

Prints a JSON summary {created, updated, deleted, unchanged, bundle_entries,
dry_run} on stdout; exit 0 on success, 1 on any WP API failure. One
devlog_sync_run Bone event per invocation (actor_id=agent:devlog).
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from devlog_lib import (  # noqa: E402
    WPClient,
    WPError,
    content_with_hash,
    emit_bone_event,
    extract_hash,
    media_slug,
)

MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
}


def sync_media(wp: WPClient, entries: list[dict], media_dir: pathlib.Path,
               bot_id: int, dry_run: bool, summary: dict) -> dict[str, str]:
    """Reconcile repo screenshots into the WP media library → {filename: url}.

    Same contract as posts: repo is SoT, WP disposable. The attachment slug is
    derived from the repo filename (the operator's stable key) and the repo
    sha256 rides in the attachment description, so an unchanged image is a no-op
    and a replaced one (same name, new bytes) is delete + re-upload.
    """
    wanted: dict[str, dict] = {}
    for entry in entries:
        for item in entry.get("media", []):
            wanted[item["filename"]] = item

    existing = {}
    for item in wp.list_media(author=bot_id):
        slug = item.get("slug", "")
        if slug.startswith("devlog-"):
            existing[slug] = item

    urls: dict[str, str] = {}
    for filename, item in sorted(wanted.items()):
        slug = media_slug(filename)
        current = existing.pop(slug, None)
        if current is not None:
            stored = extract_hash(current.get("description", {}).get("raw", ""))
            if stored == item["sha256"]:
                summary["media_unchanged"] += 1
                urls[filename] = current["source_url"]
                continue
            # Bytes changed → the attachment must go; its replacement gets a new
            # URL, which this same run writes into every referencing post.
            summary["media_replaced"] += 1
            if not dry_run:
                wp.delete_media(current["id"])
        else:
            summary["media_created"] += 1

        path = media_dir / filename
        if dry_run:
            urls[filename] = f"DRY-RUN://{slug}"
            continue
        uploaded = wp.upload_media(
            filename,
            path.read_bytes(),
            MIME.get(path.suffix.lower(), "application/octet-stream"),
            sha256=item["sha256"],
        )
        urls[filename] = uploaded["source_url"]

    # Orphans: a devlog- attachment by the bot that no entry references any more.
    for slug, item in existing.items():
        summary["media_deleted"] += 1
        print(f"orphan: deleting media {slug} (wp id {item['id']})", file=sys.stderr)
        if not dry_run:
            wp.delete_media(item["id"])
    return urls


def rewrite_media_urls(body_html: str, urls: dict[str, str]) -> str:
    """Repo-relative image paths → live WP media URLs (render-time rewrite)."""
    for filename, url in urls.items():
        body_html = body_html.replace(f"../media/{filename}", url)
    return body_html


def load_bundle(path: pathlib.Path) -> list[dict]:
    entries = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                entries.append(json.loads(line))
    return entries


def main() -> int:
    env = os.environ
    dry_run = env.get("DRY_RUN", "") == "1"
    bundle_path = pathlib.Path(env["BUNDLE_PATH"])
    media_dir = pathlib.Path(
        env.get("MEDIA_DIR") or bundle_path.parents[1] / "docs/devlog/nos-core/media"
    )
    wp = WPClient(env["WP_BASE_URL"], env["WP_BOT_USER"], env["WP_APP_PASSWORD"])

    entries = load_bundle(bundle_path)
    summary = {
        "created": 0, "updated": 0, "deleted": 0, "unchanged": 0,
        "media_created": 0, "media_replaced": 0, "media_unchanged": 0, "media_deleted": 0,
        "bundle_entries": len(entries), "dry_run": dry_run,
    }
    try:
        bot = wp.me()
        category = wp.ensure_namespace_category("nos-core")
        existing = {p["slug"]: p for p in wp.list_posts(author=bot["id"], category=category)}

        # Media first: posts embed the resulting URLs, so an image must exist
        # before the body referencing it is written.
        media_urls = sync_media(wp, entries, media_dir, bot["id"], dry_run, summary)

        for entry in entries:
            desired = {
                "title": entry["title"],
                "slug": entry["slug"],
                "content": content_with_hash(
                    rewrite_media_urls(entry["body_html"], media_urls), entry["content_hash"]
                ),
                "excerpt": entry["summary"],
                "status": "publish" if entry["status"] == "published" else "draft",
                "categories": [category],
                "tags": wp.ensure_tags(entry["tags"]) if entry["tags"] else [],
                "date": f"{entry['date']}T12:00:00",
            }
            current = existing.pop(entry["slug"], None)
            if current is None:
                summary["created"] += 1
                if not dry_run:
                    wp.create_post(desired)
                continue
            stored_hash = extract_hash(current.get("content", {}).get("raw", ""))
            if stored_hash == entry["content_hash"]:
                summary["unchanged"] += 1
                continue
            summary["updated"] += 1
            if not dry_run:
                wp.update_post(current["id"], desired)

        # Orphans: whatever is LEFT in `existing` already passed guards (a)
        # category and (b) author via the list_posts filter; (c) is the pop
        # above — only slugs absent from the bundle remain.
        for slug, post in existing.items():
            summary["deleted"] += 1
            print(f"orphan: deleting nos-core/{slug} (wp id {post['id']})", file=sys.stderr)
            if not dry_run:
                wp.delete_post(post["id"])
    except WPError as exc:
        print(f"devlog-sync: {exc}", file=sys.stderr)
        print(json.dumps(summary))
        return 1

    run_id = env.get("NOS_RUN_ID", "") or str(uuid.uuid4())
    emitted = emit_bone_event(
        env.get("BONE_URL", ""),
        env.get("WING_EVENTS_HMAC_SECRET", ""),
        "devlog_sync_run",
        run_id,
        run_id,
        summary,
    )
    if not emitted:
        print("devlog-sync: Bone event not emitted (Bone down or secret unset)", file=sys.stderr)
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
