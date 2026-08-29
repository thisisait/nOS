#!/usr/bin/env python3
"""Retro-verification harness for the weakness-reader gates (constraint C).

"A gate you can satisfy by editing the gate is not one. Every gate must be
RETRO-VERIFIED: reintroduce the defect, watch it go red, restore."

For each defect below this script:
  1. reintroduces it by an exact string substitution in the real source,
  2. runs the ONE test node that is supposed to catch it,
  3. asserts that node went RED,
  4. restores the file byte-for-byte and re-asserts GREEN.

A mutation that does NOT go red is reported as DECORATION. A gate that has
never been seen to fail is not evidence of anything — it is a comment with a
test runner attached.

Sibling harness: tools/retro-verify/loop-judges.py (build step 1).

Usage:  python3 tools/retro-verify/weakness-reader.py
"""

from __future__ import annotations

import hashlib
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

READER = REPO / "files" / "anatomy" / "bone" / "weaknesses.py"
LOOPAUTH = REPO / "files" / "anatomy" / "bone" / "loopauth.py"
BONE_MAIN = REPO / "files" / "anatomy" / "bone" / "main.py"
CREDENTIALS = REPO / "default.credentials.yml"
PLIST = REPO / "roles" / "pazny.bone" / "templates" / "bone.plist.j2"
TRAEFIK_VARS = REPO / "roles" / "pazny.traefik" / "vars" / "main.yml"

BEHAVIOUR = "tests/bone_loop"
SHAPE = "tests/anatomy/test_loop_weakness_reader.py"

# (label, file, old, new, test file, test node that MUST go red)
MUTATIONS: list[tuple[str, pathlib.Path, str, str, str, str]] = [
    # ── requirement 1: the git working tree ──────────────────────────────────
    (
        "a scheduled job's output is treated like any other dirty file",
        READER,
        "        if path in MACHINE_WRITTEN:\n            machine.append",
        "        if False:\n            machine.append",
        BEHAVIOUR,
        "test_uncommitted_scheduled_job_output_surfaces_high_and_names_the_writer",
    ),
    (
        "untracked dirs collapse, hiding a machine-written file inside a new dir",
        READER,
        '"--untracked-files=all"',
        '"--untracked-files=normal"',
        BEHAVIOUR,
        "test_untracked_scheduled_job_output_is_the_same_failure",
    ),
    (
        "porcelain -z rename entries desync the parser by one",
        READER,
        '        if xy[0] in ("R", "C"):\n            i += 1',
        '        if False:\n            i += 1',
        BEHAVIOUR,
        "test_renamed_paths_do_not_desync_the_porcelain_parser",
    ),
    # ── requirement 2: self-reported freshness ───────────────────────────────
    (
        "scan-state freshness stops declaring itself self-reported",
        READER,
        "            basis=BASIS_SELF_REPORTED,\n            value=str(claim) if claim else None,\n"
        '            written_by="the security scan itself',
        "            basis=BASIS_OBSERVED,\n            value=str(claim) if claim else None,\n"
        '            written_by="the security scan itself',
        BEHAVIOUR,
        "test_scan_state_freshness_is_marked_self_reported_and_names_its_author",
    ),
    (
        "a staleness severity derived from a self-report stops saying so",
        READER,
        "                # SELF-REPORTED: the severity above is computed from a value the\n"
        "                # scan wrote about itself. Marked, and shipped with its corroborator.\n"
        "                derived_from_self_report=True,",
        "                derived_from_self_report=False,",
        BEHAVIOUR,
        "test_staleness_severity_declares_it_came_from_a_self_report",
    ),
    (
        "the self-report contradicting the append-only log is swallowed",
        READER,
        "    if not f.self_reported or f.corroborated is not False:\n        return None",
        "    if True:\n        return None",
        BEHAVIOUR,
        "test_a_self_report_contradicted_by_the_append_only_log_is_its_own_weakness",
    ),
    (
        "the corroboration check is applied to one source instead of all of them",
        READER,
        '    load_bearing = report.name in SOURCE_FRESHNESS_LOAD_BEARING',
        '    load_bearing = report.name in SOURCE_FRESHNESS_LOAD_BEARING\n'
        '    if not load_bearing:\n        return None',
        BEHAVIOUR,
        "test_the_same_check_covers_every_self_reporting_source",
    ),
    (
        "an anonymous self-report (no written_by) is accepted",
        READER,
        '            raise ValueError("self_reported freshness must name written_by")',
        "            pass",
        BEHAVIOUR,
        "test_freshness_refuses_an_anonymous_self_report",
    ),
    # ── absence is never success ─────────────────────────────────────────────
    (
        "an unreadable source contributes silence instead of a weakness",
        READER,
        "        weaknesses=[\n            Weakness(\n                weakness_id=f\"source:{name}:{status}\",",
        "        weaknesses=[] and [\n            Weakness(\n                weakness_id=f\"source:{name}:{status}\",",
        BEHAVIOUR,
        "test_a_missing_required_source_produces_a_weakness_and_drops_complete",
    ),
    (
        "`complete` stops tracking degraded sources",
        READER,
        '        "complete": not degraded,',
        '        "complete": True,',
        BEHAVIOUR,
        "test_an_optional_host_source_absent_is_info_but_still_visible",
    ),
    (
        "one exploding source blanks the whole list",
        READER,
        "        except Exception as exc:  # noqa: BLE001 — one bad source must not blank the list",
        "        except ZeroDivisionError as exc:  # narrowed",
        BEHAVIOUR,
        "test_a_source_that_raises_does_not_blank_the_list",
    ),
    (
        "an empty corpus ledger reads as an agreeing one",
        READER,
        "    if not nights:",
        "    if False:",
        BEHAVIOUR,
        "test_an_empty_corpus_ledger_is_not_an_agreeing_one",
    ),
    (
        "a fee index that parses to zero rows reads as thirteen closed fees",
        READER,
        '            detail="index table parsed to zero rows — format drift",',
        '            detail="empty",',
        BEHAVIOUR,
        "test_an_empty_fee_table_is_format_drift_not_thirteen_closed_fees",
    ),
    # ── source correctness ───────────────────────────────────────────────────
    (
        "severity is read without the pending gate (37 CRITICAL, 0 pending)",
        READER,
        '        if not isinstance(item, dict) or item.get("status") != "pending":',
        "        if not isinstance(item, dict):",
        BEHAVIOUR,
        "test_severity_is_gated_on_pending_status",
    ),
    (
        "the hand-maintained summary is trusted instead of audited",
        READER,
        '    if claimed is not None and {k: int(v) for k, v in claimed.items()} != recomputed:',
        "    if False:",
        BEHAVIOUR,
        "test_counts_are_derived_from_items_and_the_summary_is_audited",
    ),
    (
        "a fee already being paid ranks level with a conditional one",
        READER,
        '    if "being paid now" in text or "paid)" in text:\n        return "high"',
        '    if False:\n        return "high"',
        BEHAVIOUR,
        "test_a_fee_being_paid_now_outranks_a_conditional_one",
    ),
    (
        "a file Status contradicting the index is not reported",
        READER,
        "        if own and _fee_state(own.group(\"status\")) != state:",
        "        if False:",
        BEHAVIOUR,
        "test_a_file_status_that_contradicts_the_index_is_reported",
    ),
    # ── hashing / filters ────────────────────────────────────────────────────
    (
        "a derived age leaks into evidence, so every dedup block lifts daily",
        READER,
        '                    "threshold_days": SCAN_STALE_DAYS,\n                },',
        '                    "threshold_days": SCAN_STALE_DAYS,\n                    "age_days": age,\n                },',
        BEHAVIOUR,
        "test_the_passage_of_time_does_not_change_evidence_sha",
    ),
    (
        "an unknown severity floor is coerced to 'info' instead of refused",
        READER,
        "        if floor != str(min_severity).strip().lower():",
        "        if False:",
        BEHAVIOUR,
        "test_unknown_severity_is_refused_not_coerced_to_info",
    ),
    (
        "a truncated view reports a smaller estate",
        READER,
        '        "counts": {**counts, "total": total_before_top},',
        '        "counts": {**counts, "total": len(ranked)},',
        BEHAVIOUR,
        "test_top_truncates_the_list_but_counts_stay_honest",
    ),
    # ── constraint A: two identities ─────────────────────────────────────────
    (
        "the proposer is handed the judge scope",
        LOOPAUTH,
        '"agent:proposer": ("BONE_LOOP_PROPOSE_TOKEN", frozenset({"read", "propose"})),',
        '"agent:proposer": ("BONE_LOOP_PROPOSE_TOKEN", frozenset({"read", "propose", "judge"})),',
        BEHAVIOUR,
        "test_the_proposer_cannot_trigger_a_judge",
    ),
    (
        "both identities collapse onto one env var",
        LOOPAUTH,
        '"engine:evaluator": ("BONE_LOOP_JUDGE_TOKEN"',
        '"engine:evaluator": ("BONE_LOOP_PROPOSE_TOKEN"',
        BEHAVIOUR,
        "test_the_two_tokens_are_distinct_env_vars",
    ),
    # ── constraint D: no prefix-derived credential ───────────────────────────
    (
        "a `_pw_`-derived token authenticates at runtime",
        LOOPAUTH,
        "        if DERIVED_MARKER in token:",
        "        if False:",
        BEHAVIOUR,
        "test_a_prefix_derived_token_is_refused_at_runtime",
    ),
    (
        "loop_propose_token goes back to being prefix-derived",
        CREDENTIALS,
        'loop_propose_token: ""',
        'loop_propose_token: "{{ global_password_prefix }}_pw_loop_propose"',
        SHAPE,
        "test_loop_tokens_are_not_prefix_derived",
    ),
    (
        "the loop token stops reaching the launchd env",
        PLIST,
        "        <key>BONE_LOOP_JUDGE_TOKEN</key>",
        "        <key>BONE_LOOP_JUDGE_TOKEN_DISABLED</key>",
        SHAPE,
        "test_loop_tokens_reach_both_service_managers",
    ),
    # ── constraint E: loopback only ──────────────────────────────────────────
    (
        "the loopback check is removed, leaving only the bind",
        LOOPAUTH,
        "        if host not in LOOPBACK_HOSTS:",
        "        if False:",
        BEHAVIOUR,
        "test_a_non_loopback_client_is_refused",
    ),
    (
        "bone leaves traefik_skip_ids, putting the reader on the edge",
        TRAEFIK_VARS,
        "traefik_skip_ids:\n  - bone",
        "traefik_skip_ids:\n  - bone_disabled",
        SHAPE,
        "test_bone_remains_in_the_traefik_skip_list",
    ),
    # ── shape gates ──────────────────────────────────────────────────────────
    (
        "the reader is defined but never mounted",
        BONE_MAIN,
        "    app.include_router(_nos_weaknesses.router)",
        "    pass  # router not mounted",
        SHAPE,
        "test_the_reader_is_mounted_on_bones_app",
    ),
    (
        "the reader gains a write",
        READER,
        "def _mtime_iso(path: Path) -> str | None:\n    try:",
        'def _mtime_iso(path: Path) -> str | None:\n    path.with_suffix(".seen").write_text("")\n    try:',
        SHAPE,
        "test_the_reader_contains_no_write_verb",
    ),
    (
        "the reader gains a mutating git subcommand",
        READER,
        '    rc, out = _git(root, "rev-parse", "--show-toplevel")',
        '    rc, out = _git(root, "clean", "--dry-run")',
        SHAPE,
        "test_the_reader_spawns_only_read_only_git",
    ),
    (
        "the route accepts a parameter that is not a filter",
        READER,
        "    min_severity: str | None = Query(default=None),\n    _caller=Depends",
        "    min_severity: str | None = Query(default=None),\n    severity_override: str | None = Query(default=None),\n    _caller=Depends",
        SHAPE,
        "test_no_route_parameter_can_influence_a_weakness",
    ),
    (
        "a watched machine-written path is renamed out from under the alarm",
        READER,
        '    "state/devlog-bundle.jsonl": "tools/devlog-compile.py",',
        '    "state/devlog-bundle-renamed.jsonl": "tools/devlog-compile.py",',
        SHAPE,
        "test_every_machine_written_path_still_exists",
    ),
    (
        "a source is declared with no required-flag, so it rates its own absence",
        READER,
        '    "corpus-diff": False,\n}',
        "}",
        SHAPE,
        "test_the_declared_sources_match_the_readers",
    ),
]


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_node(testfile: str, node: str) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", testfile, "-k", node, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    tail = proc.stdout.strip().splitlines()
    return proc.returncode == 0, tail[-1] if tail else "(no output)"


def main() -> int:
    print(f"retro-verifying {len(MUTATIONS)} gates for the weakness reader\n")

    ok, line = run_node(BEHAVIOUR, "test_")
    if not ok:
        print(f"REFUSING TO START: {BEHAVIOUR} is not green — {line}")
        return 2
    ok, line = run_node(SHAPE, "test_")
    if not ok:
        print(f"REFUSING TO START: {SHAPE} is not green — {line}")
        return 2

    decoration: list[str] = []
    unrestored: list[str] = []

    for i, (label, path, old, new, testfile, node) in enumerate(MUTATIONS, 1):
        rel = path.relative_to(REPO)
        original = path.read_text(encoding="utf-8")
        before = sha(path)

        if original.count(old) != 1:
            print(f"[{i:2}/{len(MUTATIONS)}] ANCHOR MISS ({original.count(old)}x) {label}")
            decoration.append(f"{label} (anchor not unique in {rel})")
            continue

        path.write_text(original.replace(old, new, 1), encoding="utf-8")
        try:
            passed, line = run_node(testfile, node)
        finally:
            path.write_text(original, encoding="utf-8")

        if sha(path) != before:
            unrestored.append(str(rel))

        verdict = "DECORATION" if passed else "caught"
        print(f"[{i:2}/{len(MUTATIONS)}] {verdict:10} {node}\n{'':15}↳ {label}\n{'':15}↳ {line}")
        if passed:
            decoration.append(f"{node}: {label}")

    print()
    ok_b, line_b = run_node(BEHAVIOUR, "test_")
    ok_s, line_s = run_node(SHAPE, "test_")
    print(f"restored {BEHAVIOUR}: {'GREEN' if ok_b else 'RED'} — {line_b}")
    print(f"restored {SHAPE}: {'GREEN' if ok_s else 'RED'} — {line_s}")

    if unrestored:
        print(f"\nFILES NOT RESTORED: {unrestored}")
    if decoration:
        print(f"\n{len(decoration)} DECORATIVE gate(s) — a gate that cannot fail proves nothing:")
        for d in decoration:
            print(f"  - {d}")
        return 1
    if not (ok_b and ok_s and not unrestored):
        return 1

    print(f"\nall {len(MUTATIONS)} reintroduced defects were caught; no decoration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
