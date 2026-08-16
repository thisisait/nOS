#!/usr/bin/env python3
"""Build a valid unified diff from a replacement an agent can state in words.

WHY THIS EXISTS, measured 2026-08-16 on the first model-authored loop cycle.
The agent read the weakness correctly, chose the conservative fix with a sound
reason — and its hand-written patch claimed seven lines in a hunk that had
five. Both judges returned `indeterminate`:

    diff does not apply at engine base: corrupt patch at <stdin>:9

Not `fail`. The engine refused to judge, which was right: a malformed patch is
not a bad change, it is an unjudgeable one, and calling it `fail` would have
said "this idea is wrong" when the idea was fine.

So the format burden moves off the model. It states FILE, OLD and NEW; this
builds the patch from the file on disk, where the line numbers and the context
are facts rather than recollections. Deterministic, and the diff applies or
this exits non-zero — it never emits a patch it has not proven.

    tools/loop-diff.py --file default.config.yml \\
        --old 'gitlab_version: "18.11.7-ce.0"  # …' \\
        --new 'gitlab_version: "18.11.9-ce.0"  # …'

Prints the unified diff on stdout. Refuses when OLD is absent, or matches more
than once — an ambiguous replacement is a proposal nobody can review.
"""

from __future__ import annotations

import argparse
import difflib
import pathlib
import subprocess
import sys
import tempfile


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, help="path relative to the repo root")
    ap.add_argument("--old", required=True, help="the line to replace, verbatim")
    ap.add_argument("--new", required=True, help="what it becomes")
    ap.add_argument("--repo", default=".", help="repo root (default: cwd)")
    args = ap.parse_args()

    repo = pathlib.Path(args.repo).resolve()
    target = repo / args.file
    if not target.is_file():
        print(f"no such file: {args.file}", file=sys.stderr)
        return 2

    original = target.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)

    # EXACTLY ONE match, or refuse. A replacement that could land in two places
    # is a proposal a reviewer cannot check, and the judge would be ruling on
    # whichever one the patcher happened to pick.
    hits = [i for i, line in enumerate(lines) if line.rstrip("\n") == args.old.rstrip("\n")]
    if not hits:
        print(f"OLD line not found verbatim in {args.file}", file=sys.stderr)
        return 3
    if len(hits) > 1:
        print(f"OLD line matches {len(hits)} times in {args.file}; be specific", file=sys.stderr)
        return 4

    patched = list(lines)
    patched[hits[0]] = args.new.rstrip("\n") + "\n"

    diff = "".join(
        difflib.unified_diff(
            lines, patched,
            fromfile=f"a/{args.file}", tofile=f"b/{args.file}",
            n=3,
        )
    )

    # PROVE IT BEFORE PRINTING IT. The whole point is that no unjudgeable patch
    # leaves this tool; `git apply --check` is the same gate the loop engine
    # applies at its base.
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as fh:
        fh.write(diff)
        probe = fh.name
    try:
        check = subprocess.run(
            ["git", "apply", "--check", probe],
            cwd=str(repo), capture_output=True, text=True,
        )
        if check.returncode != 0:
            print(f"refusing to emit a patch that does not apply: {check.stderr.strip()}",
                  file=sys.stderr)
            return 5
    finally:
        pathlib.Path(probe).unlink(missing_ok=True)

    sys.stdout.write(diff)
    return 0


if __name__ == "__main__":
    sys.exit(main())
