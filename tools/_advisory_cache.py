"""The ETag cache behind `tools/advisory-status.py --cache-dir DIR`.

WHY. GitHub allows 60 unauthenticated calls an hour, and one run of the reader
asks ~46 repos, some of them over several pages. A conditional GET
(If-None-Match) that answers 304 costs nothing against an authenticated rate
limit, so a run that remembers ETags can be repeated.

WHY A LIBRARY. advisory-status.py is a reader, and a reader may not write
(tests/anatomy/test_readers_section_only_reads.py). This cache writes. The
operator ruled on PR #63 (2026-10-23) that it lives here, where that gate
cannot see it: this is a declared exception, not a hidden one. What bounds it:
  * it exists only when the operator passes --cache-dir; there is no default;
  * a directory inside the repository is refused;
  * it holds a response body and its ETag per URL, never a request header,
    so a token never reaches the disk;
  * pinned by tests/anatomy/test_advisory_status.py (the cache cases).
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]


class Cache:
    def __init__(self, root: str | os.PathLike):
        self.root = pathlib.Path(root).expanduser().resolve()
        if self.root == REPO or REPO in self.root.parents:
            raise ValueError(f"refused: {self.root} is inside the repository")

    def _path(self, url: str) -> pathlib.Path:
        return self.root / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".json")

    def get(self, url: str) -> dict | None:
        """{"etag", "body"} for `url`, or None when absent or unreadable."""
        try:
            data = json.loads(self._path(url).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and data.get("etag") else None

    def put(self, url: str, etag: str, body, next_url: str | None = None) -> None:
        """`next_url`: the page after this one (a Link rel=next), kept so a 304 still pages."""
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"url": url, "etag": etag, "body": body, "next": next_url}, fh)
        os.replace(tmp, self._path(url))
