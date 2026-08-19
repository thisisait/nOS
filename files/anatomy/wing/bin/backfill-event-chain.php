#!/usr/bin/env php
<?php

declare(strict_types=1);

/**
 * Wing — record the audit-chain enable / re-enable anchor.
 *
 * Usage:
 *   php bin/backfill-event-chain.php --data-dir=<dir>
 *   php bin/backfill-event-chain.php --data-dir=<dir> --acknowledge-gap-before=<id>
 *
 * Does NOT retroactively sign rows we never witnessed (that would be forging an
 * audit trail). It records the CURRENT chain tail as a segment anchor so the
 * verifier accepts the boundary after a chain OFF->ON toggle (an unsigned/NULL
 * run between two signed segments). MUST run after each flag OFF->ON toggle;
 * roles/pazny.wing/tasks/post.yml does this when wing_audit_chain_enabled is on.
 *
 * Idempotent: prints 'now holds 0' when the recorded anchor already matches the
 * current tail (post.yml keys changed_when on that). Exit 0 always (best-effort).
 *
 * --acknowledge-gap-before=<id> — the OPERATOR act for a gap discovered LATE,
 * i.e. after signed rows already follow it, so the tail-anchor path above can
 * no longer authorize the historical boundary. Measured 2026-08-16..19: a bare
 * `php bin/run-agent.php` inherited no chain env and appended 37 unsigned rows
 * (337463-337499); the next signed segment (337500) starts at the hash of row
 * 337462, which nothing had recorded as an anchor, and audit-chain-verify has
 * exited 2 every night since. <id> names the FIRST SIGNED row after the gap.
 * The mode verifies before it writes — the named row must be signed, its
 * prev_hash must equal the row_hash of the last signed row before it, and the
 * window between must be non-empty and wholly unsigned — so it can only ever
 * authorize a clean chain-off window, never paper over content tampering. It
 * signs NOTHING: the window stays visibly unsigned in every verify report;
 * what changes is that the verifier accepts the reviewed boundary. Refusals
 * exit 2 — an acknowledgement that did not happen must not read as done.
 */

const GENESIS = 'nos-audit-chain-genesis-v1';

$dir = null;
$ackBefore = null;
foreach ($argv as $a) {
    if (str_starts_with($a, '--data-dir=')) {
        $dir = substr($a, 11);
    }
    if (str_starts_with($a, '--acknowledge-gap-before=')) {
        $ackBefore = (int) substr($a, 25);
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

if ($ackBefore !== null) {
    // ── the late-acknowledgement mode (header §--acknowledge-gap-before) ──
    // Verify FIRST, write second. Every refusal exits 2: an acknowledgement
    // that did not happen must not read as done.
    $refuse = function (string $why) use ($s): void {
        fwrite(STDERR, "REFUSED: {$why}\n");
        $s->close();
        exit(2);
    };
    $q = $s->prepare('SELECT id, prev_hash, row_hash FROM events WHERE id = :id');
    $q->bindValue(':id', $ackBefore, SQLITE3_INTEGER);
    $row = $q->execute()->fetchArray(SQLITE3_ASSOC);
    if (!$row) {
        $refuse("no event row with id {$ackBefore}");
    }
    if ($row['row_hash'] === null || $row['row_hash'] === '') {
        $refuse("row {$ackBefore} is UNSIGNED — name the first SIGNED row after the gap, not a row inside it");
    }
    $q = $s->prepare('SELECT id, row_hash FROM events WHERE row_hash IS NOT NULL AND id < :id ORDER BY id DESC LIMIT 1');
    $q->bindValue(':id', $ackBefore, SQLITE3_INTEGER);
    $before = $q->execute()->fetchArray(SQLITE3_ASSOC);
    if (!$before) {
        $refuse("no signed row precedes {$ackBefore} — that boundary is genesis, nothing to acknowledge");
    }
    if ((string) $row['prev_hash'] !== (string) $before['row_hash']) {
        $refuse(
            "row {$ackBefore}'s prev_hash does not equal the row_hash of the last signed row "
            . "before it (id {$before['id']}) — this is NOT a clean chain-off window and may be "
            . "tampering; an anchor here would authorize it"
        );
    }
    $gap = $s->querySingle(
        "SELECT COUNT(*) FROM events WHERE id > {$before['id']} AND id < {$ackBefore}"
    );
    if ((int) $gap === 0) {
        $refuse("no unsigned window between {$before['id']} and {$ackBefore} — nothing to acknowledge");
    }
    $meta = $s->query(
        "SELECT MIN(ts) AS t0, MAX(ts) AS t1,
                GROUP_CONCAT(DISTINCT COALESCE(source,'?')) AS sources,
                GROUP_CONCAT(DISTINCT COALESCE(actor_id,'?')) AS actors
           FROM events WHERE id > {$before['id']} AND id < {$ackBefore}"
    )->fetchArray(SQLITE3_ASSOC);
    $ah = SQLite3::escapeString((string) $before['row_hash']);
    $s->exec("INSERT OR IGNORE INTO audit_chain_meta (k,v) VALUES ('chain_segment_anchor_{$ah}','{$ah}')");
    echo "acknowledged chain-off window: {$gap} unsigned row(s), ids "
        . ($before['id'] + 1) . "-" . ($ackBefore - 1)
        . " ({$meta['t0']} .. {$meta['t1']}; source(s) {$meta['sources']}; actor(s) {$meta['actors']})\n";
    echo "recorded segment anchor at row {$before['id']}'s hash; the window stays UNSIGNED "
        . "in every verify report — this authorizes the boundary, it signs nothing\n";
    $s->close();
    exit(0);
}

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
