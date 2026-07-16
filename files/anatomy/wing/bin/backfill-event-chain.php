#!/usr/bin/env php
<?php

declare(strict_types=1);

/**
 * Wing — record the audit-chain enable / re-enable anchor.
 *
 * Usage:
 *   php bin/backfill-event-chain.php --data-dir=<dir>
 *
 * Does NOT retroactively sign rows we never witnessed (that would be forging an
 * audit trail). It records the CURRENT chain tail as a segment anchor so the
 * verifier accepts the boundary after a chain OFF->ON toggle (an unsigned/NULL
 * run between two signed segments). MUST run after each flag OFF->ON toggle;
 * roles/pazny.wing/tasks/post.yml does this when wing_audit_chain_enabled is on.
 *
 * Idempotent: prints 'now holds 0' when the recorded anchor already matches the
 * current tail (post.yml keys changed_when on that). Exit 0 always (best-effort).
 */

const GENESIS = 'nos-audit-chain-genesis-v1';

$dir = null;
foreach ($argv as $a) {
    if (str_starts_with($a, '--data-dir=')) {
        $dir = substr($a, 11);
    }
}
$base = $dir ?: (getenv('WING_DATA_DIR') ?: (getenv('HOME') . '/wing/app/data'));
$db = $base . '/wing.db';
if (!is_file($db)) {
    fwrite(STDERR, "DB not found: {$db}\n");
    echo "now holds 0 rows to backfill\n";
    exit(0);
}

$s = new SQLite3($db, SQLITE3_OPEN_READWRITE);
$s->busyTimeout(5000); // WAL is on-file; per-conn timeout prevents 'database is locked' under concurrent writers (scout HIGH 2026-07-15)
$s->enableExceptions(true);

// The next chained insert will set prev_hash = this tail (or GENESIS if none).
// Record it as a segment anchor so a re-enable after a NULL window verifies.
$tail = $s->querySingle("SELECT row_hash FROM events WHERE row_hash IS NOT NULL ORDER BY id DESC LIMIT 1");
$anchor = ($tail === null || $tail === '') ? GENESIS : (string) $tail;

$have = $s->querySingle("SELECT v FROM audit_chain_meta WHERE k='chain_last_anchor'");
if ($have === $anchor) {
    echo "chain anchor already current; now holds 0 rows to backfill\n";
    $s->close();
    exit(0);
}
$ah = SQLite3::escapeString($anchor);
$s->exec("INSERT INTO audit_chain_meta (k,v) VALUES ('chain_last_anchor','{$ah}') ON CONFLICT(k) DO UPDATE SET v='{$ah}'");
$s->exec("INSERT OR IGNORE INTO audit_chain_meta (k,v) VALUES ('chain_segment_anchor_{$ah}','{$ah}')");
echo "recorded chain segment anchor; rows inserted after this point are chained; now holds 0 rows to backfill\n";
$s->close();
exit(0);
