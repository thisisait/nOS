#!/usr/bin/env python3
"""Retro-verification harness for the cross-harness determinism gate.

Constraint C: "a gate you can satisfy by editing the gate is not one." A gate
that was never seen to fail is decoration, so every assertion in
``tests/anatomy/test_loop_determinism_across_harnesses.py`` gets its defect
REINTRODUCED here and must be observed going red.

For each mutation this script:
  1. reintroduces the defect by an exact string substitution in the real source,
  2. runs the one test node that is supposed to catch it,
  3. asserts that node went RED,
  4. restores the file byte-for-byte and re-asserts the sha256.

Any mutation that does NOT go red is reported as DECORATION and the script
exits non-zero.

Note which files are mutated: production sources (Bone modules, the Ansible
vars/templates) and ONE ratchet constant that lives in a test file
(`BLAST_RADIUS_CEILING`). The ratchet is the datum for constraint D — raising
it is the defect being reintroduced — so it is mutated where it is declared.

Usage:  python3 tools/retro-verify-loop-harness.py
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
BONE = REPO / "files" / "anatomy" / "bone"

JUDGES = BONE / "judges.py"
LEDGER = BONE / "ledger.py"
LOOPAUTH = BONE / "loopauth.py"
WEAKNESSES = BONE / "weaknesses.py"
CREDS = REPO / "default.credentials.yml"
MAIN = REPO / "main.yml"
TRAEFIK = REPO / "roles" / "pazny.traefik" / "vars" / "main.yml"
PLIST = REPO / "roles" / "pazny.bone" / "templates" / "bone.plist.j2"
BONE_TASKS = REPO / "roles" / "pazny.bone" / "tasks" / "main.yml"
CODEGEN = REPO / "tools" / "genome-codegen.py"
BLAST = REPO / "tests" / "anatomy" / "test_secret_blast_radius.py"

TESTFILE = "tests/anatomy/test_loop_determinism_across_harnesses.py"

# (label, file, old, new, test node that MUST go red)
MUTATIONS: list[tuple[str, pathlib.Path, str, str, str]] = [
    # ── the guard's own guard ────────────────────────────────────────────────
    (
        "the parity harness stops running a real judge (all three agree on "
        "INDETERMINATE — the false green parity alone cannot see)",
        JUDGES,
        """    resolved = exe if os.path.isabs(exe) else shutil.which(exe)""",
        """    resolved = None""",
        "test_the_parity_harness_really_runs_a_real_judge",
    ),
    # ── 1. the headline ──────────────────────────────────────────────────────
    (
        "the verdict identity carries wall-clock time — two harnesses can never "
        "agree and no verdict replays",
        JUDGES,
        """        return {
            "judge": self.judge_name,""",
        """        return {
            "started_at": self.started_at,
            "judge": self.judge_name,""",
        "test_the_same_tree_yields_the_same_verdict_from_every_harness",
    ),
    (
        "the SEALED verdict records the harness's working directory",
        LEDGER,
        """                "reason": verdict.reason,""",
        """                "reason": verdict.reason,
                "cwd": os.getcwd(),""",
        "test_the_sealed_verdict_agrees_across_processes",
    ),
    (
        "the scope check is removed, so the PROPOSER can trigger the judge run "
        "whose verdict scores its own next patch (constraint A)",
        LOOPAUTH,
        """        if scope not in caller.scopes:""",
        """        if False:""",
        "test_the_same_tree_yields_the_same_verdict_from_every_harness",
    ),
    # ── 2. the invariants underneath parity ──────────────────────────────────
    (
        "the judge inherits the CALLER's working directory instead of the tree",
        JUDGES,
        """            cwd=cwd,""",
        """            cwd=os.getcwd(),""",
        "test_the_judge_runs_in_the_tree_it_was_given_not_the_callers_cwd",
    ),
    (
        "the judge's output is streamed to the caller's terminal (a TTY colours "
        "the very lines the work parser reads)",
        JUDGES,
        """            capture_output=True,
            text=True,
            timeout=timeout_s,""",
        """            stdout=sys.stdout,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,""",
        "test_no_judge_is_ever_handed_a_terminal",
    ),
    (
        "the repo root is resolved from the caller's cwd, so two harnesses read "
        "two registries",
        JUDGES,
        """    return Path(__file__).resolve().parents[3]""",
        """    return Path.cwd()""",
        "test_both_harnesses_resolve_the_same_registry_from_the_source_not_the_cwd",
    ),
    (
        "the registry becomes runtime state under ~/.nos (drifts per host)",
        JUDGES,
        """REGISTRY_RELPATH = "state/judge-sets.yml\"""",
        """REGISTRY_RELPATH = os.path.expanduser("~/.nos/judge-sets.yml")""",
        "test_the_registry_is_committed_and_not_runtime_state",
    ),
    (
        "the exclusive-resource lock becomes per-process (M7's mutex is a no-op "
        "across harnesses and the two judges corrupt nos_entity.py)",
        JUDGES,
        """    locks = Path(lock_dir) if lock_dir else Path(tempfile.gettempdir())""",
        """    locks = Path(lock_dir) if lock_dir else Path(tempfile.mkdtemp())""",
        "test_both_harnesses_name_the_same_exclusive_lock",
    ),
    (
        "the verdict identity carries the sandbox path",
        JUDGES,
        """        return {
            "judge": self.judge_name,""",
        """        return {
            "sandbox_path": self.sandbox_path,
            "judge": self.judge_name,""",
        "test_the_verdict_identity_excludes_every_harness_varying_field",
    ),
    # ── 3. one implementation ────────────────────────────────────────────────
    (
        "a second adapter lands in the ledger — two oracles wearing one name",
        LEDGER,
        """ENGINE_ACTOR = "engine:judge-runner\"""",
        """ENGINE_ACTOR = "engine:judge-runner"


def _adapt_exit_zero(spec, done):
    return judges.Result.PASS, "a second implementation of judgment\"""",
        "test_judgment_has_exactly_one_implementation_in_the_estate",
    ),
    (
        "a tool outside Bone imports the runner (the shared library DECISION 6 "
        "forbids, ported four ways for four runtimes)",
        CODEGEN,
        """import argparse
import json""",
        """import argparse
import json
import judges""",
        "test_nothing_outside_bone_imports_the_judge_runner",
    ),
    (
        "a judge route is mounted that decides for itself instead of delegating",
        WEAKNESSES,
        """@router.get("/weaknesses")""",
        """@router.post("/judge")
async def post_judge(_caller=Depends(require_loop_scope("judge"))):
    return {"result": "pass"}


@router.get("/weaknesses")""",
        "test_any_mounted_judge_route_delegates_rather_than_deciding",
    ),
    (
        "the shell boundary collapses INDETERMINATE onto FAIL",
        JUDGES,
        """    "indeterminate": 2,""",
        """    "indeterminate": 1,""",
        "test_the_verdict_to_exit_code_map_is_declared_once_and_covers_every_verdict",
    ),
    # ── 4. constraint E ──────────────────────────────────────────────────────
    (
        "an engine module opens a wildcard socket",
        LEDGER,
        """def ensure_schema(conn: sqlite3.Connection) -> None:""",
        """def _listen():
    import socket

    s = socket.socket()
    s.bind(("0.0.0.0", 9999))


def ensure_schema(conn: sqlite3.Connection) -> None:""",
        "test_no_engine_module_opens_a_socket_or_a_port",
    ),
    (
        "the launchd unit binds the wildcard address",
        PLIST,
        """        <string>--host</string>
        <string>127.0.0.1</string>""",
        """        <string>--host</string>
        <string>0.0.0.0</string>""",
        "test_bone_binds_loopback_under_both_service_managers",
    ),
    (
        "the systemd ExecStart binds the wildcard address",
        BONE_TASKS,
        """--host 127.0.0.1 --port""",
        """--host 0.0.0.0 --port""",
        "test_bone_binds_loopback_under_both_service_managers",
    ),
    (
        "a loop route is mounted with no scope dependency at all",
        WEAKNESSES,
        """    _caller=Depends(require_loop_scope("read")),""",
        """""",
        "test_every_mounted_loop_route_sits_behind_a_loop_scope_dependency",
    ),
    (
        "the loopback check is removed — REM-144's shape, where the bind was "
        "real and the edge proxied around it",
        LOOPAUTH,
        """        if host not in LOOPBACK_HOSTS:""",
        """        if False:""",
        "test_every_mounted_loop_route_refuses_a_non_loopback_client",
    ),
    (
        "the wildcard address joins the loopback allowlist",
        LOOPAUTH,
        """LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})""",
        """LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient", "0.0.0.0"})""",
        "test_the_loopback_allowlist_holds_only_loopback",
    ),
    (
        "bone leaves traefik_skip_ids — its manifest entry then auto-derives an "
        "edge router straight onto the loop API (REM-144)",
        TRAEFIK,
        """  - bone             # Bone is on host; published only on 127.0.0.1; reach via Wing UI""",
        """  # - bone           (removed)""",
        "test_the_loop_declares_no_new_routable_surface",
    ),
    # ── 5. constraint D ──────────────────────────────────────────────────────
    (
        "the derived default comes back: {prefix}_pw_loop_judge",
        CREDS,
        """loop_judge_token: ""      # openssl rand -hex 32 — minted in main.yml""",
        """loop_judge_token: "{{ global_password_prefix }}_pw_loop_judge\"""",
        "test_no_loop_credential_is_prefix_derived",
    ),
    (
        "the token stops being minted random in main.yml",
        MAIN,
        """        loop_judge_token: "{% if '_pw_' in (loop_judge_token | default('')) or (loop_judge_token | default('') | length) < 32 %}{{ lookup('pipe', 'openssl rand -hex 32') }}{% else %}{{ loop_judge_token }}{% endif %}\"""",
        """        loop_judge_token: "{{ loop_judge_token | default('') }}\"""",
        "test_the_loop_tokens_are_minted_random_and_persisted",
    ),
    (
        "Bone stops refusing a `_pw_`-shaped token at RUNTIME (the declaration "
        "gate and the effect gate are separate on purpose)",
        LOOPAUTH,
        """        if DERIVED_MARKER in token:""",
        """        if False:""",
        "test_a_prefix_derived_loop_token_authenticates_nothing",
    ),
    (
        "the blast-radius ratchet is RAISED to make room for a new derived key",
        BLAST,
        """BLAST_RADIUS_CEILING = 86""",
        """BLAST_RADIUS_CEILING = 87""",
        "test_the_loop_did_not_move_the_blast_radius_ratchet",
    ),
]


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def purge_bytecode(path: pathlib.Path) -> None:
    """Delete cached bytecode for a mutated source file.

    LOAD-BEARING, and learned the hard way by the sibling harness: a .pyc is
    validated against its source by (mtime, size), and mtime has ONE SECOND of
    resolution. Two mutations of the same size written inside one second let
    the interpreter revalidate the FIRST mutation's bytecode as current — the
    test then passes against code that was never loaded, and this harness
    reports a live gate as decoration, intermittently.
    """
    cache = path.parent / "__pycache__"
    if cache.is_dir():
        for pyc in cache.glob(f"{path.stem}.*.pyc"):
            pyc.unlink(missing_ok=True)


def run_test(node: str) -> tuple[bool, str]:
    target = f"{TESTFILE}::{node}" if node else TESTFILE
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "--no-header", "-x"],
        cwd=REPO, capture_output=True, text=True, env=env,
    )
    tail = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    return proc.returncode == 0, (tail[-1] if tail else "(no output)")


def main() -> int:
    files = sorted({m[1] for m in MUTATIONS}, key=str)
    baseline = {p: (p.read_text(), sha(p)) for p in files}

    ok, line = run_test("")
    print(f"BASELINE  whole file: {'GREEN' if ok else 'RED'}  |  {line}\n")
    if not ok:
        print("baseline is not green — refusing to retro-verify against a red tree")
        return 4

    decoration: list[str] = []
    print(f"{'#':>3}  {'result':<12} gate / reintroduced defect")
    print("-" * 100)

    for i, (label, path, old, new, node) in enumerate(MUTATIONS, 1):
        original, original_sha = baseline[path]
        if old not in original:
            print(f"{i:>3}  {'ANCHOR-LOST':<12} {label}")
            decoration.append(f"{label} (mutation anchor no longer matches source)")
            continue
        mutated = original.replace(old, new, 1)
        try:
            path.write_text(mutated)
            purge_bytecode(path)
            went_green, line = run_test(node)
            went_red = not went_green
        finally:
            # A concurrent writer (another agent in this worktree, an editor's
            # autosave) would otherwise be silently CLOBBERED by the restore —
            # this harness would destroy work it never read. Detect it, preserve
            # it, and say so.
            if path.read_text() != mutated:
                conflict = path.with_suffix(path.suffix + ".retro-conflict")
                conflict.write_text(path.read_text())
                path.write_text(original)
                purge_bytecode(path)
                print(
                    f"\nCONCURRENT EDIT to {path} during mutation {i}. The "
                    f"foreign content was saved to {conflict} and the original "
                    f"restored. Re-run once the tree is quiet."
                )
                return 5
            path.write_text(original)
            purge_bytecode(path)
            assert sha(path) == original_sha, f"RESTORE FAILED for {path}"

        status = "RED (good)" if went_red else "STAYED GREEN"
        print(f"{i:>3}  {status:<12} {label}")
        print(f"     {'':<12} -> {node}")
        print(f"     {'':<12}    {line}")
        if not went_red:
            decoration.append(f"{label} -> {node}")

    print("-" * 100)
    for path, (_, original_sha) in baseline.items():
        assert sha(path) == original_sha, f"tree not restored: {path}"
    print(f"tree restored byte-for-byte (sha256 verified on {len(files)} files)")

    ok, line = run_test("")
    print(f"AFTER     whole file: {'GREEN' if ok else 'RED'}  |  {line}")
    if not ok:
        return 4

    if decoration:
        print("\nDECORATION — these gates did not go red when their defect was reintroduced:")
        for d in decoration:
            print(f"  - {d}")
        return 1
    print(f"\nall {len(MUTATIONS)} reintroduced defects were caught; no decoration")
    return 0


if __name__ == "__main__":
    sys.exit(main())
