"""Anatomy CI gate — tamper-evident audit hash-chain (gov-readiness P1).

Exercises the REAL seams against throwaway SQLite DBs built from the live
schema-extensions.sql:
  - cross-language canonical + row_hash parity (Bone Python writer vs the PHP
    AuditChain the verifier uses) — the load-bearing invariant;
  - a Python-written chain verifies (verify-audit-chain.php exit 0);
  - WORM triggers: actor_action_id-only UPDATE allowed, content UPDATE blocked,
    DELETE blocked while locked, legacy NULL-row_hash rows freely mutable;
  - offline tampering is DETECTED (verify exit 2);
  - retention purge re-anchors (chain still verifies, last_purged_hash set);
  - chain OFF->ON toggle verifies once the anchor is recorded;
  - flag-off is a no-op (row_hash NULL, verify all-unsigned exit 0).

Skipped when php is unavailable (Woodpecker python:3.13-slim). The GitHub
Actions pytest job has php 8.3, so it BINDS there.
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
SCHEMA = WING / "db" / "schema-extensions.sql"
AUDITCHAIN = WING / "app" / "Model" / "AuditChain.php"
VERIFY = WING / "bin" / "verify-audit-chain.php"
BACKFILL = WING / "bin" / "backfill-event-chain.php"
PURGE = WING / "bin" / "purge-events.php"
SECRET = "audit-chain-test-secret-0123456789"

pytestmark = pytest.mark.skipif(shutil.which("php") is None, reason="php not installed")

sys.path.insert(0, str(REPO / "files" / "anatomy" / "bone"))


@pytest.fixture(autouse=True)
def _isolate_env():
    """Save/restore the chain env vars so this module's direct os.environ writes
    never leak into other tests in the same pytest process (e.g. the bone
    callback suite, which would otherwise see a stale WING_AUDIT_CHAIN_ENABLED)."""
    keys = ("WING_DB_PATH", "WING_AUDIT_CHAIN_ENABLED", "WING_EVENTS_HMAC_SECRET")
    saved = {k: os.environ.get(k) for k in keys}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _wing():
    """Import the Bone wing client. insert_event reads env at CALL time, so no
    reload is needed between env changes — and reloading would mint a fresh
    WingDBNotReady class, breaking `is`-identity for modules (events.py) that
    imported it earlier in the session."""
    import clients.wing as W
    return W


def _fresh_db(tmp_path) -> pathlib.Path:
    # Build via the REAL init-db.php (not raw schema-extensions.sql) so the test
    # schema matches production EXACTLY — including the WORM triggers + chain
    # index that init-db creates AFTER its ALTER sweep. Applying schema-extensions
    # alone used to hide the existing-DB migration bug (no triggers => no WORM).
    r = subprocess.run(
        ["php", str(WING / "bin" / "init-db.php"), f"--data-dir={tmp_path}"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"init-db failed building test DB: {r.stderr}"
    return tmp_path / "wing.db"


def _php(args, secret=SECRET):
    env = dict(os.environ)
    env["WING_EVENTS_HMAC_SECRET"] = secret
    env["AC"] = str(AUDITCHAIN)
    return subprocess.run(["php", *args], capture_output=True, text=True, env=env)


def _chain_env(db, on=True, secret=SECRET):
    os.environ["WING_DB_PATH"] = str(db)
    os.environ["WING_EVENTS_HMAC_SECRET"] = secret
    os.environ["WING_AUDIT_CHAIN_ENABLED"] = "1" if on else ""


def test_cross_language_canonical_and_rowhash_parity(tmp_path):
    W = _wing()
    vec = {
        "ts": "2026-05-31T00:00:00Z", "run_id": "r1", "type": "task_ok",
        "playbook": "main.yml", "play": "p", "task": "t/slash & <html>",
        "role": "r", "host": "h", "duration_ms": 1234, "changed": 1,
        "result_json": json.dumps({"a": "b/c", "u": "č"}),
        "migration_id": None, "upgrade_id": None, "patch_id": None,
        "coexist_svc": None, "source": "callback", "actor_id": "aid",
        "acted_at": "2026-05-31T00:00:00Z",
    }
    prev = W._GENESIS
    key = hmac.new(SECRET.encode(), W._CHAIN_LABEL, hashlib.sha256).hexdigest()
    py_canon = W._canonical(vec)
    py_hash = hmac.new(key.encode(), (prev + py_canon).encode(), hashlib.sha256).hexdigest()

    harness = tmp_path / "probe.php"
    harness.write_text(
        "<?php declare(strict_types=1); require getenv('AC');\n"
        "$in = json_decode(file_get_contents('php://stdin'), true);\n"
        "$k = \\App\\Model\\AuditChain::chainKey();\n"
        "echo \\App\\Model\\AuditChain::canonical($in['row']) . \"\\n\";\n"
        "echo \\App\\Model\\AuditChain::rowHash($in['prev'], $in['row'], $k) . \"\\n\";\n"
    )
    r = subprocess.run(
        ["php", str(harness)], capture_output=True, text=True,
        env={**os.environ, "WING_EVENTS_HMAC_SECRET": SECRET, "AC": str(AUDITCHAIN)},
        input=json.dumps({"row": vec, "prev": prev}),
    )
    assert r.returncode == 0, r.stderr
    php_canon, php_hash = r.stdout.strip().split("\n")
    assert php_canon == py_canon, "canonical bytes diverge across PHP/Python"
    assert php_hash == py_hash, "row_hash diverges across PHP/Python"


def test_python_written_chain_verifies(tmp_path):
    db = _fresh_db(tmp_path)
    _chain_env(db, on=True)
    W = _wing()
    W.insert_event({"ts": "t1", "run_id": "r", "type": "task_ok", "task": "a",
                    "result": {"x": 1}, "changed": True, "duration_ms": 5})
    W.insert_event({"ts": "t2", "run_id": "r", "type": "task_ok", "task": "b"})
    v = _php([str(VERIFY), f"--db={db}"])
    assert v.returncode == 0, v.stderr
    assert "CHAIN-OK" in v.stdout


def test_worm_allows_actor_action_id_blocks_content_and_delete(tmp_path):
    db = _fresh_db(tmp_path)
    _chain_env(db, on=True)
    W = _wing()
    W.insert_event({"ts": "t1", "run_id": "r", "type": "task_ok", "task": "a"})
    con = sqlite3.connect(db)
    # actor_action_id-only UPDATE: ALLOWED
    con.execute("UPDATE events SET actor_action_id='aa1' WHERE id=1")
    con.commit()
    # content UPDATE: BLOCKED (RAISE(ABORT) -> sqlite3.IntegrityError)
    with pytest.raises(sqlite3.Error):
        con.execute("UPDATE events SET task='TAMPER' WHERE id=1")
        con.commit()
    con.rollback()
    # DELETE while locked: BLOCKED
    with pytest.raises(sqlite3.Error):
        con.execute("DELETE FROM events WHERE id=1")
        con.commit()
    con.rollback()
    con.close()
    # chain still intact after the allowed actor_action_id stamp
    v = _php([str(VERIFY), f"--db={db}"])
    assert v.returncode == 0, v.stderr


def test_legacy_null_rows_freely_mutable(tmp_path):
    db = _fresh_db(tmp_path)
    # chain OFF insert -> row_hash NULL
    _chain_env(db, on=False)
    W = _wing()
    W.insert_event({"ts": "t1", "run_id": "r", "type": "task_ok", "task": "a"})
    con = sqlite3.connect(db)
    con.execute("UPDATE events SET task='edited' WHERE id=1")  # triggers dormant on NULL row_hash
    con.execute("DELETE FROM events WHERE id=1")
    con.commit()
    con.close()


def test_offline_tamper_is_detected(tmp_path):
    db = _fresh_db(tmp_path)
    _chain_env(db, on=True)
    W = _wing()
    W.insert_event({"ts": "t1", "run_id": "r", "type": "task_ok", "task": "a"})
    W.insert_event({"ts": "t2", "run_id": "r", "type": "task_ok", "task": "b"})
    con = sqlite3.connect(db)
    con.execute("DROP TRIGGER events_worm_update")  # simulate an offline attacker
    con.execute("UPDATE events SET task='HACKED' WHERE id=1")
    con.commit()
    con.close()
    v = _php([str(VERIFY), f"--db={db}"])
    assert v.returncode == 2, "tampered chain must verify as BROKEN"


def test_purge_reanchors_and_chain_still_verifies(tmp_path):
    db = _fresh_db(tmp_path)
    _chain_env(db, on=True)
    W = _wing()
    for i in range(3):
        W.insert_event({"ts": "2024-01-01T00:00:00Z", "run_id": "r", "type": "task_ok", "task": f"old{i}"})
    for i in range(2):
        W.insert_event({"ts": "2026-05-31T00:00:00Z", "run_id": "r", "type": "task_ok", "task": f"new{i}"})
    p = _php([str(PURGE), f"--db={db}", "--older-than-days=365"])
    assert p.returncode == 0, p.stderr
    v = _php([str(VERIFY), f"--db={db}"])
    assert v.returncode == 0, v.stderr
    con = sqlite3.connect(db)
    lp = con.execute("SELECT v FROM audit_chain_meta WHERE k='last_purged_hash'").fetchone()
    con.close()
    assert lp and lp[0], "purge must record last_purged_hash"


def test_legacy_db_without_chain_surface_purges_unchanged(tmp_path):
    """FIX-B1: a DB with no audit_chain_meta / row_hash falls through to the
    original byte-identical DELETE."""
    db = tmp_path / "legacy.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "ts TEXT NOT NULL, run_id TEXT NOT NULL, type TEXT NOT NULL)")
    con.executemany("INSERT INTO events (ts, run_id, type) VALUES (?, 'r', 'task_ok')",
                    [("2024-01-01T00:00:00Z",), ("2024-01-01T00:00:00Z",)])
    con.commit()
    con.close()
    p = _php([str(PURGE), f"--db={db}", "--older-than-days=365"])
    assert p.returncode == 0, p.stderr
    assert "Purged 2 events" in p.stdout


def test_toggle_off_then_on_verifies(tmp_path):
    db = _fresh_db(tmp_path)
    _chain_env(db, on=True)
    W = _wing()
    W.insert_event({"ts": "t1", "run_id": "r", "type": "task_ok", "task": "chained1"})
    _chain_env(db, on=False)
    W.insert_event({"ts": "t2", "run_id": "r", "type": "task_ok", "task": "unsigned"})
    b = _php([str(BACKFILL), f"--data-dir={db.parent}"])
    assert b.returncode == 0, b.stderr
    _chain_env(db, on=True)
    W.insert_event({"ts": "t3", "run_id": "r", "type": "task_ok", "task": "chained2"})
    v = _php([str(VERIFY), f"--db={db}"])
    assert v.returncode == 0, v.stderr


def test_existing_db_migration_via_real_init_db(tmp_path):
    """Regression: run the REAL init-db.php against a PRE-EXISTING wing.db whose
    events table predates the chain columns (no row_hash). The WORM triggers +
    idx_events_row_hash must be created AFTER the ALTER sweep adds row_hash, not
    inside schema-extensions.sql (which would fail 'no such column: row_hash' on
    every existing install — the bug that broke a live playbook run)."""
    initdb = WING / "bin" / "init-db.php"
    db = tmp_path / "wing.db"
    con = sqlite3.connect(db)
    # OLD events schema — exactly the pre-chain column set, no row_hash/prev_hash.
    con.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
        "run_id TEXT NOT NULL, type TEXT NOT NULL, playbook TEXT, play TEXT, task TEXT, "
        "role TEXT, host TEXT, duration_ms INTEGER, changed INTEGER, result_json TEXT, "
        "migration_id TEXT, upgrade_id TEXT, patch_id TEXT, coexist_svc TEXT, source TEXT, "
        "actor_id TEXT, actor_action_id TEXT, acted_at TEXT, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    con.execute("INSERT INTO events (ts,run_id,type,task) VALUES ('2026-01-01T00:00:00Z','r','task_ok','legacy')")
    con.commit()
    con.close()

    r = subprocess.run(["php", str(initdb), f"--data-dir={tmp_path}"], capture_output=True, text=True)
    assert r.returncode == 0, f"init-db must migrate an existing DB cleanly: {r.stderr}"

    con = sqlite3.connect(db)
    cols = [c[1] for c in con.execute("PRAGMA table_info(events)")]
    trg = [t[0] for t in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")]
    assert "row_hash" in cols and "prev_hash" in cols, "ALTER sweep must add chain columns"
    assert "events_worm_update" in trg and "events_worm_delete" in trg, "WORM triggers must be created post-sweep"
    # the pre-existing legacy row has NULL row_hash -> triggers dormant -> still mutable
    con.execute("UPDATE events SET task='edited' WHERE id=1")
    con.commit()
    con.close()


def test_verify_writes_verdict_when_flag_set(tmp_path):
    """--write-verdict caches the verdict in audit_chain_meta (header badge)."""
    db = _fresh_db(tmp_path)
    _chain_env(db, on=True)
    W = _wing()
    W.insert_event({"ts": "t1", "run_id": "r", "type": "task_ok", "task": "a"})
    v = _php([str(VERIFY), f"--db={db}", "--write-verdict"])
    assert v.returncode == 0, v.stderr
    con = sqlite3.connect(db)
    ok = con.execute("SELECT v FROM audit_chain_meta WHERE k='last_verify_ok'").fetchone()
    at = con.execute("SELECT v FROM audit_chain_meta WHERE k='last_verify_at'").fetchone()
    con.close()
    assert ok and ok[0] == "1", "intact chain must cache ok='1'"
    assert at and at[0], "last_verify_at must be set"
    # tamper -> exit 2, verdict flips to '0'
    con = sqlite3.connect(db)
    con.execute("DROP TRIGGER events_worm_update")
    con.execute("UPDATE events SET task='X' WHERE id=1")
    con.commit()
    con.close()
    v2 = _php([str(VERIFY), f"--db={db}", "--write-verdict"])
    assert v2.returncode == 2
    con = sqlite3.connect(db)
    ok2 = con.execute("SELECT v FROM audit_chain_meta WHERE k='last_verify_ok'").fetchone()
    con.close()
    assert ok2 and ok2[0] == "0", "tampered chain must cache ok='0'"


def test_verify_without_flag_leaves_verdict_untouched(tmp_path):
    """Backward-compat: plain --db= (no --write-verdict) writes no verdict."""
    db = _fresh_db(tmp_path)
    _chain_env(db, on=True)
    W = _wing()
    W.insert_event({"ts": "t1", "run_id": "r", "type": "task_ok", "task": "a"})
    v = _php([str(VERIFY), f"--db={db}"])
    assert v.returncode == 0
    con = sqlite3.connect(db)
    ok = con.execute("SELECT v FROM audit_chain_meta WHERE k='last_verify_ok'").fetchone()
    con.close()
    assert ok is None, "plain verify must not touch the verdict keys"


def test_flag_off_is_noop(tmp_path):
    db = _fresh_db(tmp_path)
    _chain_env(db, on=False)
    W = _wing()
    W.insert_event({"ts": "t1", "run_id": "r", "type": "task_ok", "task": "plain"})
    con = sqlite3.connect(db)
    rh = con.execute("SELECT row_hash FROM events").fetchone()[0]
    con.close()
    assert rh is None, "chain-off insert must leave row_hash NULL"
    v = _php([str(VERIFY), f"--db={db}"])
    assert v.returncode == 0
