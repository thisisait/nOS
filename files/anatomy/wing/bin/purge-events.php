<?php

declare(strict_types=1);

/**
 * Wing — Purge audit `events` rows past the retention horizon (GDPR Art. 5(1)(e)
 * storage limitation).
 *
 * Usage:
 *   php bin/purge-events.php --db=<path> --older-than-days=<n> [--dry-run]
 *
 * Called by tasks/audit-retention.yml (opt-in `--tags audit-retention`). Deletes
 * rows whose `ts` is older than now - N days. Uses raw SQLite3 (no Nette
 * container boot) so it is fast and standalone-testable; `julianday()` parses
 * the stored ISO-8601 `ts` robustly regardless of `T`/`Z` formatting.
 *
 * --dry-run reports the count WITHOUT deleting. Exit codes:
 *   0 ok · 1 bad args · 3 DB error.
 */

$db = null;
$days = null;
$dryRun = false;
foreach ($argv as $arg) {
    if (str_starts_with($arg, '--db=')) {
        $db = substr($arg, 5);
    } elseif (str_starts_with($arg, '--older-than-days=')) {
        $days = substr($arg, 18);
    } elseif ($arg === '--dry-run') {
        $dryRun = true;
    }
}

if ($db === null || $db === '' || $days === null || $days === '') {
    fwrite(STDERR, "Usage: php bin/purge-events.php --db=<path> --older-than-days=<n> [--dry-run]\n");
    exit(1);
}
if (!ctype_digit((string) $days) || (int) $days <= 0) {
    fwrite(STDERR, "--older-than-days must be a positive integer\n");
    exit(1);
}
$days = (int) $days;
if (!is_file($db)) {
    fwrite(STDERR, "DB not found: {$db}\n");
    exit(3);
}

try {
    $sqlite = new SQLite3($db, SQLITE3_OPEN_READWRITE);
} catch (\Throwable $e) {
    fwrite(STDERR, "Cannot open {$db}: " . $e->getMessage() . "\n");
    exit(3);
}

// julianday(ts) < julianday('now', '-N days') — robust against T/Z ISO forms.
$predicate = "julianday(ts) < julianday('now', '-{$days} days')";

$count = (int) $sqlite->querySingle("SELECT COUNT(*) FROM events WHERE {$predicate}");

if ($dryRun) {
    echo "DRY-RUN: would purge {$count} events older than {$days} days\n";
    $sqlite->close();
    exit(0);
}

// Detect whether THIS db has the audit-chain surface. Absent (chain-off
// install, pre-feature DB, or a legacy test seed) -> the original byte-identical
// DELETE so we never crash on a DB lacking audit_chain_meta / row_hash.
$hasMeta = (int) $sqlite->querySingle(
    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='audit_chain_meta'"
) > 0;
$hasRowHash = false;
$ti = $sqlite->query('PRAGMA table_info(events)');
while ($c = $ti->fetchArray(SQLITE3_ASSOC)) {
    if ($c['name'] === 'row_hash') {
        $hasRowHash = true;
        break;
    }
}

$chainInWindow = 0;
if ($hasMeta && $hasRowHash) {
    $chainInWindow = (int) $sqlite->querySingle(
        "SELECT COUNT(*) FROM events WHERE {$predicate} AND row_hash IS NOT NULL"
    );
}

if (!$hasMeta || !$hasRowHash || $chainInWindow === 0) {
    // Legacy / chain-off / no-chained-rows-in-window: original path, unchanged.
    $ok = $sqlite->exec("DELETE FROM events WHERE {$predicate}");
    $sqlite->close();
    if ($ok === false) {
        fwrite(STDERR, "DELETE failed\n");
        exit(3);
    }
    echo "Purged {$count} events older than {$days} days\n";
    exit(0);
}

// Chain-aware re-anchor path: capture the survivor boundary (newest purged
// row's hash), unlock the WORM DELETE guard, delete, record last_purged_hash so
// the verifier accepts the survivor's prev_hash, reset the guard — one txn.
$boundaryHash = $sqlite->querySingle(
    "SELECT row_hash FROM events WHERE {$predicate} AND row_hash IS NOT NULL ORDER BY id DESC LIMIT 1"
);
$cutoff = $sqlite->querySingle("SELECT MAX(ts) FROM events WHERE {$predicate}");
$sqlite->exec('BEGIN IMMEDIATE');
try {
    $sqlite->exec("INSERT INTO audit_chain_meta (k,v) VALUES ('purge_unlocked','1') ON CONFLICT(k) DO UPDATE SET v='1'");
    $ok = $sqlite->exec("DELETE FROM events WHERE {$predicate}");
    if ($ok === false) {
        throw new \RuntimeException('DELETE failed');
    }
    if ($boundaryHash) {
        $bh = SQLite3::escapeString((string) $boundaryHash);
        $ct = SQLite3::escapeString((string) $cutoff);
        $sqlite->exec("INSERT INTO audit_chain_meta (k,v) VALUES ('last_purged_hash','{$bh}') ON CONFLICT(k) DO UPDATE SET v='{$bh}'");
        $sqlite->exec("INSERT INTO audit_chain_meta (k,v) VALUES ('last_purged_cutoff','{$ct}') ON CONFLICT(k) DO UPDATE SET v='{$ct}'");
    }
    $sqlite->exec("UPDATE audit_chain_meta SET v='0' WHERE k='purge_unlocked'");
    $sqlite->exec('COMMIT');
} catch (\Throwable $e) {
    $sqlite->exec("UPDATE audit_chain_meta SET v='0' WHERE k='purge_unlocked'");
    @$sqlite->exec('ROLLBACK');
    $sqlite->close();
    fwrite(STDERR, 'DELETE failed: ' . $e->getMessage() . "\n");
    exit(3);
}
$sqlite->close();
echo "Purged {$count} events older than {$days} days\n";
exit(0);
