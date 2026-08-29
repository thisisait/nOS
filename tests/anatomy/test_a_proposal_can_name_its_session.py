"""The field Bone accepts must be one the client can send.

MEASURED 2026-08-29. `loop_proposals` holds 22 rows and **every one** has
`session_uuid IS NULL`. The ledger join was read as "the proposer never ran" —
true, but not the whole cause. Bone has accepted `session_uuid` since the join
landed (`files/anatomy/bone/looproutes.py:100` declares it, `:159` stores it),
and `nos-loop`, the only client that POSTs a proposal, never sent it. So even a
proposer that ran would have written a row that names no session.

Both halves were green: Bone's side is exercised, and the runner-side gate
(`test_every_proposal_names_a_session.py`) substitutes a stub for
`bin/run-agent.php` and asserts about the stub — honestly declared, and exactly
why nothing noticed that the wire between them carried no field.

This reads the CLI: the argument exists, and it reaches the payload. It does not
POST anything — the estate's ledger is not a fixture.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
CLI = REPO / "files/anatomy/bone/bin/nos-loop"
ROUTES = REPO / "files/anatomy/bone/looproutes.py"


def test_bone_still_accepts_the_field() -> None:
    """The premise. If Bone stops taking it, this whole file is the wrong shape."""
    src = ROUTES.read_text(encoding="utf-8")
    assert "session_uuid" in src, (
        "Bone no longer names session_uuid; the client sending it would be "
        "sending a field nobody stores"
    )


def test_the_client_offers_the_argument() -> None:
    out = subprocess.run([sys.executable, str(CLI), "propose", "--help"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "--session-uuid" in out.stdout, (
        "nos-loop propose cannot name a session; every proposal it records is "
        "untraceable to what it cost"
    )


def test_the_argument_reaches_the_payload() -> None:
    """Parsed, not grepped: a `--session-uuid` that is accepted and dropped
    before the POST would satisfy a substring search and change nothing."""
    tree = ast.parse(CLI.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "cmd_propose")
    posted = {
        k.value for call in ast.walk(fn)
        if isinstance(call, ast.Call)
        for arg in call.args
        if isinstance(arg, ast.Dict)
        for k in arg.keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }
    assert "session_uuid" in posted, (
        "cmd_propose builds its POST body without session_uuid; the flag would "
        "be accepted on the command line and dropped on the way to the wire"
    )
