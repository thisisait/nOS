#!/usr/bin/env python3
"""The first immune crawler: walks git history a slice per tick for instructions aimed at an assistant.

A crawler (ssot/doctrine/immune-system.md §3) holds a cursor, takes one bounded
step per Pulse tick, and dies when its lifespan is spent. This one reads the
ADDED lines of each commit after its cursor (`git show -p -U0`) and matches
them against the shape table below: prompt-injection phrasings and the
invisible characters a dormant trigger hides behind (Trojan Source). It
records WHERE a shape is (commit, path, line, shape id), never the text, so a
verdict cannot carry the payload or a secret onward.

Paths that quote shapes on purpose (tests, the fee ledger, this file) are
tolerated by state/immune/crawl-tolerance.yml. A model is never asked.

    tools/immune-crawl.py --slice 50                 # the next 50 commits
    tools/immune-crawl.py --slice 5 --lifespan 10    # retire after 10 commits walked

Exit: 0 clean · 10 findings in this slice · 11 git unreadable (no cursor written)
· 12 lifespan spent (the cursor is retired; later runs walk nothing).
State: ~/.nos/immune/crawl/git-history.json (cursor) and verdicts.jsonl, 0600.
Overrides: NOS_IMMUNE_CRAWL_REPO (default: this checkout), NOS_IMMUNE_CRAWL_DIR.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CELL = "immune-crawler:git-history"
TOLERANCE = REPO / "state" / "immune" / "crawl-tolerance.yml"
EXIT_CLEAN, EXIT_FOUND, EXIT_UNREADABLE, EXIT_SPENT = 0, 10, 11, 12

#: shape id -> pattern over one added line. Narrow on purpose: a shape that fires on prose is noise.
SHAPES = {
    "ignore-previous": re.compile(
        r"\b(ignore|disregard|forget)\s+(all\s+|any\s+|the\s+|your\s+)*(previous|prior|above|earlier)\s+"
        r"(instructions?|prompts?|messages?|rules|directions)", re.I),
    "system-prompt-override": re.compile(
        # `<system>` as a placeholder (nos.<stack>.<system>, tokens/<system>.token) is everywhere here:
        # only a closing tag, a line that opens with the tag, or a chat-template token counts.
        r"\b(new|updated|real|actual)\s+system\s+prompt\b|</\s*system\s*>|^\s*<\s*system\s*>"
        r"|<\|im_start\|>\s*system|\[/?INST\]", re.I),
    "jailbreak-mode": re.compile(r"\b(developer|jailbreak|DAN|god)\s+mode\s+(enabled|on|activated)\b", re.I),
    "assistant-directive": re.compile(
        r"\b(claude|assistant|chatgpt|copilot|gemini)\s*[,:]\s*(please\s+)?"
        r"(run|execute|delete|push|commit|send|curl|ignore|disable)\b", re.I),
    "exfil-instruction": re.compile(
        r"\b(send|post|upload|exfiltrate|forward)\s+(the\s+|all\s+|your\s+|any\s+)*"
        r"(secrets?|credentials|tokens?|api[\s_-]?keys?|passwords?|\.env)\s+to\b", re.I),
    # Bidi controls (Trojan Source) and line/paragraph separators. Zero-width joiners are left out:
    # emoji and the uid fixtures carry them on purpose (24 of 44 hits over 6 438 commits were those).
    "hidden-unicode": re.compile("[\u202a-\u202e\u2066-\u2069\u2028\u2029]"),
}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          errors="replace", timeout=120)


def _tolerated() -> list[str]:
    doc = yaml.safe_load(TOLERANCE.read_text(encoding="utf-8")) if TOLERANCE.is_file() else {}
    return [str(g) for g in (doc or {}).get("globs") or []]


def _write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def scan(diff: str, globs: list[str]) -> list[dict]:
    """Verdicts for the added lines of a `git show --format=%x00%H -p -U0` stream. No text kept."""
    out, commit, path, line = [], "", "", 0
    for raw in diff.splitlines():
        if raw.startswith("\x00"):
            commit, path = raw.strip("\x00").strip(), ""
        elif raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else ""
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line = int(m.group(1)) if m else 0
        elif raw.startswith("+") and path:
            if not any(fnmatch.fnmatch(path, g) for g in globs):
                for sid, rx in SHAPES.items():
                    if rx.search(raw[1:]):
                        out.append({"at": _now(), "cell": CELL, "commit": commit, "path": path,
                                    "line": line, "shape_id": sid})
            line += 1
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--slice", type=int, default=50, help="commits walked this tick (default 50)")
    ap.add_argument("--lifespan", type=int, default=20000, help="commits walked in all before the cell retires")
    a = ap.parse_args(argv)
    if a.slice < 1 or a.lifespan < 1:
        ap.error("--slice and --lifespan are positive")
    repo = Path(os.environ.get("NOS_IMMUNE_CRAWL_REPO") or REPO)
    home = Path(os.environ.get("NOS_IMMUNE_CRAWL_DIR") or Path.home() / ".nos" / "immune" / "crawl")
    cursor_file, verdicts_file = home / "git-history.json", home / "verdicts.jsonl"

    try:
        top = _git(repo, "rev-parse", "--verify", "HEAD")
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"immune-crawl: git unreadable at {repo}: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE
    if top.returncode != 0:
        print(f"immune-crawl: {repo} is not a readable git repository", file=sys.stderr)
        return EXIT_UNREADABLE

    cur = json.loads(cursor_file.read_text(encoding="utf-8")) if cursor_file.is_file() else {}
    if cur.get("retired_at"):
        print(f"immune-crawl: retired {cur['retired_at']} after {cur.get('steps', 0)} commits; walks nothing")
        return EXIT_SPENT
    steps = int(cur.get("steps", 0))
    home.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)
    if steps >= a.lifespan:
        cur.update(retired_at=_now(), lifespan=a.lifespan)
        _write(cursor_file, json.dumps(cur, indent=2) + "\n")
        print(f"immune-crawl: lifespan {a.lifespan} spent ({steps} commits walked); retired")
        return EXIT_SPENT

    last = cur.get("last_commit")
    # ponytail: a cursor git no longer knows (history rewritten) restarts at the root and re-walks; verdicts may repeat.
    if last and _git(repo, "cat-file", "-e", f"{last}^{{commit}}").returncode != 0:
        print(f"immune-crawl: cursor {last[:12]} is unknown to git; walking from the root again", file=sys.stderr)
        last = None
    revs = _git(repo, "rev-list", "--reverse", f"{last}..HEAD" if last else "HEAD")
    if revs.returncode != 0:
        print(f"immune-crawl: git rev-list failed: {revs.stderr.strip()[:200]}", file=sys.stderr)
        return EXIT_UNREADABLE
    todo = revs.stdout.split()[: min(a.slice, a.lifespan - steps)]
    found: list[dict] = []
    if todo:
        try:
            # a merge as a plain diff to its first parent: a combined diff (`++`, `@@@`) defeats the line-start shapes
            diff = _git(repo, "show", "--no-color", "--format=%x00%H", "-p", "-U0", "--diff-merges=first-parent",
                        "--no-ext-diff", "--no-textconv", *todo)
        except (OSError, subprocess.SubprocessError) as exc:  # a huge slice times out: say unreadable, never crash
            print(f"immune-crawl: git show unreadable: {exc}", file=sys.stderr)
            return EXIT_UNREADABLE
        if diff.returncode != 0:
            print(f"immune-crawl: git show failed: {diff.stderr.strip()[:200]}", file=sys.stderr)
            return EXIT_UNREADABLE
        found = scan(diff.stdout, _tolerated())
        if found:
            with verdicts_file.open("a", encoding="utf-8") as fh:
                fh.writelines(json.dumps(v) + "\n" for v in found)
            os.chmod(verdicts_file, 0o600)
        cur.update(last_commit=todo[-1], steps=steps + len(todo))
    cur.update(repo=str(repo), lifespan=a.lifespan, updated_at=_now())
    cur.setdefault("started_at", cur["updated_at"])
    _write(cursor_file, json.dumps(cur, indent=2) + "\n")
    print(f"immune-crawl: walked {len(todo)} commit(s), {cur.get('steps', 0)}/{a.lifespan} in all; "
          f"{len(found)} finding(s)" + (f" -> {verdicts_file}" if found else ""))
    for v in found:
        print(f"  {v['shape_id']:<22} {v['commit'][:12]} {v['path']}:{v['line']}")
    return EXIT_FOUND if found else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
