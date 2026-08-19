"""`tools/identity-status.py` reports the account roster and can never change it.

Same doctrine as test_the_red_reader_only_reads.py, same reason: the obvious
next thought — "while it is looking, it could delete the 65 orphaned
nos-tester-e2e-* accounts it found" — is exactly the addition that must be
refused. A reader that repairs will eventually certify its own repair.
Reconciliation is the playbook's job (auditable, tagged, reviewable);
deletion of live accounts is an operator act.

Pinned:
1. GET only — the module contains no write-capable HTTP method and no
   subprocess. urllib is the whole client.
2. Exit 0 whatever it finds — a finding is a report, not a failure.
3. Absence is UNKNOWN, never green — an unreadable realm prints `?`, and
   "no data" is never rendered as "no problem".
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools/identity-status.py"

WRITE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


def test_the_tool_exists_and_is_executable():
    """Positive control — a renamed tool makes every check below vacuous."""
    assert TOOL.is_file(), "tools/identity-status.py is gone"
    assert TOOL.stat().st_mode & 0o111, "tools/identity-status.py lost +x"


def test_every_http_request_is_a_get_and_nothing_shells_out():
    tree = ast.parse(TOOL.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = {a.name for a in node.names} | {
                getattr(node, "module", None) or ""
            }
            assert "subprocess" not in names, (
                "the reader imports subprocess — a reader holds no verbs"
            )
        if isinstance(node, ast.Call):
            func = ast.unparse(node.func)
            assert "subprocess" not in func, (
                f"the reader shells out ({func}) — a reader holds no verbs"
            )
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value not in WRITE_METHODS, (
                f"write-capable HTTP method {node.value!r} appeared in the "
                "reader — reconciliation belongs to the playbook"
            )


def test_it_exits_zero_and_reports_absence_as_unknown():
    proc = subprocess.run(
        [sys.executable, str(TOOL)], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, (
        f"the reader exited {proc.returncode}: a finding is a report, not a "
        f"failure\n{proc.stderr}"
    )
    # On any host at least one line must exist; on a host with no realms
    # reachable the output must SAY unknown rather than staying quiet.
    assert proc.stdout.strip(), "the reader said nothing at all"
    if "unreadable" in proc.stdout:
        assert "?" in proc.stdout, (
            "an unreadable realm is not marked '?' — absence rendered as fine"
        )
