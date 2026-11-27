#!/usr/bin/env python3
"""The paths a /roadmap-loop commit may not touch, checked on the diff, not on the loop's word.

    tools/loop-branch-guard.py <base> <head>      e.g. origin/dev origin/loop/dev

Lists every commit in base..head that touches a held path (tests, gates, the ratchet, agent
settings, CI workflows, the push guards, operator files) and exits 1; exits 0 when none does.
The loop never writes tests or gates (roadmap-loop skill; a gate it trips is a GATE CONFLICT note),
and until 2026-11-26 only the skill text said so. /roadmap-integrate runs this before the batch and
drops a branch it names. Session commits are cherry-picked after the check and are not in the range.
"""
from __future__ import annotations

import fnmatch
import pathlib
import subprocess
import sys

import yaml

HELD = (
    "tests/*", "*.test.ts", "*.spec.ts", "files/anatomy/thalamus/*/tests/*",
    "state/judge-sets.yml", ".claude/*", ".github/workflows/*", "tools/git-hooks/*", "tools/nos-push",
    "config.yml", "credentials.yml",
)


#: Files tools/regenerate.py writes are committed with the branch (never hand-edited), so not held.
GENERATED = frozenset((yaml.safe_load((pathlib.Path(__file__).resolve().parents[1] / "state" / "generated.yml")
                       .read_text(encoding="utf-8")) or {}).get("files") or {})
#: A shrink-only list may lose lines (the debt shrinks); one that gains a line is held.
SHRINK_ONLY = "tests/anatomy/*_pending.txt"


def held(path: str, added: int = 1) -> bool:
    if path in GENERATED or (fnmatch.fnmatch(path, SHRINK_ONLY) and added == 0):
        return False
    return any(fnmatch.fnmatch(path, pat) for pat in HELD)


def hits(base: str, head: str) -> list[tuple[str, str, list[str]]]:
    log = subprocess.run(["git", "log", "--no-merges", "--format=%x00%h %s", "--numstat", f"{base}..{head}"],
                         capture_output=True, text=True, check=True).stdout
    out = []
    for chunk in log.split("\0")[1:]:
        head_line, *stats = [ln for ln in chunk.splitlines() if ln.strip()]
        sha, _, subject = head_line.partition(" ")
        files = [(st.split("\t")[2], int(st.split("\t")[0]) if st.split("\t")[0].isdigit() else 1) for st in stats]
        bad = [f for f, added in files if held(f, added)]
        if bad:
            out.append((sha, subject, bad))
    return out


def _self_test() -> None:
    for p in ("tests/anatomy/test_x.py", "files/anatomy/face/src/lib/a.test.ts", ".claude/skills/x/SKILL.md",
              ".github/workflows/ci.yml", "state/judge-sets.yml", "files/anatomy/thalamus/thalamus/tests/serve.rs"):
        assert held(p), p
    for p in ("tools/roadmap-status.py", "roles/pazny.traefik/tasks/main.yml", "docs/tests.md",
              "files/anatomy/face/src/lib/a.ts", "ssot/doctrine/face.md", "tests/fixtures/selfmodel-recall.json"):
        assert not held(p), p
    assert held("tests/anatomy/credential_doubles_pending.txt", 1)
    assert not held("tests/anatomy/credential_doubles_pending.txt", 0)


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        _self_test()
        print("self-test ok")
        sys.exit(0)
    if len(sys.argv) != 3:
        sys.exit(__doc__.strip().splitlines()[2].strip())
    found = hits(sys.argv[1], sys.argv[2])
    for sha, subject, bad in found:
        print(f"HELD {sha} {subject}: {', '.join(bad)}")
    print(f"loop-branch-guard: {len(found)} commit(s) touch held paths in {sys.argv[1]}..{sys.argv[2]}")
    sys.exit(1 if found else 0)
