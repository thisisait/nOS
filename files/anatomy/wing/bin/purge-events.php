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

$ok = $sqlite->exec("DELETE FROM events WHERE {$predicate}");
$sqlite->close();
if ($ok === false) {
    fwrite(STDERR, "DELETE failed\n");
    exit(3);
}

echo "Purged {$count} events older than {$days} days\n";
exit(0);
