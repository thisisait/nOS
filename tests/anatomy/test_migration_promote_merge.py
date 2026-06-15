"""Anatomy CI gate — B6 forge-merge → review_status='merged' (GATE 2, PULL model).

Pins the load-bearing pieces of the B6 promotion path so they can't drift apart:

  * tools/migration-pr.sh grows a --mark-merged path that invokes the Wing
    bridge bin/promote-migration.php, is mutually exclusive with --open-pr, and
    resolves the merge commit SHA (explicit or from the merged MR on the LOCAL
    forge — never GitHub).
  * bin/promote-migration.php is the ONLY writer of review_status='merged' +
    committed_sha, and emits migration_promoted (an event type the twin gate
    already whitelists in both events.py + EventRepository.php).
  * MigrationAuthoredRepository::markMerged() is the repo-side merged-writer;
    setReviewStatus() STILL hard-refuses 'merged' (Wing UI can never flip it —
    only the forge merge can, GATE 2).

The functional half (when php is on PATH) exercises promote-migration.php against
a throwaway SQLite DB through the chain-OFF default path: a draft/in_review row
flips to merged + committed_sha, a migration_promoted event lands with the right
FK + result_json, re-runs are idempotent (changed=0, no double-emit), and a
stale 'merged' row for the same (service,recipe) is delete-prior'd so the
UNIQUE(service,recipe_id,review_status) index never trips.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sqlite3
import subprocess
import textwrap

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
MIGRATION_PR = REPO / "tools" / "migration-pr.sh"
BRIDGE = REPO / "files" / "anatomy" / "wing" / "bin" / "promote-migration.php"
REPO_PHP = REPO / "files" / "anatomy" / "wing" / "app" / "Model" / "MigrationAuthoredRepository.php"


# ── Static contract gates ─────────────────────────────────────────────────────

def test_migration_pr_has_mark_merged_path():
    text = MIGRATION_PR.read_text()
    assert "--mark-merged" in text, "migration-pr.sh must grow the --mark-merged flip path"
    assert "MARK_MERGED" in text, "migration-pr.sh must parse a --mark-merged flag"
    assert "promote-migration.php" in text, "--mark-merged must invoke the Wing bridge bin/promote-migration.php"
    # mutually exclusive with --open-pr (open the MR, merge it, THEN mark merged)
    assert "mutually exclusive" in text, "--open-pr / --mark-merged must be mutually exclusive"
    # never GitHub: the merge SHA is read off the LOCAL forge port (the %2F-dodge)
    assert "127.0.0.1" in text, "the merge-SHA lookup must hit the LOCAL forge port, not the public domain"


def test_bridge_exists_and_emits_promoted_event():
    text = BRIDGE.read_text()
    assert "--mark-merged" in text, "bridge must accept --mark-merged"
    assert "'migration_promoted'" in text or '"migration_promoted"' in text, (
        "bridge must emit the migration_promoted event"
    )
    # the bridge is the merged-writer
    assert "review_status='merged'" in text, "bridge must flip review_status to merged"
    assert "committed_sha" in text, "bridge must stamp committed_sha"
    # audit-chain awareness — reuse the shared AuditChain algorithm (not a 4th copy)
    assert "AuditChain" in text, "bridge must reuse App\\Model\\AuditChain for the hash-chain"
    # delete-prior keeps the UNIQUE(service,recipe_id,review_status) index from tripping
    assert "review_status='merged' AND id<>" in text, (
        "bridge must delete-prior a stale merged row for the same (service,recipe)"
    )


def test_repo_markmerged_is_the_merged_writer():
    text = REPO_PHP.read_text()
    assert "function markMerged(" in text, "MigrationAuthoredRepository must own a markMerged() merged-writer"
    # markMerged sets merged
    assert "'review_status' => 'merged'" in text, "markMerged must set review_status='merged'"


def test_setreviewstatus_still_refuses_merged():
    """GATE 2: Wing's setReviewStatus() may ONLY ever write in_review / rejected.
    'merged' stays the forge-merge's exclusive write."""
    text = REPO_PHP.read_text()
    # the guard list in setReviewStatus
    assert "['in_review', 'rejected']" in text, (
        "setReviewStatus must restrict to in_review/rejected (merged is the forge's write)"
    )
    # and it must NOT contain 'merged' inside the in_array allow-list literal
    assert "['in_review', 'rejected', 'merged']" not in text, (
        "setReviewStatus must NOT allow 'merged' — that is GATE 2's exclusive path"
    )


# ── Functional gate (php-on-PATH) ─────────────────────────────────────────────

_SHIM = """<?php
declare(strict_types=1);
// chain-OFF default path needs no real AuditChain; stub it so the bridge's
// `require vendor/autoload.php` (vendor is built by the playbook) is bypassed.
spl_autoload_register(function ($class) {
    if ($class === 'App\\\\Model\\\\AuditChain') {
        eval('namespace App\\\\Model; final class AuditChain {'
            . ' const GENESIS="g";'
            . ' public static function chainKey(){return null;}'
            . ' public static function rowHash($p,$r,$k){return hash_hmac("sha256",$p,$k);} }');
    }
});
"""


def _seed_db(path: pathlib.Path) -> None:
    db = sqlite3.connect(str(path))
    db.executescript(textwrap.dedent("""
        CREATE TABLE migrations_authored (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          uuid TEXT NOT NULL UNIQUE, service TEXT NOT NULL, recipe_id TEXT NOT NULL,
          migration_id TEXT, plan_mode TEXT NOT NULL DEFAULT 'migration',
          from_version TEXT, to_version TEXT, severity TEXT, title TEXT NOT NULL,
          artifact_kind TEXT NOT NULL DEFAULT 'migration_yaml',
          artifact_path TEXT, forge TEXT, mr_url TEXT, forge_branch TEXT,
          committed_sha TEXT, review_status TEXT NOT NULL DEFAULT 'draft',
          rejected_reason TEXT, author_agent TEXT NOT NULL DEFAULT 'migration-author',
          session_uuid TEXT, actor_id TEXT, actor_action_id TEXT, applied_migration_id TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          UNIQUE (service, recipe_id, review_status)
        );
        CREATE TABLE events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, run_id TEXT NOT NULL,
          type TEXT NOT NULL, playbook TEXT, play TEXT, task TEXT, role TEXT, host TEXT,
          duration_ms INTEGER, changed INTEGER, result_json TEXT,
          migration_id TEXT, upgrade_id TEXT, patch_id TEXT, coexist_svc TEXT,
          source TEXT, actor_id TEXT, actor_action_id TEXT, acted_at TEXT,
          prev_hash TEXT, row_hash TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """))
    db.commit()
    db.close()


@pytest.mark.skipif(shutil.which("php") is None, reason="php not on PATH (bridge functional gate)")
def test_bridge_flips_merged_and_emits_once(tmp_path):
    php = shutil.which("php")
    data = tmp_path / "data"
    data.mkdir()
    dbp = data / "wing.db"
    _seed_db(dbp)

    # Seed: a stale merged row + a fresh in_review row for the SAME (service,recipe)
    db = sqlite3.connect(str(dbp))
    db.execute(
        "INSERT INTO migrations_authored (uuid,service,recipe_id,migration_id,title,review_status,committed_sha) "
        "VALUES ('old','postgresql','16-to-17','old-id','old','merged','oldsha')")
    db.execute(
        "INSERT INTO migrations_authored (uuid,service,recipe_id,migration_id,title,review_status,session_uuid,actor_action_id) "
        "VALUES ('new','postgresql','16-to-17','2026-06-15-pg','new','in_review','new','new')")
    db.commit()
    db.close()

    shim = tmp_path / "shim.php"
    shim.write_text(_SHIM)
    bridge = tmp_path / "promote.php"
    bridge.write_text(
        BRIDGE.read_text().replace(
            "require dirname(__DIR__) . '/vendor/autoload.php';",
            f"require '{shim}';",
        )
    )

    def run(*args):
        return subprocess.run([php, str(bridge), *args], capture_output=True, text=True)

    # First flip via the authoring uuid.
    r1 = run("--mark-merged", "--uuid=new", "--committed-sha=newsha", f"--data-dir={data}")
    assert r1.returncode == 0, r1.stderr
    assert "changed=1" in r1.stdout

    db = sqlite3.connect(str(dbp))
    db.row_factory = sqlite3.Row
    rows = list(db.execute("SELECT uuid,review_status,committed_sha FROM migrations_authored"))
    # the stale merged row was delete-prior'd; only the new merged row survives
    assert len(rows) == 1, "stale merged row must be delete-prior'd (UNIQUE-safe flip)"
    assert rows[0]["uuid"] == "new" and rows[0]["review_status"] == "merged"
    assert rows[0]["committed_sha"] == "newsha"

    evs = list(db.execute("SELECT type,migration_id,result_json,actor_action_id FROM events"))
    assert len(evs) == 1, "exactly one migration_promoted event on the first flip"
    assert evs[0]["type"] == "migration_promoted"
    assert evs[0]["migration_id"] == "2026-06-15-pg", "migration_id FK col carries the migration id"
    assert evs[0]["actor_action_id"] == "new", "actor_action_id reuses the authoring uuid (A14 lineage)"
    payload = json.loads(evs[0]["result_json"])
    assert payload["migration_uuid"] == "new" and payload["committed_sha"] == "newsha"
    db.close()

    # Idempotent re-run: re-stamps, does NOT re-emit.
    r2 = run("--mark-merged", "--uuid=new", "--committed-sha=newsha", f"--data-dir={data}")
    assert r2.returncode == 0, r2.stderr
    assert "changed=0" in r2.stdout
    db = sqlite3.connect(str(dbp))
    assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1, "no double-emit on idempotent re-run"
    db.close()


@pytest.mark.skipif(shutil.which("php") is None, reason="php not on PATH (bridge functional gate)")
def test_bridge_refuses_missing_row_and_bad_args(tmp_path):
    php = shutil.which("php")
    data = tmp_path / "data"
    data.mkdir()
    _seed_db(data / "wing.db")
    shim = tmp_path / "shim.php"
    shim.write_text(_SHIM)
    bridge = tmp_path / "promote.php"
    bridge.write_text(
        BRIDGE.read_text().replace(
            "require dirname(__DIR__) . '/vendor/autoload.php';",
            f"require '{shim}';",
        )
    )

    def run(*args):
        return subprocess.run([php, str(bridge), *args], capture_output=True, text=True)

    # missing --committed-sha → usage error (exit 2)
    assert run("--mark-merged", "--uuid=x", f"--data-dir={data}").returncode == 2
    # neither --uuid nor --migration-id → usage error (exit 2)
    assert run("--mark-merged", "--committed-sha=s", f"--data-dir={data}").returncode == 2
    # no matching row → exit 1
    assert run("--mark-merged", "--uuid=nope", "--committed-sha=s", f"--data-dir={data}").returncode == 1
