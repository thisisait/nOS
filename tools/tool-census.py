#!/usr/bin/env python3
"""Every tools/ entry point by body word and by caller (row cli-limbs-inventory, step 1 of cli-limbs-tidy).

Body word: the tools/README.md section that lists it (reader | judge | limb | library); the index
gate (test_the_tools_index_is_complete) keeps that list complete. Callers come from tracked files that
name it: its file name (tools/x.py, "tools" / "x.py", $SCRIPT_DIR/x.sh) or, for a library, its
module (`import x`). The CLASS of a caller is where the naming file lives:

  pulse     a plugin under files/anatomy/plugins names it (a Pulse job or wiring block)
  converge  a role, task, playbook or template names it
  ci        .github/ or tools/ci-local.sh names it
  tool      another tool names it
  agent     a skill (.claude/, files/anatomy/skills) names it
  organ     other organ code (Wing, face, Bone, thalamus, …) names it
  test      a test names it
  operator  its name says a human runs it by name (README convention: nos-*, run-*)
  docs      CLAUDE.md, README.md or docs/ (not archive/devlog) names it
  nothing   none: a retire-or-move candidate (cli-limbs-tidy step 3)

    tools/tool-census.py            the table
    tools/tool-census.py --unused   only those nothing runs (docs or tests at most)
    tools/tool-census.py --json
A `library*` is listed under Libraries but executable: the README's word, flagged, never re-filed.
A reader: reads the checkout only, exit 0.
"""
from __future__ import annotations

import collections
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORDS = {"Readers": "reader", "Judges": "judge", "Limbs": "limb", "Libraries": "library"}
CODE_CALLERS = ("pulse", "converge", "ci", "tool", "agent", "organ", "operator")


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True).stdout


def entry_points() -> list[str]:
    """What the index gate counts: tracked files directly in tools/, .py/.sh or `nos`."""
    return sorted(Path(p).name for p in _git("ls-files", "tools").split()
                  if Path(p).parent.name == "tools" and (Path(p).suffix in {".py", ".sh"} or Path(p).name == "nos"))


def words() -> dict[str, str]:
    word, out = None, {}
    for line in (REPO / "tools/README.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^## (\w+)", line)
        if m:
            word = WORDS.get(m.group(1))
        m = re.match(r"^- `([^`]+)`", line)
        if m and word:
            out.setdefault(m.group(1), word)
    return out


def caller_class(ref: str) -> str | None:
    if ref.startswith("files/anatomy/plugins/"):
        return "pulse"
    if ref.startswith((".github/",)) or ref == "tools/ci-local.sh":
        return "ci"
    if ref.startswith(("roles/", "tasks/", "handlers/", "templates/")) or (
            "/" not in ref and ref.endswith((".yml", ".yaml"))):
        return "converge"
    if ref.startswith("tools/"):
        return "tool"
    if ref.startswith((".claude/", "files/anatomy/skills/")):
        return "agent"
    if ref.startswith("tests/"):
        return "test"
    if ref in ("CLAUDE.md", "README.md") or (ref.startswith("docs/")
                                              and not ref.startswith(("docs/archive/", "docs/devlog/"))):
        return "docs"
    if ref.startswith("files/"):
        return "organ"
    return None


def census() -> list[dict]:
    names = entry_points()
    known = set(names)
    refs: dict[str, set[str]] = collections.defaultdict(set)
    # By file name (tools/x.py, REPO / "tools" / "x.py", "$SCRIPT_DIR/x.sh"), or by module for a
    # library (`import x` / `from x import`); the bare word `nos` only as tools/nos.
    ref = re.compile(r"(?<![\w.-])([A-Za-z0-9_][A-Za-z0-9_.-]*\.(?:py|sh))(?![\w.-])|tools/(nos)\b")
    imp = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_]\w*)", re.M)
    for src in _git("ls-files").split():   # every tracked text file, one read each
        cls = caller_class(src)
        if not cls:
            continue
        try:
            text = (REPO / src).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found = {a or b for a, b in ref.findall(text)} | {f"{m}.py" for m in imp.findall(text)}
        for name in found & known:
            if src not in (f"tools/{name}", "tools/README.md"):
                refs[name].add(cls)
    w = words()
    rows = []
    for n in names:
        found = refs.get(n, set()) | ({"operator"} if n.startswith(("nos-", "run-")) or n == "nos" else set())
        callers = sorted(found, key=lambda c: (CODE_CALLERS + ("test", "docs")).index(c))
        word = w.get(n, "UNLISTED")
        # The README files it under Libraries, but it runs on its own (exec bit): say so, do not re-file it.
        misfiled = word == "library" and (REPO / "tools" / n).stat().st_mode & 0o111 != 0
        rows.append({"tool": n, "word": word, "callers": callers or ["nothing"],
                     "called_by_code": any(c in CODE_CALLERS for c in callers), "misfiled": misfiled})
    return rows


def main() -> int:
    rows = census()
    unused = [r for r in rows if not r["called_by_code"]]
    counts = {"tools": len(rows), "by_word": dict(collections.Counter(r["word"] for r in rows)),
              "no_code_caller": len(unused), "nothing": sum(r["callers"] == ["nothing"] for r in rows),
              "misfiled_library": sum(r["misfiled"] for r in rows)}
    if "--json" in sys.argv:
        json.dump({"rows": rows, "counts": counts}, sys.stdout, indent=2)
        return 0
    for r in (unused if "--unused" in sys.argv else rows):
        print(f"{r['tool']:34} {r['word'] + ('*' if r['misfiled'] else ''):<9} {', '.join(r['callers'])}")
    print(f"\n{counts['tools']} tools · " + " · ".join(f"{k} {v}" for k, v in sorted(counts["by_word"].items()))
          + f" · {counts['no_code_caller']} nothing runs ({counts['nothing']} with none at all)"
          + (f" · {counts['misfiled_library']} library* runs on its own (README files it under Libraries)"
             if counts["misfiled_library"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
