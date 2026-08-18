#!/usr/bin/env python3
"""Compare the vendored cortex organ against the KEAP tree it was cut from.

WHY THIS EXISTS. `docs/hidden_fees/11` states the problem and, in its "what
closes it", says of drift detection: *"It cannot detect drift from the original
— nothing in this repo can."* That sentence is true of the REPO and was quietly
false of the HOST: `~/keap/src` is a full checkout, put there by the playbook,
sitting beside the vendored copy the whole time. The comparison was never
impossible, only never written.

So this is the mitigation the entry called for, in the only shape it can take:
a reader that runs where both trees exist, not a CI gate. CI has no KEAP
checkout and inventing one would be a second copy to keep in step — the exact
disease. On a host without `~/keap/src` this says so and reports nothing, which
is the honest answer rather than "no drift".

WHAT IT FOUND ON ITS FIRST RUN, 2026-08-18, organ 0.1.0 against KEAP 1.40.1 —
and one of the three is not cosmetic:

    cortex-opcodes.ts
      -export const MODEL_URI_RE = /^(anthropic|claude|openai|openclaw)-…/
      +export const MODEL_URI_RE = /^(anthropic|openclaw)-…/

The organ accepts `claude-*` and `openai-*` model URIs; KEAP rejects them. Two
implementations of one language disagreeing about what the language IS, which is
precisely the bill entry 11 predicted — *"`ast.binding` stamps are issued for a
language the source repo no longer speaks"* — arriving before anyone looked.

WHAT IT IS NOT. It does not merge, re-vendor, or edit either tree. Choosing a
direction is a decision about the language, and `S5` (delete one of the two
implementations) is the only real close; everything here is mitigation that
makes the drift visible while both exist.

Usage:
    tools/cortex-drift.py                # summary, one line per file
    tools/cortex-drift.py --diff         # full unified diffs
    tools/cortex-drift.py --json
    tools/cortex-drift.py --keap ~/other # a different KEAP checkout

Exit 0 always, including when everything has drifted. Drift is a fact about two
trees, not a defect a commit introduced — and see `tools/rem-status.py`'s header
for why this estate does not wire facts to build failures.
"""

from __future__ import annotations

import argparse
import difflib
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
ORGAN = REPO / "files/anatomy/cortex"
DEFAULT_KEAP = pathlib.Path.home() / "keap" / "src"

#: Subtrees the organ vendors. A file present in the organ and absent from KEAP
#: is reported rather than skipped — it is either organ-only by design or a
#: rename KEAP made and we did not follow, and those look identical from here.
VENDORED = ("server", "shared", "knowledge", "docs")

#: Noise that says nothing about whether the two implementations agree.
SKIP = re.compile(r"(/node_modules/|/dist|/test-results/|\.map$|\.log$)")

#: The organ marks its own locally-written files. `server/index.ts` says
#: "LOCALLY AUTHORED (not a port)" in line 2 and shares a NAME with KEAP's
#: standalone backend while being a different program — diffing the two
#: produced 694 changed lines of pure noise on the first run and buried the one
#: finding that mattered. The claim is read from the file rather than kept as a
#: list here, for the same reason the agent-wiring gate reads the agent's own
#: env: a list here would be a third copy to maintain, and this tool exists
#: because copies drift.
LOCALLY_AUTHORED = re.compile(r"LOCALLY AUTHORED", re.I)

#: A DELIBERATE divergence marks itself. `server/fs-sync.ts` carries seven
#: `nOS S2 DIFF n/6` blocks, each naming the upstreamable change and the design
#: section that justifies it — 329 changed lines, every one of them intended.
#: Reporting that beside an undeclared one-line change would make the tool as
#: unreadable as having no tool, so declared drift is counted and set aside.
#:
#: The interesting category is therefore UNDECLARED drift: a file that differs
#: and does not say why. That is the shape entry 11 is actually about.
DECLARED_DIFF = re.compile(r"nOS\s+S\d+\s+DIFF", re.I)


def _files(root: pathlib.Path) -> dict[str, pathlib.Path]:
    out: dict[str, pathlib.Path] = {}
    for sub in VENDORED:
        base = root / sub
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and not SKIP.search(str(path)):
                out[str(path.relative_to(root))] = path
    return out


def _read(path: pathlib.Path) -> list[str] | None:
    try:
        return path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (UnicodeDecodeError, OSError):
        return None   # binary or unreadable: not comparable, and not "identical"


def compare(keap_root: pathlib.Path) -> dict:
    if not keap_root.is_dir():
        return {
            "keap_root": str(keap_root),
            "available": False,
            "why": "no KEAP checkout on this host, so drift is UNKNOWN — not absent",
            "files": [],
        }

    organ_files = _files(ORGAN)
    keap_files = _files(keap_root)

    rows = []
    for rel in sorted(organ_files):
        ours = organ_files[rel]
        head = "".join((_read(ours) or [])[:12])
        if LOCALLY_AUTHORED.search(head):
            # Not a copy, so it cannot have drifted from one. Counted, so a
            # file that quietly LOSES the marker shows up as newly compared
            # rather than silently vanishing from the tally.
            rows.append({"file": rel, "state": "locally_authored", "changed_lines": None})
            continue
        theirs = keap_files.get(rel)
        if theirs is None:
            rows.append({"file": rel, "state": "organ_only", "changed_lines": None})
            continue
        ours_lines, theirs_lines = _read(organ_files[rel]), _read(theirs)
        if ours_lines is None or theirs_lines is None:
            rows.append({"file": rel, "state": "not_comparable", "changed_lines": None})
            continue
        if ours_lines == theirs_lines:
            rows.append({"file": rel, "state": "identical", "changed_lines": 0})
            continue
        diff = list(difflib.unified_diff(
            ours_lines, theirs_lines,
            fromfile=f"organ/{rel}", tofile=f"keap/{rel}", n=2,
        ))
        changed = sum(1 for line in diff
                      if line[:1] in "+-" and not line.startswith(("+++", "---")))
        declared = len(DECLARED_DIFF.findall("".join(ours_lines)))
        rows.append({
            "file": rel,
            "state": "declared_diff" if declared else "drifted",
            "declared_markers": declared,
            "changed_lines": changed,
            "diff": "".join(diff),
        })

    # KEAP files the organ never vendored are NOT drift — the organ is a subset
    # by design — so they are counted, not listed. A count that jumps is a hint
    # that KEAP grew a module the organ may want.
    keap_only = len(set(keap_files) - set(organ_files))

    return {
        "keap_root": str(keap_root),
        "available": True,
        "organ_version": (ORGAN / "VERSION").read_text().strip()
        if (ORGAN / "VERSION").is_file() else "unknown",
        "keap_version": _keap_version(keap_root),
        "files": rows,
        "keap_only_count": keap_only,
    }


def _keap_version(root: pathlib.Path) -> str:
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            return str(json.loads(pkg.read_text(encoding="utf-8")).get("version", "unknown"))
        except json.JSONDecodeError:
            pass
    return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keap", type=pathlib.Path, default=DEFAULT_KEAP)
    ap.add_argument("--diff", action="store_true", help="print full unified diffs")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report = compare(args.keap)

    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    if not report["available"]:
        print(f"{report['why']}")
        print(f"  looked in {report['keap_root']}")
        return 0

    drifted = [r for r in report["files"] if r["state"] == "drifted"]
    declared = [r for r in report["files"] if r["state"] == "declared_diff"]
    organ_only = [r for r in report["files"] if r["state"] == "organ_only"]
    identical = sum(1 for r in report["files"] if r["state"] == "identical")
    local = sum(1 for r in report["files"] if r["state"] == "locally_authored")

    print(f"organ {report['organ_version']} vs KEAP {report['keap_version']} "
          f"({report['keap_root']})")
    print(f"  {identical} identical · {len(drifted)} UNDECLARED drift · "
          f"{len(declared)} declared · {local} locally authored · "
          f"{len(organ_only)} organ-only · {report['keap_only_count']} KEAP-only (not vendored)")
    if declared:
        print("  declared (each carries its own `nOS Sn DIFF` markers): "
              + ", ".join(f"{r['file'].split('/')[-1]}×{r['declared_markers']}" for r in declared))

    for row in sorted(drifted, key=lambda r: -r["changed_lines"]):
        print(f"\n  ~ {row['file']}  ({row['changed_lines']} changed line(s))")
        if args.diff:
            print("".join(f"      {line}" for line in row["diff"].splitlines(keepends=True)))
        else:
            for line in row["diff"].splitlines():
                if line[:1] in "+-" and not line.startswith(("+++", "---")):
                    print(f"      {line[:150]}")

    if organ_only:
        print(f"\n  organ-only ({len(organ_only)}) — either deliberate, or a rename "
              "KEAP made that we did not follow; the two look the same from here:")
        for row in organ_only[:20]:
            print(f"      {row['file']}")
        if len(organ_only) > 20:
            print(f"      … and {len(organ_only) - 20} more")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
