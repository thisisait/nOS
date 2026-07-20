#!/usr/bin/env python3
"""devlog-compile — validate nos-core devlog entries, emit the committed bundle.

Reads docs/devlog/nos-core/**/*.md (YAML frontmatter + markdown body),
validates the schema (doctrine: docs/devlog/README.md), and rewrites
state/devlog-bundle.jsonl — the machine source of truth the playbook syncs
into WordPress (files/anatomy/scripts/devlog-sync.py).

The bundle is BYTE-DETERMINISTIC: entries sorted by id, json sort_keys, no
timestamps, and the markdown→HTML renderer version is hard-pinned below (a
different python-markdown can emit different HTML, which would make the
freshness gate flap — lockfile-sync precedent). CI installs the same pin
(.github/workflows/ci.yml pytest job); the gate is
tests/anatomy/test_devlog_bundle.py.

Usage:
  tools/devlog-compile.py            # validate + rewrite state/devlog-bundle.jsonl
  tools/devlog-compile.py --check    # validate + exit 1 if the committed bundle is stale
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
ENTRIES_DIR = REPO / "docs" / "devlog" / "nos-core"
MEDIA_DIR = ENTRIES_DIR / "media"
BUNDLE_PATH = REPO / "state" / "devlog-bundle.jsonl"

# Repo-hosted screenshots. An entry references them repo-relative from its year
# directory — ![alt](../media/<name>.png) — which is what makes the image render
# both on GitHub and in the compiled bundle. The FILENAME is the stable key: the
# operator overwrites an image's bytes, keeps the name, re-runs the playbook, and
# the live post shows the new picture (devlog-sync.py does the WP side).
MEDIA_RE = re.compile(r"!\[([^\]]*)\]\(\.\./media/([^)\s]+)\)")
CODE_FENCE_RE = re.compile(r"^```.*?^```", re.S | re.M)
CODE_SPAN_RE = re.compile(r"`[^`\n]*`")
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}

# Single source of the renderer pin. Bump together with the ci.yml pytest
# pip-install line and re-run this tool (the bundle bytes may change).
MARKDOWN_PIN = "3.10.2"

REQUIRED = ("id", "title", "date", "namespace", "summary")
ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
STATUSES = ("published", "draft")


def _markdown_renderer():
    import markdown  # noqa: PLC0415 — deliberate late import for --help speed

    if markdown.__version__ != MARKDOWN_PIN:
        sys.exit(
            f"devlog-compile: python-markdown {markdown.__version__} installed, "
            f"pin is {MARKDOWN_PIN} — bundle bytes would drift. "
            f"pip install 'markdown=={MARKDOWN_PIN}'"
        )
    return markdown.Markdown(extensions=["fenced_code", "tables"])


def _split_frontmatter(path: pathlib.Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: missing frontmatter")
    try:
        _, fm, body = text.split("---\n", 2)
    except ValueError:
        raise ValueError(f"{path}: unterminated frontmatter") from None
    meta = yaml.safe_load(fm) or {}
    if not isinstance(meta, dict):
        raise ValueError(f"{path}: frontmatter is not a mapping")
    return meta, body.strip() + "\n"


def _norm_date(value) -> str:
    # PyYAML parses unquoted ISO dates into datetime.date.
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _collect_media(body: str, path: pathlib.Path, media_dir: pathlib.Path) -> tuple[list[dict], list[str]]:
    """Resolve ../media/<name> references → [{filename, sha256, alt}] + errors.

    The sha256 is what makes "same filename, new bytes" detectable downstream, so
    a replaced screenshot re-uploads without the entry's markdown changing at all.
    """
    # Scan PROSE only. A post is allowed to document the media syntax itself —
    # writing ![](../media/x.png) inside backticks must not be read as a real
    # reference (it isn't rendered as an image either), so code spans and fenced
    # blocks are blanked before matching.
    prose = CODE_FENCE_RE.sub("", body)
    prose = CODE_SPAN_RE.sub("", prose)
    media, errors, seen = [], [], set()
    for alt, name in MEDIA_RE.findall(prose):
        if name in seen:
            continue
        seen.add(name)
        target = media_dir / name
        if pathlib.Path(name).suffix.lower() not in MEDIA_EXT:
            errors.append(f"{path}: media '{name}' has an unsupported extension")
            continue
        if "/" in name or "\\" in name:
            errors.append(f"{path}: media '{name}' must sit flat in {media_dir.name}/")
            continue
        if not target.is_file():
            # relative_to() raises for a tree outside the repo (tests, or a
            # compile run from elsewhere) — the path is cosmetic, never let it
            # replace the real diagnosis.
            try:
                shown = target.relative_to(REPO)
            except ValueError:
                shown = target
            errors.append(f"{path}: media '{name}' not found at {shown}")
            continue
        media.append(
            {
                "filename": name,
                "alt": alt.strip(),
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )
    return sorted(media, key=lambda m: m["filename"]), errors


def load_entries(entries_dir: pathlib.Path = ENTRIES_DIR) -> list[dict]:
    """Validate and load every nos-core entry. Raises ValueError on violation."""
    errors: list[str] = []
    entries: list[dict] = []
    seen: dict[str, pathlib.Path] = {}
    for path in sorted(entries_dir.glob("*/*.md")):
        try:
            meta, body = _split_frontmatter(path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        for field in REQUIRED:
            if not meta.get(field):
                errors.append(f"{path}: missing required field '{field}'")
        eid = str(meta.get("id", ""))
        if eid != path.stem:
            errors.append(f"{path}: id '{eid}' != filename stem '{path.stem}'")
        if eid and not ID_RE.match(eid):
            errors.append(f"{path}: id must be <YYYY-MM-DD>-<slug> lowercase-dash")
        if eid in seen:
            errors.append(f"{path}: duplicate id (also {seen.get(eid)})")
        seen[eid] = path
        if meta.get("namespace") != "nos-core":
            errors.append(f"{path}: committed entries must be namespace nos-core")
        date = _norm_date(meta.get("date", ""))
        if not DATE_RE.match(date):
            errors.append(f"{path}: date '{date}' is not ISO YYYY-MM-DD")
        elif path.parent.name != date[:4]:
            errors.append(f"{path}: must live under the {date[:4]}/ year directory")
        status = meta.get("status", "published")
        if status not in STATUSES:
            errors.append(f"{path}: status '{status}' not in {STATUSES}")
        tags = meta.get("tags") or []
        if not isinstance(tags, list) or any(
            not isinstance(t, str) or not TAG_RE.match(t) for t in tags
        ):
            errors.append(f"{path}: tags must be a list of lowercase-dash strings")
        media, media_errors = _collect_media(body, path, entries_dir / "media")
        errors.extend(media_errors)
        entry = {
            "id": eid,
            "slug": eid,
            "namespace": "nos-core",
            "title": str(meta.get("title", "")),
            "date": date,
            "updated": _norm_date(meta["updated"]) if meta.get("updated") else date,
            "status": status,
            "summary": str(meta.get("summary", "")).strip(),
            "tags": tags,
            "release": str(meta["release"]) if meta.get("release") else None,
            "body_md": body,
        }
        # Only present when the entry actually carries images — an unconditional
        # key would rewrite every existing entry's bytes (and the freshness gate
        # compares bytes).
        if media:
            entry["media"] = media
        entries.append(entry)
    if errors:
        raise ValueError("devlog validation failed:\n  " + "\n  ".join(errors))
    return entries


def compile_bundle(entries_dir: pathlib.Path = ENTRIES_DIR) -> str:
    """Return the bundle text (published entries only, byte-deterministic)."""
    md = _markdown_renderer()
    lines = []
    for entry in sorted(load_entries(entries_dir), key=lambda e: e["id"]):
        if entry["status"] == "draft":
            continue
        md.reset()
        entry["body_html"] = md.convert(entry["body_md"])
        hash_input = {k: entry[k] for k in ("title", "summary", "body_html", "tags", "status", "date")}
        # Media hashes join the content hash so that replacing a screenshot's
        # bytes (markdown untouched) still marks the post dirty — the sync
        # re-uploads the image, which mints a new URL that must land in the body.
        if entry.get("media"):
            hash_input["media"] = entry["media"]
        entry["content_hash"] = hashlib.sha256(
            json.dumps(hash_input, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        lines.append(json.dumps(entry, sort_keys=True, ensure_ascii=False))
    return "".join(line + "\n" for line in lines)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    bundle = compile_bundle()
    committed = BUNDLE_PATH.read_text(encoding="utf-8") if BUNDLE_PATH.exists() else None
    if check:
        if committed != bundle:
            print(
                f"STALE: {BUNDLE_PATH.relative_to(REPO)} does not match "
                f"docs/devlog/nos-core/ — run tools/devlog-compile.py and commit",
                file=sys.stderr,
            )
            return 1
        print(f"OK: bundle fresh ({bundle.count(chr(10))} entries)")
        return 0
    BUNDLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BUNDLE_PATH.write_text(bundle, encoding="utf-8")
    print(f"wrote {BUNDLE_PATH.relative_to(REPO)} ({bundle.count(chr(10))} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
