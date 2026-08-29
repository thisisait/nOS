#!/usr/bin/env python3
"""Refuse a workflow script the runtime would reject — before it spends anything.

WHY THIS EXISTS. Two workflow scripts were launched on 2026-08-28 and both died
on a defect a reader could have seen. The research workflow referenced a
constant that was never defined and died mid-run, after its first two agents had
already been paid for. The build workflow died 32 seconds in, twice: first
`meta.description` was three strings joined with `+` (the runtime requires a pure
literal), then five `pipeline()` calls passed their stages where the items array
goes. Each failure cost a launch, a diagnosis and a resume.

None of that needed the runtime to discover. `node --check` passes all three —
they are valid JavaScript that violates the workflow contract, which is a
different thing.

WHAT IT CANNOT SEE, said plainly so a green run is not over-read.

  * An identifier that is never defined — the research workflow's actual bug.
    That needs a scope graph; this reads text.
  * A BACKTICK INSIDE A PROMPT, which ends the template it lives in. A rule
    spelling a branch name in backticks made the runtime refuse a script at line
    115 while `node --check` stayed happy, because the ticks were PAIRED and the
    template merely ended early. Two heuristics were tried and both were worse
    than nothing: counting ticks per file cannot see it, and flagging ticks in
    indented prose reds 7 of 8 legitimate scripts, because a code template with
    `${...}` in it looks identical by that measure. Telling them apart needs a
    scanner that tracks template state across lines and through nested `${}` —
    real work, not a regex. Until then the failure is loud and immediate at
    launch, which is the cheapest place it can happen.
  * Anything that only exists at runtime.

Usage:
    tools/workflow-lint.py <script.js> [<script.js> ...]
    tools/workflow-lint.py --all      # every committed workflow script

Exit 0 when every script passes, 1 when any fails. This one IS a gate — it
refuses, unlike the readers in this directory, because its whole job is to
refuse before a launch.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

#: Where committed workflow scripts live. A script outside these is linted only
#: when named explicitly.
GLOBS = ("docs/plans/**/*workflow*.js", ".claude/workflows/*.js")

#: The runtime rejects these outright — they would break resume, which replays
#: a prefix of agent() calls and needs the script to be deterministic.
NONDETERMINISM = (
    (r"\bDate\.now\s*\(", "Date.now() — forbidden; pass a timestamp in via args"),
    (r"\bMath\.random\s*\(", "Math.random() — forbidden; vary the prompt by index"),
    (r"\bnew\s+Date\s*\(\s*\)", "argless new Date() — forbidden; pass the date in via args"),
)

#: `pipeline(items, stage1, ...)` and `parallel([thunks])` both take a
#: collection FIRST. Passing a stage there is the 2026-08-28 build-workflow bug:
#: five call sites read as "run these two phases" and the runtime read
#: "run these items". The repair for that bug then introduced the next one
#: (FALSY_ITEMS below), which is why both live here.
COLLECTION_FIRST = ("pipeline", "parallel")


def node_check(path: pathlib.Path) -> list[str]:
    """Valid JavaScript at all? Necessary, nowhere near sufficient."""
    try:
        out = subprocess.run(["node", "--check", str(path)],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        # An absent node is UNKNOWN, not a pass — say so rather than stay quiet.
        return [f"could not run `node --check` ({exc}); syntax is UNVERIFIED"]
    return [] if out.returncode == 0 else [f"node --check failed: {out.stderr.strip()[:300]}"]


def meta_block(src: str) -> tuple[str, list[str]]:
    """The `export const meta = {...}` text, brace-matched."""
    m = re.search(r"export\s+const\s+meta\s*=\s*\{", src)
    if not m:
        return "", ["no `export const meta = {...}` — the runtime requires it"]
    depth, i = 0, m.end() - 1
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():i + 1], []
        i += 1
    return "", ["`meta` block is not brace-balanced"]


def strip_strings(text: str) -> str:
    """Blank out string/template contents so punctuation inside them is not read
    as code. Crude on purpose: it only has to survive a meta block."""
    return re.sub(r"'[^'\n]*'|\"[^\"\n]*\"|`[^`]*`", "''", text)


def code_only(src: str) -> str:
    """Source with strings and comments blanked, newlines preserved.

    Without this the linter reads its own advice: a comment explaining the
    `pipeline([null])` bug was reported AS the bug. A detector that cannot tell
    code from prose about code is the failure it exists to catch.
    """
    out, i, n = [], 0, len(src)
    while i < n:
        ch = src[i]
        if ch in "'\"`":
            q, j = ch, i + 1
            while j < n and src[j] != q:
                j += 2 if src[j] == "\\" else 1
            out.append("".join(c if c == "\n" else " " for c in src[i:j + 1]))
            i = j + 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i)); i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join(c if c == "\n" else " " for c in src[i:j])); i = j
        else:
            out.append(ch); i += 1
    return "".join(out)


def check_meta(src: str) -> list[str]:
    block, errs = meta_block(src)
    if errs:
        return errs
    bare = strip_strings(block)
    if "+" in bare:
        errs.append("meta contains a `+` — it must be a PURE LITERAL; a "
                    "concatenated description is a BinaryExpression and the "
                    "runtime refuses it (measured 2026-08-28)")
    if re.search(r"\$\{", block):
        errs.append("meta interpolates a template expression — pure literals only")
    if re.search(r"\.\.\.", bare):
        errs.append("meta uses a spread — pure literals only")
    if re.search(r"\w\s*\(", bare):
        errs.append("meta calls a function — pure literals only")
    for field in ("name", "description"):
        if not re.search(rf"\b{field}\s*:", block):
            errs.append(f"meta.{field} is required")
    return errs


#: MEASURED 2026-08-28 with a two-agent probe: `pipeline([null], stage)` invoked
#: the stage ZERO times; `pipeline([1], stage)` invoked it once. A null item is
#: already-dropped, so every stage is skipped — silently, with no error and no
#: log. That is how two whole phases of the build workflow (delete agent memory;
#: the lock) never ran while the run continued as if they had.
FALSY_ITEMS = ("null", "undefined", "0", "false", "''", '""')


def check_collection_first(src: str) -> list[str]:
    """`pipeline(` / `parallel(` must be handed a collection, not a stage — and
    the collection must contain something the runtime will actually process."""
    errs = []
    for m in re.finditer(r"\bpipeline\s*\(\s*\[([^\]]*)\]", src):
        items = m.group(1).strip()
        line = src[:m.start()].count("\n") + 1
        if not items:
            errs.append(f"line {line}: pipeline([]) has no items — every stage is "
                        f"skipped and the run continues as if they had passed")
        elif all(i.strip() in FALSY_ITEMS for i in items.split(",") if i.strip()):
            errs.append(
                f"line {line}: pipeline([{items}]) — a falsy item is treated as "
                f"ALREADY DROPPED, so its stages never run and nothing says so "
                f"(measured 2026-08-28). Use a truthy sentinel, e.g. [1]."
            )
    for fn in COLLECTION_FIRST:
        for m in re.finditer(rf"\b{fn}\s*\(", src):
            rest = src[m.end():].lstrip()
            # A leading `(` is only a stage when it is an arrow's PARAMETER list —
            # `((x || []).map(...))` is a parenthesised expression and perfectly
            # legal here. Tell them apart by what follows the matching paren.
            if rest.startswith("("):
                depth, k = 0, 0
                while k < len(rest):
                    depth += (rest[k] == "(") - (rest[k] == ")")
                    if depth == 0:
                        break
                    k += 1
                if not rest[k + 1:].lstrip().startswith("=>"):
                    continue
            if rest.startswith(("(", "async", "=>", "function")):
                line = src[:m.start()].count("\n") + 1
                errs.append(
                    f"line {line}: {fn}() is given a stage where its items go. "
                    f"The signature is {fn}(items, ...) — pass the array, even "
                    f"if it is one implicit item — [1], never [null]."
                )
    return errs


def check_nondeterminism(src: str) -> list[str]:
    errs = []
    for pattern, why in NONDETERMINISM:
        for m in re.finditer(pattern, src):
            line = src[:m.start()].count("\n") + 1
            errs.append(f"line {line}: {why}")
    return errs


def check_meta_not_read(src: str) -> list[str]:
    """The body may DECLARE `meta`; it may not READ it.

    The runtime lifts the meta export out of the script's scope, so
    `meta.phases.map(...)` in the body throws `meta is not defined` before a
    single agent starts — measured 2026-08-28. Unlike the backtick problem this
    one is exact, not a heuristic: any `meta` token outside the export
    declaration is the bug.
    """
    errs = []
    decl = re.search(r"export\s+const\s+meta\s*=", src)
    for m in re.finditer(r"\bmeta\b", src):
        if decl and decl.start() <= m.start() < decl.end():
            continue
        line = src[:m.start()].count("\n") + 1
        errs.append(f"line {line}: the body reads `meta` — the runtime lifts it out of "
                    f"scope, so this throws 'meta is not defined' before any agent runs. "
                    f"Spell the value out instead.")
    return errs


def check_use_before_declared(src: str) -> list[str]:
    """A top-level call to a `const` declared further down throws at line one.

    Measured 2026-08-28: `enter('Answers')` sat 30 lines above `const enter = …`
    and the run died with "Cannot access 'enter' before initialization" — no
    agent started. Deliberately narrow: only TOP-LEVEL calls (column 0) against
    TOP-LEVEL const declarations. A reference inside a function body is legal
    however it is ordered, and flagging those would red every valid script.
    """
    decl = {}
    for m in re.finditer(r"^const\s+([A-Za-z_]\w*)\s*=", src, re.M):
        decl.setdefault(m.group(1), m.start())
    errs = []
    for m in re.finditer(r"^([A-Za-z_]\w*)\s*\(", src, re.M):
        name = m.group(1)
        if name in decl and m.start() < decl[name]:
            line = src[:m.start()].count("\n") + 1
            errs.append(f"line {line}: `{name}()` is called above its `const {name} =` — "
                        f"the run dies before any agent starts")
    return errs


def check_phases(src: str) -> list[str]:
    """A phase() with no meta entry gets its own progress group — legal, and
    usually a typo. Report the mismatch rather than guessing which side is right."""
    block, _ = meta_block(src)
    declared = set(re.findall(r"title:\s*['\"]([^'\"]+)['\"]", block))
    called = set(re.findall(r"\bphase\(\s*['\"]([^'\"]+)['\"]\s*\)", src))
    errs = []
    if orphan := sorted(called - declared):
        errs.append(f"phase() titles with no meta.phases entry: {orphan}")
    if unused := sorted(declared - called):
        errs.append(f"meta.phases entries no phase() call uses: {unused}")
    return errs


CHECKS = (node_check, None)  # node_check takes a path; the rest take source


def lint(path: pathlib.Path) -> list[str]:
    if not path.is_file():
        return [f"{path} does not exist"]
    src = path.read_text(encoding="utf-8")
    errs = node_check(path)
    code = code_only(src)
    errs += check_meta(src)
    for check in (check_collection_first, check_nondeterminism, check_phases,
                  check_meta_not_read, check_use_before_declared):
        errs += check(code)
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scripts", nargs="*", type=pathlib.Path)
    ap.add_argument("--all", action="store_true", help="lint every committed workflow script")
    args = ap.parse_args()

    paths = list(args.scripts)
    if args.all or not paths:
        for g in GLOBS:
            paths += sorted(REPO.glob(g))
    if not paths:
        print("no workflow scripts found — nothing was checked, which is not a pass")
        return 1

    failed = 0
    for p in paths:
        errs = lint(p)
        rel = p.relative_to(REPO) if p.is_relative_to(REPO) else p
        if errs:
            failed += 1
            print(f"FAIL {rel}")
            for e in errs:
                print(f"  • {e}")
        else:
            print(f"ok   {rel}")
    print(f"\n{len(paths) - failed}/{len(paths)} scripts pass")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
