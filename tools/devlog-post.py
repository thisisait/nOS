#!/usr/bin/env python3
"""devlog-post — publish a devlog entry to an ON-SITE namespace via WP REST.

The audited write path for namespaces whose source of truth is the live
WordPress DB (site, tenant/<x>, machine/<x>, user/<x>). Authenticates as the
nos-devlog-bot Application Password from ~/.nos/secrets.yml and emits a
devlog_entry_created/updated Bone event (actor_id=agent:devlog) per write —
never write to WP with raw curl or the admin account (docs/devlog/README.md
§ Audit doctrine).

REFUSES --namespace nos-core (exit 2): nos-core is repo-SoT — author a file
under docs/devlog/nos-core/<YYYY>/ instead; a REST-only nos-core post would be
deleted as an orphan by the next playbook sync.

Usage:
  tools/devlog-post.py --namespace site --title "..." --body-file entry.md
                       [--tags a,b] [--status publish|draft] [--summary "..."]
                       [--slug custom-slug]

Body file is markdown; rendered to HTML when python-markdown is installed,
posted as preformatted text otherwise. Prints the created/updated post JSON
{id, link, slug} on stdout.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
import uuid

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[1] / "files" / "anatomy" / "scripts")
)
import yaml  # noqa: E402
from devlog_lib import WPClient, WPError, emit_bone_event  # noqa: E402

SECRETS = pathlib.Path.home() / ".nos" / "secrets.yml"
NAMESPACE_RE = re.compile(r"^(site|tenant/[a-z0-9-]+|machine/[a-z0-9-]+|user/[a-z0-9-]+)$")


def _render(body_md: str) -> str:
    try:
        import markdown  # noqa: PLC0415

        return markdown.Markdown(extensions=["fenced_code", "tables"]).convert(body_md)
    except ImportError:
        return "<pre>" + body_md.replace("&", "&amp;").replace("<", "&lt;") + "</pre>"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--summary", default="")
    ap.add_argument("--tags", default="", help="comma-separated lowercase-dash tags")
    ap.add_argument("--status", default="publish", choices=["publish", "draft"])
    ap.add_argument("--slug", default="", help="default: <today>-<slugified-title>")
    args = ap.parse_args()

    if args.namespace == "nos-core" or not NAMESPACE_RE.match(args.namespace):
        print(
            "devlog-post: nos-core is repo-SoT — author a file under "
            "docs/devlog/nos-core/<YYYY>/ instead (the playbook sync would "
            "delete a REST-only nos-core post as an orphan). Valid on-site "
            "namespaces: site, tenant/<x>, machine/<x>, user/<x>.",
            file=sys.stderr,
        )
        return 2

    if not SECRETS.is_file():
        print("devlog-post: ~/.nos/secrets.yml not found (no live tenant)", file=sys.stderr)
        return 1
    secrets = yaml.safe_load(SECRETS.read_text()) or {}
    app_password = secrets.get("wordpress_devlog_app_password", "")
    if not app_password:
        print(
            "devlog-post: wordpress_devlog_app_password is empty — run the "
            "playbook (--tags wordpress) to mint it",
            file=sys.stderr,
        )
        return 1

    # Resolve the WP port from the repo config the same way the sync task does.
    repo = pathlib.Path(__file__).resolve().parents[1]
    cfg = yaml.safe_load((repo / "default.config.yml").read_text())
    port = cfg.get("wordpress_port", 8084)
    bot_user = cfg.get("wordpress_devlog_bot_user", "nos-devlog-bot")
    bone_port = cfg.get("bone_port", 8099)

    slug = args.slug or (
        time.strftime("%Y-%m-%d") + "-" + re.sub(r"[^a-z0-9]+", "-", args.title.lower()).strip("-")
    )
    body_md = pathlib.Path(args.body_file).read_text(encoding="utf-8")
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    wp = WPClient(f"http://127.0.0.1:{port}", bot_user, app_password)
    try:
        category = wp.ensure_namespace_category(args.namespace)
        existing = [
            p
            for p in wp.list_posts(author=wp.me()["id"], category=category)
            if p["slug"] == slug
        ]
        desired = {
            "title": args.title,
            "slug": slug,
            "content": _render(body_md),
            "excerpt": args.summary,
            "status": args.status,
            "categories": [category],
            "tags": wp.ensure_tags(tags) if tags else [],
        }
        if existing:
            post = wp.update_post(existing[0]["id"], desired)
            event_type = "devlog_entry_updated"
        else:
            post = wp.create_post(desired)
            event_type = "devlog_entry_created"
    except WPError as exc:
        print(f"devlog-post: {exc}", file=sys.stderr)
        return 1

    action_id = str(uuid.uuid4())
    emitted = emit_bone_event(
        f"http://127.0.0.1:{bone_port}",
        secrets.get("wing_events_hmac_secret", ""),
        event_type,
        action_id,
        action_id,
        {
            "namespace": args.namespace,
            "slug": slug,
            "wp_post_id": post["id"],
            "title": args.title,
        },
    )
    if not emitted:
        print("devlog-post: WARNING — Bone audit event not emitted", file=sys.stderr)
    print(json.dumps({"id": post["id"], "link": post.get("link", ""), "slug": slug}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
