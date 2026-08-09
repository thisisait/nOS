#!/usr/bin/env php
<?php

declare(strict_types=1);

/**
 * Wing — verify the tamper-evident audit hash-chain over wing.db `events`.
 *
 * Usage:
 *   php bin/verify-audit-chain.php --db=<path> [--json]
 *
 * Exit codes: 0 chain intact · 1 bad args · 2 chain BROKEN · 3 DB/secret error.
 *
 * Reuses App\Model\AuditChain verbatim (same canonicalization the writer signs
 * with) so writer + verifier can never drift. Segment-aware: tolerates an
 * unsigned (NULL row_hash) run — legacy prefix or a chain-off maintenance
 * window — and resumes at a row whose prev_hash is GENESIS, a recorded
 * re-enable anchor, or the retention-purge survivor boundary.
 */

require __DIR__ . '/../app/Model/AuditChain.php';

$db = null;
$json = false;
$writeVerdict = false;
foreach ($argv as $a) {
    if (str_starts_with($a, '--db=')) {
        $db = substr($a, 5);
    } elseif ($a === '--json') {
        $json = true;
    } elseif ($a === '--write-verdict') {
        $writeVerdict = true;
    }
}
if ($db === null || $db === '') {
    fwrite(STDERR, "Usage: php bin/verify-audit-chain.php --db=<path> [--json]\n");
    exit(1);
}
if (!is_file($db)) {
    fwrite(STDERR, "DB not found: {$db}\n");
    exit(3);
}
// The key RING, not one key (2026-08-06). Current first, then retired. A
// segment is verified by whichever ring member matches its FIRST row, and that
// member must then verify every remaining row of the segment — so a key change
// is possible only where a new segment is possible, i.e. at a recorded anchor.
// Without that constraint a leaked retired key could re-sign a suffix.
$keyRing = \App\Model\AuditChain::chainKeys();
if ($keyRing === []) {
    fwrite(STDERR, "WING_EVENTS_HMAC_SECRET not set\n");
    exit(3);
}
$key = $keyRing[0];

$s = new SQLite3($db, SQLITE3_OPEN_READONLY);
$s->enableExceptions(true);

// Authorized segment-start hashes: GENESIS, every recorded re-enable anchor,
// and the retention purge survivor boundary.
$anchors = [\App\Model\AuditChain::GENESIS => true];
$lastPurged = $s->querySingle("SELECT v FROM audit_chain_meta WHERE k='last_purged_hash'");
if ($lastPurged) {
    $anchors[(string) $lastPurged] = true;
}
$ar = $s->query("SELECT v FROM audit_chain_meta WHERE k LIKE 'chain_segment_anchor_%'");
while ($a = $ar->fetchArray(SQLITE3_ASSOC)) {
    if (!empty($a['v'])) {
        $anchors[(string) $a['v']] = true;
    }
}

$res = $s->query('SELECT * FROM events ORDER BY id ASC');
$prev = null;
$segmentOpen = false;
$checked = 0;
$skipped = 0;
$break = null;
while ($row = $res->fetchArray(SQLITE3_ASSOC)) {
    if ($row['row_hash'] === null) {     // unsigned: legacy prefix or chain-off window
        $segmentOpen = false;
        $prev = null;
        $skipped++;
        continue;
    }
    // A key may be re-elected at exactly two places: the first row of a
    // segment, and any row whose prev_hash is a recorded anchor.
    //
    // THE SECOND CLAUSE IS LOAD-BEARING and the first draft omitted it. A
    // rotation on a LIVE chain produces no gap — the next row's prev_hash is
    // simply the sealed head — so `!$segmentOpen` never fires again and the
    // ring was never consulted. Measured: the very first post-rotation row
    // failed as "content tampered". An anchor is the authorization to change
    // keys; whether a row happens to also start a segment is incidental.
    $atAnchor = isset($anchors[(string) $row['prev_hash']]);
    if (!$segmentOpen) {                  // first chained row of a (possibly new) segment
        if (!$atAnchor) {
            $break = ['id' => $row['id'], 'why' => 'segment start prev_hash neither genesis nor recorded anchor'];
            break;
        }
        $prev = (string) $row['prev_hash'];
        $segmentOpen = true;
    }
    if ($atAnchor || $key === null) {
        // Elect the ring member that verifies THIS row. Between anchors the
        // elected key is the only one accepted, so a suffix re-signed with a
        // leaked retired key breaks at the row where the key changes.
        $elected = null;
        foreach ($keyRing as $candidate) {
            $probe = \App\Model\AuditChain::rowHash((string) $prev, $row, $candidate);
            if (hash_equals($probe, (string) $row['row_hash'])) {
                $elected = $candidate;
                break;
            }
        }
        if ($elected === null) {
            $break = ['id' => $row['id'], 'why' => 'row at key-rotation point verifies under no key in the ring'];
            break;
        }
        $key = $elected;
    }
    if (!hash_equals((string) $prev, (string) $row['prev_hash'])) {
        $break = ['id' => $row['id'], 'why' => 'prev_hash break'];
        break;
    }
    $expect = \App\Model\AuditChain::rowHash((string) $prev, $row, $key);
    if (!hash_equals($expect, (string) $row['row_hash'])) {
        $break = ['id' => $row['id'], 'why' => 'row_hash mismatch (content tampered)'];
        break;
    }
    $prev = (string) $row['row_hash'];
    $checked++;
}
$s->close();

// --write-verdict: cache the integrity verdict into audit_chain_meta so the
// Wing header badge reads it cheaply (no per-render chain walk). Opt-in — the
// Pulse verify job is the only caller; fires regardless of --json. WAL-safe
// (busyTimeout) + best-effort: a write failure is SWALLOWED so the exit code
// stays driven SOLELY by the verdict (0 intact / 2 broken / 3 secret-or-db).
// Computed BEFORE the verdict write, not after. The first draft put this check
// below and left `$verdictOk` keyed on `$break` alone — so the Wing header badge
// would have rendered a calm green while this process exited 2. A cached verdict
// that disagrees with the verdict is the defect this whole file is about.
$tailIsCurrent = $key === null || hash_equals($keyRing[0], (string) $key);

if ($writeVerdict) {
    $verdictOk = ($break === null && $tailIsCurrent) ? '1' : '0';
    try {
        $w = new SQLite3($db, SQLITE3_OPEN_READWRITE);
        $w->busyTimeout(5000);
        $hasMeta = (int) $w->querySingle(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='audit_chain_meta'"
        );
        if ($hasMeta > 0) {
            $now = gmdate('c');
            $u = $w->prepare("INSERT INTO audit_chain_meta (k,v) VALUES ('last_verify_ok', :v) ON CONFLICT(k) DO UPDATE SET v = :v");
            $u->bindValue(':v', $verdictOk);
            $u->execute();
            $u2 = $w->prepare("INSERT INTO audit_chain_meta (k,v) VALUES ('last_verify_at', :v) ON CONFLICT(k) DO UPDATE SET v = :v");
            $u2->bindValue(':v', $now);
            $u2->execute();
        }
        $w->close();
    } catch (\Throwable $e) {
        fwrite(STDERR, "verdict-write skipped: " . $e->getMessage() . "\n");
    }
}

if ($break !== null) {
    if ($json) {
        echo json_encode(['ok' => false, 'checked' => $checked, 'unsigned' => $skipped, 'first_break' => $break]) . "\n";
    } else {
        fwrite(STDERR, "CHAIN-BROKEN at id={$break['id']}: {$break['why']}\n");
    }
    exit(2);
}

// A CONSISTENT CHAIN IS NOT A CORRECTLY-SIGNED ONE (added 2026-08-09).
//
// Everything above asks one question: is the chain self-consistent? It never
// asks WHICH ring member signed it, and those are not the same question. A
// writer holding a retired secret signs every row with it, each row verifies
// against the last, and this file prints CHAIN-OK forever.
//
// Measured, not imagined. On 2026-08-08 the tail segment changed keys and the
// break exposed what had been true underneath:
//
//     retired key   173948 rows   2026-07-24T20:49 .. 2026-08-08T07:24
//     current key      152 rows   2026-08-08T07:25 .. 2026-08-08T07:28
//
// The ENTIRE chain — every row of it — had been signed with a retired
// credential for fifteen days, and the nightly job reported ok:true on every
// one of those nights. The rotation that retired that key had run, reported
// success, and the Wing daemon never adopted it: launchd had not re-read the
// changed plist (fixed separately, roles/pazny.wing/tasks/main.yml). Rotating a
// leaked key is worth nothing if the writer keeps using the old one, and the
// control that exists to notice could not see it.
//
// So the tail is checked against the CURRENT key specifically. This is the only
// place that can catch it: a break needs a key CHANGE, and a writer that never
// changes its key never produces one.
if (!$tailIsCurrent) {
    if ($json) {
        echo json_encode([
            'ok' => false, 'checked' => $checked, 'unsigned' => $skipped,
            'first_break' => null,
            'stale_key' => 'the newest segment is signed with a RETIRED key — the '
                . 'chain is self-consistent and the writer never adopted the rotation',
        ]) . "\n";
    } else {
        fwrite(STDERR, "CHAIN-STALE-KEY: {$checked} rows verify, but the newest "
            . "segment is signed with a RETIRED key. The writer never adopted the "
            . "rotation; restart the Wing daemon so it re-reads its plist.\n");
    }
    exit(2);
}

if ($json) {
    echo json_encode(['ok' => true, 'checked' => $checked, 'unsigned' => $skipped,
                      'tail_key' => 'current']) . "\n";
} else {
    echo "CHAIN-OK: {$checked} chained rows verified, {$skipped} unsigned rows "
        . "skipped, newest segment signed with the current key\n";
}
exit(0);
