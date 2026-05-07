"""Wing API token mint/revoke helpers (A13.6).

The production token contract is fully owned by ``files/anatomy/wing/bin/
provision-token.php`` — it computes the SHA-256 hash, performs the
DELETE-by-name + INSERT UPSERT, and emits ``Created``/``Updated`` lines.
Reusing it via subprocess here means:
  * one source of truth for the hash algorithm
  * tests stay green if the token storage scheme changes
  * the audit trail (``api_tokens.created_by`` column) is consistent

For revocation we go DIRECT to SQLite — provision-token.php has no delete
mode and the test path is allowed to bypass the PHP layer because:
  * we know the schema (single table, single row keyed by ``name``)
  * we just minted the row a moment ago, so we own it unambiguously
  * keeping a trivial DELETE in Python keeps teardown synchronous + fast

Test tokens use ``name=tester:e2e:<username>`` so they sort cleanly in
``api_tokens`` and never collide with operator-provisioned tokens.
"""

from __future__ import annotations

import os
import secrets as _secrets
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path


def _wing_app_dir() -> Path:
    """Where ``provision-token.php`` lives. Repo-relative — works from any cwd."""
    here = Path(__file__).resolve()
    # tests/e2e/lib/wing_token_admin.py → repo root → files/anatomy/wing/
    repo_root = here.parents[3]
    return repo_root / "files" / "anatomy" / "wing"


def _wing_db_path() -> Path:
    """Production wing.db location. Override via ``WING_DATA_DIR`` env."""
    data_dir = os.environ.get("WING_DATA_DIR") or os.path.expanduser("~/wing/data")
    return Path(data_dir) / "wing.db"


@dataclass
class WingToken:
    name: str       # e.g. "tester:e2e:nos-tester-e2e-a1b2c3d4"
    plaintext: str  # the bearer token the test sends as Authorization: Bearer ...
    php_output: str = ""


def mint_token(token_name: str, plaintext: str | None = None) -> WingToken:
    """Provision a Wing API token for the test session.

    Returns a ``WingToken`` whose ``plaintext`` field is the bearer string —
    keep it in memory only. The DB stores SHA-256(plaintext).
    """
    if plaintext is None:
        plaintext = _secrets.token_urlsafe(32)

    db_path = _wing_db_path()
    if not db_path.exists():
        raise FileNotFoundError(
            f"wing.db not found at {db_path} — run the playbook first or set "
            "WING_DATA_DIR to point at a populated install."
        )

    proc = subprocess.run(
        [
            "php", "bin/provision-token.php",
            f"--db={db_path}",
            f"--token={plaintext}",
            f"--name={token_name}",
        ],
        cwd=_wing_app_dir(),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"provision-token.php failed (rc={proc.returncode}): "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
    return WingToken(name=token_name, plaintext=plaintext, php_output=proc.stdout.strip())


def revoke_token(token_name: str) -> int:
    """Delete the ``api_tokens`` row by name. Returns rows-deleted count."""
    db_path = _wing_db_path()
    if not db_path.exists():
        return 0
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.execute("DELETE FROM api_tokens WHERE name = ?", (token_name,))
        con.commit()
        return cur.rowcount
    finally:
        con.close()


def list_tokens_by_prefix(name_prefix: str) -> list[str]:
    """List token names matching a prefix — for orphan-sweep CI gates."""
    db_path = _wing_db_path()
    if not db_path.exists():
        return []
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            "SELECT name FROM api_tokens WHERE name LIKE ? ORDER BY name",
            (name_prefix + "%",),
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()
