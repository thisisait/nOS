#!/usr/bin/env python3
"""Compare the face's `TableView` against KEAP's `viewMetaSchema`.

WHY THIS EXISTS. The render contract is declared TWICE — once as a TypeScript
interface the face renders from, once as a zod schema KEAP validates with — and
until 2026-08-28 NOTHING compared them. The face's own comment says as much:
"Mirrors KEAP's `viewMetaSchema` (shared/contracts/table.ts) — KEAP validates,
this only renders." A mirror nobody looks in.

That is this estate's most expensive recurring shape, and the `view` block has
already paid for it three times in one afternoon: the agent create mapping
forwarded `graph` and not `view`; the reconcile path was write-once for it; and
`GET /api/tables/:id` omitted what `PATCH` accepted. Each failed as SILENCE.

The specific drift this watches for is worse than a crash, because zod STRIPS
unknown keys: a face that starts reading `view.sort` before KEAP declares it
sees `undefined` forever, and a KEAP that adds a key the face never reads keeps
accepting a declaration nothing renders. Neither end goes red.

WHY A READER AND NOT A CI GATE — settled already, by `tools/cortex-drift.py`:
"CI has no KEAP checkout and inventing one would be a second copy to keep in
step — the exact disease." So this runs where both trees exist: the face is
vendored in this repo, and `~/keap/src` is a full checkout the playbook puts on
the host. Without that checkout it says so and reports nothing, which is the
honest answer rather than "no drift".

WHY IT COMPARES FACTS, NOT TEXT. The two files are a TS interface and a zod
object; they will never be textually similar and diffing them would report
drift forever. What must agree is the VOCABULARY: which keys exist, which
styles, which comparison ops, and the caps — the values that decide whether a
declaration written once survives both ends.

Usage:
    tools/view-contract-drift.py            # the comparison
    tools/view-contract-drift.py --json     # for a caller
    tools/view-contract-drift.py --keap ~/other/keap

Exit 0 in agreement (or no KEAP checkout) · 1 when the two contracts disagree.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
FACE = REPO / "files/anatomy/face/src/lib/contracts/index.ts"
FACE_VIEW = REPO / "files/anatomy/face/src/lib/tables/view.ts"
DEFAULT_KEAP = pathlib.Path.home() / "keap" / "src"


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"(?m)//.*$", "", text)


def face_contract() -> dict:
    src = _strip_comments(FACE.read_text(encoding="utf-8"))
    body = re.search(r"export interface TableView \{(.*?)\n\}", src, re.DOTALL)
    keys = set(re.findall(r"^\s*(\w+)\??:", body.group(1), re.MULTILINE)) if body else set()
    styles = re.search(r"style:\s*((?:'[a-z]+'\s*\|?\s*)+)", body.group(1)) if body else None
    ops = re.search(r"export type RowOp\s*=\s*([^;]+);", src)
    caps_src = _strip_comments(FACE_VIEW.read_text(encoding="utf-8"))
    caps = {
        m.group(1): int(m.group(2))
        for m in re.finditer(r"const (MAX_\w+)\s*=\s*(\d+)", caps_src)
    }
    return {
        "keys": sorted(keys),
        "styles": sorted(re.findall(r"'([a-z]+)'", styles.group(1))) if styles else [],
        "ops": sorted(re.findall(r"'(\w+)'", ops.group(1))) if ops else [],
        "caps": caps,
    }


def keap_contract(root: pathlib.Path) -> dict:
    src = _strip_comments((root / "shared/contracts/table.ts").read_text(encoding="utf-8"))
    body = re.search(r"export const viewMetaSchema = z\.object\(\{(.*?)\n\}\);", src, re.DOTALL)
    keys = set(re.findall(r"^\s*(\w+):", body.group(1), re.MULTILINE)) if body else set()
    styles = re.search(r"tableViewStyleSchema = z\.enum\(\[([^\]]+)\]", src)
    ops = re.search(r"filterOpSchema = z\.enum\(\[([^\]]+)\]", src)
    # Caps are `.max(N)` on the three generative keys plus the label lengths.
    caps: dict[str, int] = {}
    for name, pat in (
        ("MAX_FACETS", r"facets: z\.array\(z\.string\(\)\)\.max\((\d+)\)"),
        ("MAX_HIGHLIGHTS", r"highlights: z\.array\(highlightSpecSchema\)\.max\((\d+)\)"),
        ("MAX_PREDICATES", r"when: z\.array\(rowPredicateSchema\)\.min\(1\)\.max\((\d+)\)"),
        ("MAX_LABEL", r"highlightSpecSchema = z\.object\(\{\s*label: z\.string\(\)\.min\(1\)\.max\((\d+)\)"),
        ("MAX_OFFER_LABEL", r"offerSpecSchema = z\.object\(\{\s*label: z\.string\(\)\.min\(1\)\.max\((\d+)\)"),
    ):
        m = re.search(pat, src, re.DOTALL)
        if m:
            caps[name] = int(m.group(1))
    return {
        "keys": sorted(keys),
        "styles": sorted(re.findall(r"'([a-z]+)'", styles.group(1))) if styles else [],
        "ops": sorted(re.findall(r"'(\w+)'", ops.group(1))) if ops else [],
        "caps": caps,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keap", type=pathlib.Path, default=DEFAULT_KEAP)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    contract = args.keap / "shared/contracts/table.ts"
    if not contract.exists():
        report = {"available": False, "why": "no KEAP checkout — nothing to compare",
                  "keap_root": str(args.keap)}
        if args.json:
            json.dump(report, sys.stdout, indent=2, sort_keys=True)
            return 0
        # Absence is reported as absence. "No drift" would be a lie here.
        print(f"{report['why']}\n  looked in {contract}")
        return 0

    face, keap = face_contract(), keap_contract(args.keap)
    findings: list[str] = []

    for axis in ("keys", "styles", "ops"):
        only_face = sorted(set(face[axis]) - set(keap[axis]))
        only_keap = sorted(set(keap[axis]) - set(face[axis]))
        if only_face:
            findings.append(
                f"{axis}: the face declares {only_face} that KEAP does not — zod STRIPS "
                f"unknown keys, so the face would read undefined forever, silently"
            )
        if only_keap:
            findings.append(
                f"{axis}: KEAP declares {only_keap} that the face does not read — a "
                f"declaration the store accepts and no renderer honours"
            )

    for name in sorted(set(face["caps"]) & set(keap["caps"])):
        if face["caps"][name] != keap["caps"][name]:
            findings.append(
                f"cap {name}: face={face['caps'][name]} keap={keap['caps'][name]} — the "
                f"tighter end truncates at render what the other end accepted"
            )
    missing_caps = sorted(set(keap["caps"]) - set(face["caps"]))
    if missing_caps:
        findings.append(f"caps only KEAP enforces: {missing_caps}")

    if args.json:
        json.dump({"available": True, "face": face, "keap": keap, "findings": findings},
                  sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 1 if findings else 0

    print(f"face  {FACE.relative_to(REPO)}")
    print(f"keap  {contract}")
    print(f"  keys   {len(face['keys'])} vs {len(keap['keys'])}")
    print(f"  styles {face['styles']}")
    print(f"  ops    {len(face['ops'])} vs {len(keap['ops'])}")
    print(f"  caps   {face['caps']}")
    if not findings:
        print("\nThe two contracts agree.")
        return 0
    print(f"\n{len(findings)} disagreement(s):")
    for f in findings:
        print(f"  - {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
