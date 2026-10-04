#!/usr/bin/env python3
"""Record what every running container runs — the converge's baseline.

Called from main.yml post_tasks (after handlers). Writes image ref, image ID
and repo digests per container, plus the source git commit for images built
locally (`--src REPO=DIR`). `tools/digest-status.py` judges drift; this only
records. Prints `changed`/`unchanged`; exit 1 when docker cannot be read.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

_spec = importlib.util.spec_from_file_location(
    "_digest_status", pathlib.Path(__file__).with_name("digest-status.py"))
_reader = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_reader)


def repo_of(ref: str) -> str:
    ref = ref.split("@", 1)[0]
    head, sep, tail = ref.rpartition(":")
    return head if sep and "/" not in tail else ref


def parse_srcs(pairs: list[str]) -> dict[str, str]:
    return dict(p.split("=", 1) for p in pairs if "=" in p and p.split("=", 1)[1])


def _git(d: str, *args: str) -> str | None:
    try:
        p = subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def source(d: str) -> dict:
    commit = _git(d, "rev-parse", "HEAD")
    dirty = _git(d, "status", "--porcelain", "--", ".")
    # dirty=None: not a git tree, so the commit cannot name what was built
    return {"dir": d, "commit": commit, "dirty": None if dirty is None else bool(dirty)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--src", action="append", default=[], metavar="REPO=DIR")
    args = ap.parse_args()
    live = _reader.snapshot()
    if live is None:
        print("docker unreachable — nothing recorded", file=sys.stderr)
        return 1
    srcs = parse_srcs(args.src)
    for row in live.values():
        d = srcs.get(repo_of(row["image"]))
        row["source"] = source(d) if d else None
    out = pathlib.Path(args.out).expanduser()
    try:
        before = json.loads(out.read_text(encoding="utf-8")).get("containers")
    except (OSError, ValueError, AttributeError):
        before = None
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps({"recorded_at": datetime.now(timezone.utc).isoformat(),
                               "containers": live}, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(out)
    built = sum(1 for r in live.values() if r["source"])
    print(f"{'unchanged' if before == live else 'changed'}: {len(live)} containers "
          f"({built} built locally) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
