#!/usr/bin/env python3
"""One-shot: backfill the canonical A9 notification routing block.

Appends a uniform severity→channel `notification:` block to every service
plugin that lacks one. Idempotent — skips plugins that already declare a
top-level `notification:` key (including the 5 legacy event-key blocks, which
are normalized separately). Textual append (not yaml.dump) so the rich inline
comments in each plugin.yml survive untouched.

Run from repo root:  python3 tools/backfill-notifications.py [--dry-run]
"""
from __future__ import annotations

import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
PLUGINS_ROOT = REPO / "files" / "anatomy" / "plugins"

BLOCK = """
# ── Notification routing (A9 severity → channel) ─────────────────────────────
# Uniform wiring contract (2026-05-23): harvested by wing-base into
# notification-routing.json; Bone falls back to this when an emitter POSTs a
# notification with origin_plugin + severity but no explicit channels. The
# emitter decides which failure maps to which severity; this block only routes
# a severity to channels. Channels: wing-inbox | ntfy | mail. Tune per service.
notification:
  on_critical: [wing-inbox, ntfy]
  on_high:     [wing-inbox, ntfy]
  on_medium:   [wing-inbox]
  on_low:      []
  on_info:     []
"""


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    appended, skipped = [], []
    for d in sorted(PLUGINS_ROOT.iterdir()):
        manifest = d / "plugin.yml"
        if not manifest.is_file():
            continue
        m = yaml.safe_load(manifest.read_text()) or {}
        if "service" not in (m.get("type") or []):
            continue
        if m.get("notification"):
            skipped.append(d.name)
            continue
        if not dry:
            text = manifest.read_text()
            if not text.endswith("\n"):
                text += "\n"
            manifest.write_text(text + BLOCK)
        appended.append(d.name)
    print(f"appended ({len(appended)}): {', '.join(appended)}")
    print(f"skipped — already had notification ({len(skipped)}): "
          f"{', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
