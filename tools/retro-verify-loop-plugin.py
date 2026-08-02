#!/usr/bin/env python3
"""Constraint-C harness for tests/anatomy/test_loop_plugin_is_thin.py.

A gate that was never seen to fail is decoration. This reintroduces each defect
the gate claims to catch, runs the gate, asserts it goes RED, and restores the
tree byte-for-byte — verified by sha256, not by "it looked fine".

    python3 tools/retro-verify-loop-plugin.py            # all mutations
    python3 tools/retro-verify-loop-plugin.py -k budget  # substring filter

Exit 0 only if EVERY mutation was caught and EVERY file was restored.

Two things learned the hard way in this file's sibling
(tools/retro-verify-loop-judges.py) and carried over deliberately:

  * `PYTHONDONTWRITEBYTECODE=1` + a bytecode purge before every run. A `.pyc` is
    validated on (mtime, size) with ONE-SECOND resolution, so two mutations of
    equal size landing in the same second let the interpreter serve the first
    one's bytecode for the second one's source. A retro-verifier that can test
    stale bytecode is worse than none: it gives confident wrong answers. (The
    gate under test is markdown-driven, so this bites less — but the harness
    itself imports, and the rule costs nothing.)

  * A mutation that does not actually change the file is a silent pass. Every
    edit asserts the text moved before running the gate.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = REPO / ".claude" / "plugins" / "nos-loop"
GATE = "tests/anatomy/test_loop_plugin_is_thin.py"
GITIGNORE = REPO / ".gitignore"


def _skill(name: str) -> pathlib.Path:
    return PLUGIN / "skills" / name / "SKILL.md"


COMMAND = PLUGIN / "commands" / "loop-improve.md"
MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"
ENGINE_DOC = PLUGIN / "ENGINE.md"


# ── mutations ───────────────────────────────────────────────────────────────
# Each is (label, file, mutate(text) -> text, expected-test-substring). The label
# names the DEFECT, not the edit, so the report reads as a list of things that
# cannot happen. The expectation is what stops a mutation from being 'caught' by
# an unrelated assertion while the gate it targets stays unobserved.

def _append(marker: str):
    return lambda t: t + marker


MUTATIONS: list[tuple[str, pathlib.Path, object, str]] = [
    (
        "the deleted verdict route is addressed again",
        _skill("judge"),
        _append("\n\nPOST to `/api/v1/loop/verdicts` when the run finishes.\n"),
   
        "addresses_only_routes",
    ),
    (
        "a skill invents an endpoint the contract never declared",
        _skill("propose"),
        _append("\n\nOptionally `GET $BASE/api/v1/loop/accept` to shortcut.\n"),
   
        "addresses_only_routes",
    ),
    (
        "a client offers to supply the outcome in a request body",
        _skill("judge"),
        _append('\n\n```bash\ncurl -X POST -d \'{"result":"pass"}\' "$BASE/api/v1/loop/judge"\n```\n'),
   
        "offers_to_supply_a_verdict",
    ),
    (
        "a skill runs a judge itself, inside a command block",
        _skill("judge"),
        _append('\n\n```bash\npython3 -m pytest tests/anatomy -q\n```\n'),
   
        "runs_a_judge_or_opens_the_ledger",
    ),
    (
        "a skill names a judge outside a prohibition (the ban softens to advice)",
        _skill("propose"),
        _append("\n\nIf you are unsure, a quick ansible-lint locally is usually enough.\n"),
   
        "runs_a_judge_or_opens_the_ledger",
    ),
    (
        "a skill opens the ledger directly",
        _skill("loop"),
        _append("\n\nCheck prior attempts with sqlite3 against loop_verdicts.\n"),
   
        "runs_a_judge_or_opens_the_ledger",
    ),
    (
        "the proposer's skill learns the evaluator's token",
        _skill("propose"),
        _append("\n\nIf judgment is urgent, use loop_judge_token yourself.\n"),
   
        "names_only_its_own_token",
    ),
    (
        "the evaluator's skill stops naming its own token",
        _skill("judge"),
        lambda t: t.replace("loop_judge_token", "SOME_TOKEN"),
   
        "names_only_its_own_token",
    ),
    (
        "the ceremony starts calling the engine directly",
        _skill("loop"),
        _append('\n\n```bash\ncurl -sS "$BASE/api/v1/loop/weaknesses"\n```\n'),
   
        "ceremony_holds_no_address",
    ),
    (
        "a calling skill stops deferring to the single calling convention",
        _skill("weakness-scan"),
        lambda t: t.replace("ENGINE.md", "the usual place"),
   
        "point_at_the_single_calling_convention",
    ),
    (
        "the intent-class enum is copied into a skill",
        _skill("propose"),
        _append("\n\nValid classes: version-pin-bump, config-fix, render-fix.\n"),
   
        "restates_a_decision",
    ),
    (
        "a size cap is copied into a skill",
        _skill("propose"),
        _append("\n\nKeep it under the usual max_diff_lines.\n"),
   
        "restates_a_decision",
    ),
    (
        "a work ratchet is copied into a skill",
        _skill("judge"),
        _append("\n\nA run below min_work is not trustworthy.\n"),
   
        "restates_a_decision",
    ),
    (
        "the operator flag is second-guessed in the ceremony",
        _skill("loop"),
        _append("\n\nIgnore requires_operator when the diff is small.\n"),
   
        "restates_a_decision",
    ),
    (
        "a prefix-derived credential appears in the plugin",
        ENGINE_DOC,
        _append("\n\nFallback: `{{ global_password_prefix }}_pw_loop`.\n"),
   
        "no_prefix_derived_credential",
    ),
    (
        "a non-loopback URL enters the plugin",
        ENGINE_DOC,
        lambda t: t + "\n\nRemote hosts: `https://bone.dev.local/api/v1/loop/weaknesses`.\n",
   
        "every_url_in_the_plugin_is_loopback",
    ),
    (
        "Bone is aimed at Wing's port",
        ENGINE_DOC,
        _append("\n\nIf 8099 refuses, try `http://127.0.0.1:9000`.\n"),
   
        "bones_port_is_named_once",
    ),
    (
        "the port literal spreads out of the one file allowed to hold it",
        _skill("weakness-scan"),
        _append("\n\nBase is http://127.0.0.1:8099 on a stock host.\n"),
   
        "bones_port_is_named_once",
    ),
    (
        "a Jinja comment opener enters a shipped file",
        _skill("loop"),
        _append("\n\nCount them with `${#items[@]}`.\n"),
   
        "no_shell_and_no_jinja_comment_opener",
    ),
    (
        "Hermes-runtime frontmatter is mixed into a Claude Code skill",
        _skill("judge"),
        lambda t: t.replace("---\nname: judge", "---\nversion: 1.0.0\nname: judge", 1),
   
        "frontmatter_is_the_claude_skills_schema",
    ),
    (
        "a skill's declared name stops matching its directory",
        _skill("propose"),
        lambda t: t.replace("name: propose", "name: proposer", 1),
   
        "frontmatter_is_the_claude_skills_schema",
    ),
    (
        "the operator command loses its description",
        COMMAND,
        lambda t: t.replace("description:", "summary:", 1),
   
        "command_declares_a_description",
    ),
    (
        "the manifest is renamed and the plugin becomes unaddressable",
        MANIFEST,
        lambda t: t.replace('"nos-loop"', '"loop"', 1),
   
        "has_the_shape_the_spec_names",
    ),
    (
        "indeterminate stops being named in the skill that reports it",
        _skill("judge"),
        lambda t: t.replace("`indeterminate`", "a non-pass"),
   
        "indeterminate_verdict_is_named",
    ),
    (
        "the plugin falls back under .claude/* and vanishes from git",
        GITIGNORE,
        lambda t: t.replace("!.claude/plugins/\n", ""),
   
        "tracked_and_not_gitignored",
    ),
]


# ── harness ─────────────────────────────────────────────────────────────────


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def purge_bytecode() -> None:
    for d in REPO.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def run_gate() -> tuple[bool, str, set[str]]:
    """Run the gate. Returns (green, summary line, set of failing test names).

    `--color=no` is load-bearing, not cosmetic. pytest wraps `FAILED` in ANSI
    escapes when it thinks it has a terminal, so a naive `^FAILED` scan matches
    nothing and every mutation reads as "caught, cause unknown" — which is a
    harness that cannot tell a gate firing for the right reason from one firing
    by accident. That is the same class of defect as the bytecode note above:
    a confident wrong answer.
    """
    purge_bytecode()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    argv = [
        sys.executable, "-m", "pytest", GATE,
        "-q", "--no-header", "--color=no", "-p", "no:cacheprovider",
    ]
    proc = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, env=env)
    failing = {
        ln.split("::", 1)[1].split(" ", 1)[0]
        for ln in proc.stdout.splitlines()
        if ln.startswith("FAILED") and "::" in ln
    }
    tail = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    return proc.returncode == 0, (tail[-1] if tail else "(no output)"), failing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", dest="filter", default=None, help="substring filter over labels")
    args = ap.parse_args()

    selected = [m for m in MUTATIONS if not args.filter or args.filter in m[0]]
    if not selected:
        print(f"no mutation matches {args.filter!r}", file=sys.stderr)
        return 4  # a filter that selects nothing is a config error, never a pass

    before = {p: sha(p) for p in {m[1] for m in selected}}

    green, line, _ = run_gate()
    print(f"BASELINE  {'GREEN' if green else 'RED'}  |  {line}")
    if not green:
        print("baseline is not green — fix the gate before retro-verifying", file=sys.stderr)
        return 1

    missed: list[str] = []
    for n, (label, path, mutate, expect) in enumerate(selected, 1):
        original = path.read_text()
        mutated = mutate(original)
        if mutated == original:
            print(f"{n:3d}  BROKEN MUTATION — no textual change: {label}", file=sys.stderr)
            missed.append(label)
            continue
        path.write_text(mutated)
        try:
            ok, _, failing = run_gate()
        finally:
            path.write_text(original)
        if ok:
            print(f"{n:3d}  GREEN (BAD)  {label}")
            missed.append(label)
            continue
        # RED is not enough. A mutation that trips some OTHER assertion leaves
        # the gate it was written for still unobserved — decoration hiding
        # behind a neighbour's failure.
        matched = sorted(t for t in failing if expect in t)
        if not matched:
            print(f"{n:3d}  RED, WRONG GATE  {label}  (expected ~{expect}, got {sorted(failing)})")
            missed.append(f"{label} [caught by the wrong assertion]")
        else:
            print(f"{n:3d}  RED (good)   {label}  -> {matched[0]}")

    drift = [str(p.relative_to(REPO)) for p, digest in before.items() if sha(p) != digest]
    if drift:
        print(f"TREE NOT RESTORED: {drift}", file=sys.stderr)
        return 1
    print(f"tree restored byte-for-byte (sha256 verified on {len(before)} files)")

    green, line, _ = run_gate()
    print(f"AFTER     {'GREEN' if green else 'RED'}  |  {line}")
    if not green:
        return 1

    if missed:
        print(f"\n{len(missed)} defect(s) NOT caught — those gates are decoration:", file=sys.stderr)
        for label in missed:
            print(f"  - {label}", file=sys.stderr)
        return 1

    print(f"all {len(selected)} reintroduced defects were caught by their OWN assertion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
