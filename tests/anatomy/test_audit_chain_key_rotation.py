"""The chain key can be rotated without throwing away the history it signed.

WHY THIS EXISTS. `AuditChain::chainKey()` derives from
`WING_EVENTS_HMAC_SECRET`, so changing that secret used to invalidate every row
ever signed — 140,758 on this estate. A credential that cannot be rotated is
one you keep forever, and on 2026-08-05 that one leaked into a public commit
(a live value pasted into a test fixture). The choice was "rotate and lose the
tamper-evident log" or "keep a published key". Neither is acceptable, so the
third option got built.

THE DESIGN, and it needed no schema change because the seam already existed.
The verifier already walks SEGMENTS and already refuses a segment that does not
start at GENESIS or a recorded anchor. So:

    rotation == start a new segment
    a key change is allowed exactly where a segment change is allowed

Each segment elects the ring member that verifies its FIRST row, and that
member must then verify every remaining row of the segment. A leaked retired
key therefore cannot re-sign a suffix: the forged rows sit mid-segment, where
the elected key is the only one accepted.

WHAT IT DOES NOT DO. The class docblock's threat model is unchanged — an
attacker who can write wing.db and read the CURRENT secret can recompute
everything, anchors included. This restores verifiability across a rotation,
which is what was lost. It does not make a tamper-evident log tamper-proof.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
VERIFY = WING / "bin" / "verify-audit-chain.php"

OLD_SECRET = "rotation-test-secret-OLD-0123456789"
NEW_SECRET = "rotation-test-secret-NEW-9876543210"
CHAIN_LABEL = b"wing-events-chain-v1"

pytestmark = pytest.mark.skipif(shutil.which("php") is None, reason="php not installed")

sys.path.insert(0, str(REPO / "files" / "anatomy" / "bone"))


@pytest.fixture(autouse=True)
def _isolate_env():
    keys = ("WING_DB_PATH", "WING_AUDIT_CHAIN_ENABLED",
            "WING_EVENTS_HMAC_SECRET", "WING_EVENTS_HMAC_SECRET_RETIRED")
    saved = {k: os.environ.get(k) for k in keys}
    yield
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def _fresh_db(tmp_path) -> pathlib.Path:
    r = subprocess.run(
        ["php", str(WING / "bin" / "init-db.php"), f"--data-dir={tmp_path}"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"init-db failed: {r.stderr}"
    return tmp_path / "wing.db"


def _write_events(db: pathlib.Path, secret: str, count: int, tag: str) -> None:
    """Write through the REAL Bone writer, so the rows are signed the way
    production signs them rather than the way this test imagines."""
    os.environ["WING_DB_PATH"] = str(db)
    os.environ["WING_EVENTS_HMAC_SECRET"] = secret
    os.environ["WING_AUDIT_CHAIN_ENABLED"] = "1"
    import clients.wing as W
    for i in range(count):
        W.insert_event({"ts": f"2026-08-06T0{i}:00:00Z", "type": f"{tag}.{i}",
                        "run_id": f"run-{tag}", "source": "test"})


def _head_hash(db: pathlib.Path) -> str:
    con = sqlite3.connect(str(db))
    try:
        row = con.execute(
            "SELECT row_hash FROM events WHERE row_hash IS NOT NULL "
            "ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        con.close()
    assert row and row[0], "no signed rows to anchor"
    return row[0]


def _record_anchor(db: pathlib.Path, head: str) -> None:
    """What the rotation procedure does: seal the current head as an authorized
    segment start, so the next row may legitimately open a new segment."""
    con = sqlite3.connect(str(db))
    try:
        con.execute("INSERT OR REPLACE INTO audit_chain_meta (k, v) VALUES (?, ?)",
                    (f"chain_segment_anchor_{head}", head))
        con.commit()
    finally:
        con.close()


def _verify(db: pathlib.Path, secret: str, retired: str = "") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["WING_DB_PATH"] = str(db)
    env["WING_EVENTS_HMAC_SECRET"] = secret
    env["WING_EVENTS_HMAC_SECRET_RETIRED"] = retired
    return subprocess.run(["php", str(VERIFY), f"--db={db}"],
                          capture_output=True, text=True, env=env)


def _rotated_db(tmp_path) -> pathlib.Path:
    db = _fresh_db(tmp_path)
    _write_events(db, OLD_SECRET, 3, "before")
    _record_anchor(db, _head_hash(db))
    _write_events(db, NEW_SECRET, 3, "after")
    return db


# ── control ─────────────────────────────────────────────────────────────────

def test_an_unrotated_chain_still_verifies(tmp_path):
    """Counterweight: without this, a verifier hard-wired to fail would satisfy
    every negative case below."""
    db = _fresh_db(tmp_path)
    _write_events(db, OLD_SECRET, 3, "plain")
    result = _verify(db, OLD_SECRET)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


# ── the property that was missing ───────────────────────────────────────────

def test_history_signed_by_the_retired_key_still_verifies(tmp_path):
    db = _rotated_db(tmp_path)
    result = _verify(db, NEW_SECRET, retired=OLD_SECRET)
    assert result.returncode == 0, (
        "a rotated chain does not verify with the retired key on the ring — "
        f"rotation still destroys the audit history.\n{result.stdout}\n{result.stderr}"
    )


def test_without_the_retired_key_the_old_segment_fails(tmp_path):
    """The measurement that motivated the ring, kept as a test.

    This is what rotating WITHOUT a ring does to 140,758 rows.
    """
    db = _rotated_db(tmp_path)
    result = _verify(db, NEW_SECRET)
    assert result.returncode != 0, (
        "the pre-rotation segment verified under a key that never signed it — "
        "the ring is accepting anything, which is worse than losing history"
    )


# ── the property that makes the ring safe ───────────────────────────────────

def test_a_retired_key_cannot_sign_new_history(tmp_path):
    """A leaked retired key must not let an attacker extend the chain.

    The forged row sits MID-SEGMENT, where the elected key is the only one
    accepted — so the ring buys verifiability of the past without granting the
    old key any authority over the present.
    """
    db = _rotated_db(tmp_path)
    head = _head_hash(db)

    # Craft a row signed with the RETIRED key, chained onto the current head.
    row = {"ts": "2026-08-06T23:00:00Z", "run_id": "forged", "type": "forged.row",
           "playbook": None, "play": None, "task": None, "role": None, "host": None,
           "duration_ms": None, "changed": None, "result_json": None,
           "migration_id": None, "upgrade_id": None, "patch_id": None,
           "coexist_svc": None, "source": "test", "actor_id": None,
           "acted_at": "2026-08-06T23:00:00Z"}
    canon = json.dumps(row, separators=(",", ":"), ensure_ascii=False)
    old_key = hmac.new(OLD_SECRET.encode(), CHAIN_LABEL, hashlib.sha256).hexdigest()
    forged = hmac.new(old_key.encode(), (head + canon).encode(), hashlib.sha256).hexdigest()

    con = sqlite3.connect(str(db))
    try:
        con.execute(
            "INSERT INTO events (ts, run_id, type, source, acted_at, prev_hash, row_hash) "
            "VALUES (?,?,?,?,?,?,?)",
            (row["ts"], row["run_id"], row["type"], row["source"], row["acted_at"],
             head, forged))
        con.commit()
    finally:
        con.close()

    result = _verify(db, NEW_SECRET, retired=OLD_SECRET)
    assert result.returncode != 0, (
        "a row signed with the RETIRED key was accepted mid-segment — the ring "
        "has handed the leaked key authority to write new history"
    )


def test_the_ring_is_ordered_current_first(tmp_path):
    """The writer must never reach for a retired key."""
    env = dict(os.environ)
    env["WING_EVENTS_HMAC_SECRET"] = NEW_SECRET
    env["WING_EVENTS_HMAC_SECRET_RETIRED"] = f"{OLD_SECRET}, {OLD_SECRET}"
    probe = (
        'require "' + str(WING / "app" / "Model" / "AuditChain.php") + '";'
        'echo json_encode(["one" => \\App\\Model\\AuditChain::chainKey(),'
        '"ring" => \\App\\Model\\AuditChain::chainKeys()]);'
    )
    result = subprocess.run(["php", "-r", probe], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["ring"][0] == data["one"], "chainKeys() does not lead with the writer's key"
    # duplicates collapse — a retired list that repeats a value must not grow
    assert len(data["ring"]) == 2, f"ring did not dedupe: {len(data['ring'])} entries"
