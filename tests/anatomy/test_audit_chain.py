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


def test_consent_table_migration_via_real_init_db(tmp_path):
    """Regression mirror of test_existing_db_migration_via_real_init_db, for the
    consent registry: run the REAL init-db.php against a PRE-EXISTING wing.db
    whose gdpr_consent table predates the active-consent partial index (and is
    missing withdrawn_at). idx_gdpr_consent_active references withdrawn_at, so it
    MUST be created in init-db.php AFTER the ALTER sweep adds the column — NOT in
    schema-extensions.sql (which would fail 'no such column: withdrawn_at' on
    every existing install, the exact class of bug the row_hash ordering taught)."""
    initdb = WING / "bin" / "init-db.php"
    db = tmp_path / "wing.db"
    con = sqlite3.connect(db)
    # OLD gdpr_consent schema — a plausible earlier shape WITHOUT withdrawn_at,
    # updated_at, and the active-consent partial index.
    con.execute(
        "CREATE TABLE gdpr_consent (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "subject_email TEXT NOT NULL, processing_id TEXT, activity TEXT NOT NULL, "
        "lawful_basis TEXT NOT NULL DEFAULT 'consent', tos_version_hash TEXT, "
        "source TEXT NOT NULL DEFAULT 'operator', granted_at TEXT NOT NULL, "
        "notes TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    con.execute(
        "INSERT INTO gdpr_consent (subject_email,activity,granted_at) "
        "VALUES ('a@b.test','legacy-activity','2026-01-01T00:00:00Z')"
    )
    con.commit()
    con.close()

    r = subprocess.run(["php", str(initdb), f"--data-dir={tmp_path}"], capture_output=True, text=True)
    assert r.returncode == 0, f"init-db must migrate an existing consent table cleanly: {r.stderr}"

    con = sqlite3.connect(db)
    cols = [c[1] for c in con.execute("PRAGMA table_info(gdpr_consent)")]
    idx = [i[1] for i in con.execute("PRAGMA index_list(gdpr_consent)")]
    assert "withdrawn_at" in cols, "ALTER sweep must add gdpr_consent.withdrawn_at"
    assert "updated_at" in cols, "ALTER sweep must add gdpr_consent.updated_at"
    assert "idx_gdpr_consent_active" in idx, (
        "active-consent partial index must be created post-sweep (it references "
        "the ALTER-added withdrawn_at)"
    )
    # the legacy row survives, still active (withdrawn_at NULL) and addressable
    n = con.execute(
        "UPDATE gdpr_consent SET withdrawn_at='2026-02-01T00:00:00Z' "
        "WHERE subject_email='a@b.test' AND activity='legacy-activity' AND withdrawn_at IS NULL"
    ).rowcount
    con.commit()
    con.close()
    assert n == 1, "the migrated legacy row must be withdrawable via the active path"


# ── late acknowledgement of a chain-off window (2026-08-19) ──────────────────
#
# MEASURED LIVE: a bare `php bin/run-agent.php` inherited no chain env and the
# librarian appended 37 unsigned rows (337463-337499) to a chained wing.db; the
# next signed segment (337500) starts at row 337462's hash, which nothing had
# recorded as an anchor, so `audit-chain-verify` exited 2 every night after.
# The tail-anchor path (`backfill-event-chain.php` bare) cannot repair this —
# by the time the gap is DISCOVERED, signed rows already follow it and the
# current tail is not the boundary. `--acknowledge-gap-before=<id>` is the
# operator act for exactly that; these gates pin that it verifies before it
# writes and that it can never authorize anything but a clean chain-off window.

def _gapped_db(tmp_path):
    """A DB in the live break's exact shape: signed, unsigned window, signed."""
    db = _fresh_db(tmp_path)
    _chain_env(db, on=True)
    W = _wing()
    W.insert_event({"ts": "t1", "run_id": "r", "type": "task_ok", "task": "signed1"})
    W.insert_event({"ts": "t2", "run_id": "r", "type": "task_ok", "task": "signed2"})
    _chain_env(db, on=False)
    W.insert_event({"ts": "t3", "run_id": "r", "type": "task_ok", "task": "gap1"})
    W.insert_event({"ts": "t4", "run_id": "r", "type": "task_ok", "task": "gap2"})
    _chain_env(db, on=True)
    W.insert_event({"ts": "t5", "run_id": "r", "type": "task_ok", "task": "signed3"})
    con = sqlite3.connect(db)
    resumed = con.execute(
        "SELECT MAX(id) FROM events WHERE row_hash IS NOT NULL").fetchone()[0]
    con.close()
    return db, resumed


def test_a_late_gap_breaks_verify_and_the_ack_repairs_the_boundary(tmp_path):
    db, resumed = _gapped_db(tmp_path)
    v = _php([str(VERIFY), f"--db={db}"])
    assert v.returncode == 2, (
        "positive control failed: the gapped DB should verify broken, or the "
        "acknowledgement below is repairing nothing"
    )

    a = _php([str(BACKFILL), f"--data-dir={db.parent}",
              f"--acknowledge-gap-before={resumed}"])
    assert a.returncode == 0, a.stderr
    assert "2 unsigned row(s)" in a.stdout, a.stdout
    assert "signs nothing" in a.stdout, (
        "the acknowledgement must say what it does NOT do — it authorizes the "
        "boundary, it never signs the window"
    )

    v = _php([str(VERIFY), f"--db={db}", "--json"])
    assert v.returncode == 0, f"verify still broken after the ack: {v.stdout}{v.stderr}"
    assert '"unsigned":2' in v.stdout.replace(" ", ""), (
        "the window must STAY visibly unsigned in the verify report — an ack "
        "that hides the count is a success marker written over history"
    )


def test_the_ack_refuses_an_unsigned_row_a_missing_row_and_an_empty_window(tmp_path):
    db, resumed = _gapped_db(tmp_path)
    con = sqlite3.connect(db)
    inside = con.execute(
        "SELECT MIN(id) FROM events WHERE row_hash IS NULL").fetchone()[0]
    first_signed = con.execute(
        "SELECT MIN(id) FROM events WHERE row_hash IS NOT NULL").fetchone()[0]
    con.close()

    r = _php([str(BACKFILL), f"--data-dir={db.parent}",
              f"--acknowledge-gap-before={inside}"])
    assert r.returncode == 2 and "UNSIGNED" in r.stderr, (
        "naming a row inside the window must refuse — the anchor would land "
        "mid-gap and authorize a boundary nobody reviewed"
    )

    r = _php([str(BACKFILL), f"--data-dir={db.parent}",
              "--acknowledge-gap-before=99999"])
    assert r.returncode == 2 and "no event row" in r.stderr

    r = _php([str(BACKFILL), f"--data-dir={db.parent}",
              f"--acknowledge-gap-before={first_signed + 1}"])
    assert r.returncode == 2 and "no unsigned window" in r.stderr, (
        "a contiguous chain has nothing to acknowledge; exit 0 here would let "
        "a cron'd ack mint anchors forever"
    )


def test_the_ack_refuses_a_window_that_is_not_a_clean_chain_off(tmp_path):
    """A signed row whose prev_hash does NOT point at the last signed row
    before it is possible tampering, and an anchor there would authorize it."""
    db, _ = _gapped_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO events (ts, run_id, type, prev_hash, row_hash) "
        "VALUES ('t9', 'r', 'task_ok', 'not-the-real-tail-hash', 'forged-hash')")
    con.commit()
    forged = con.execute("SELECT MAX(id) FROM events").fetchone()[0]
    con.close()
    r = _php([str(BACKFILL), f"--data-dir={db.parent}",
              f"--acknowledge-gap-before={forged}"])
    assert r.returncode == 2 and "tampering" in r.stderr, (
        f"the ack blessed a boundary whose prev_hash matches nothing: "
        f"{r.stdout}{r.stderr}"
    )


# ── writer type-stability + the verifier's strict int-retype (2026-08-19) ────
#
# MEASURED LIVE: events row 339176 (agent_tool_result, result_json arrived as
# int 0) was signed over canonical bytes `0`; SQLite's TEXT column hands back
# the string "0", which canonicalizes to `"0"`, so the nightly verify reported
# "content tampered" on a row nobody touched. Two fixes, both pinned here: the
# writers cast to string BEFORE signing (so this cannot recur), and the
# verifier retries exactly one strict variant for the historical rows.

def test_a_numeric_payload_field_signs_verifiably(tmp_path):
    """The Python writer casts before hashing: an int slipped into a TEXT
    field must produce a row the verifier can rebuild."""
    db = _fresh_db(tmp_path)
    _chain_env(db, on=True)
    W = _wing()
    W.insert_event({"ts": "t1", "run_id": "r", "type": "task_ok", "task": 0})
    v = _php([str(VERIFY), f"--db={db}", "--json"])
    assert v.returncode == 0, (
        f"an int-typed TEXT field broke the chain at write time: {v.stdout}{v.stderr}"
    )
    assert '"type_coerced":0' in v.stdout.replace(" ", ""), (
        "the WRITER must have stabilized the type — a coerced verify here "
        "means the retry is doing the writer's job on NEW rows"
    )


def _int_typed_row(db):
    """Reproduce the historical defect exactly: sign canonical(int 0), store
    the TEXT round-trip ('0'), exactly what the pre-fix writer did."""
    import hmac as _hmac
    import hashlib as _hashlib
    W = _wing()
    con = sqlite3.connect(db)
    prev = con.execute(
        "SELECT row_hash FROM events WHERE row_hash IS NOT NULL "
        "ORDER BY id DESC LIMIT 1").fetchone()
    prev = prev[0] if prev and prev[0] else W._GENESIS
    values = {"ts": "t2", "run_id": "r", "type": "task_ok", "result_json": 0}
    key = _hmac.new(SECRET.encode(), W._CHAIN_LABEL, _hashlib.sha256).hexdigest()
    row_hash = _hmac.new(
        key.encode(), (prev + W._canonical(values)).encode(), _hashlib.sha256
    ).hexdigest()
    con.execute(
        "INSERT INTO events (ts, run_id, type, result_json, prev_hash, row_hash) "
        "VALUES ('t2', 'r', 'task_ok', '0', ?, ?)", (prev, row_hash))
    con.commit()
    rid = con.execute("SELECT MAX(id) FROM events").fetchone()[0]
    con.close()
    return rid


def test_the_verifier_retries_the_historical_int_typing_strictly(tmp_path):
    db = _fresh_db(tmp_path)
    _chain_env(db, on=True)
    W = _wing()
    W.insert_event({"ts": "t1", "run_id": "r", "type": "task_ok", "task": "a"})
    _int_typed_row(db)
    W.insert_event({"ts": "t3", "run_id": "r", "type": "task_ok", "task": "b"})

    v = _php([str(VERIFY), f"--db={db}", "--json"])
    assert v.returncode == 0, (
        f"the historical int-typed row still reads as tampered: {v.stdout}{v.stderr}"
    )
    assert '"type_coerced":1' in v.stdout.replace(" ", ""), (
        "the retry must be COUNTED, not silent — a coerced row the report "
        "hides is a variant acceptance nobody reviews"
    )


def test_the_retype_retry_is_round_trip_strict(tmp_path):
    """'00' coerces to int 0 under a loose cast and would collide with the
    signed bytes; the strict round-trip must refuse it as tampering."""
    db = _fresh_db(tmp_path)
    _chain_env(db, on=True)
    W = _wing()
    W.insert_event({"ts": "t1", "run_id": "r", "type": "task_ok", "task": "a"})
    rid = _int_typed_row(db)
    con = sqlite3.connect(db)
    # WORM permits only actor_action_id updates on chained rows — simulate the
    # tamper the way an attacker with file access would, via a rebuilt row.
    try:
        con.execute("UPDATE events SET result_json='00' WHERE id=?", (rid,))
        con.commit()
    except (sqlite3.OperationalError, sqlite3.IntegrityError):
        # WORM refused the in-place edit (good, and itself a positive control);
        # drop the trigger the way the forgery test above does — offline
        # tampering is detected, not prevented.
        trig = con.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE '%worm%'"
        ).fetchall()
        for (name,) in trig:
            con.execute(f"DROP TRIGGER {name}")
        con.execute("UPDATE events SET result_json='00' WHERE id=?", (rid,))
        con.commit()
    con.close()
    v = _php([str(VERIFY), f"--db={db}", "--json"])
    assert v.returncode == 2 and "tampered" in v.stdout + v.stderr, (
        f"'00' was accepted by the retype retry — the round-trip guard is "
        f"gone and the retry is now a second canonicalization: {v.stdout}"
    )
