#!/usr/bin/env php
<?php

declare(strict_types=1);

/**
 * Wing — seal the audit-chain anchor at a LEGITIMATE key rotation.
 *
 * WHY THIS HAD TO EXIST. The chain key can rotate; `AuditChain::chainKeys()`
 * keeps a ring so retired keys still VERIFY. But a key change is only accepted
 * where a segment may start, i.e. at a recorded anchor — otherwise a leaked
 * retired key could re-sign a suffix and the chain would agree.
 *
 * The only tool that recorded anchors was `backfill-event-chain.php`, and it
 * seals at the CURRENT TAIL, which is right for a chain OFF->ON toggle and
 * useless for a rotation that already happened: the boundary needing the anchor
 * is back in the history, not at the head. `main.yml`'s rotation path prints
 * "Anchor sealed at the current head" and `roles/pazny.wing/tasks/post.yml`
 * runs the tail-sealer during a converge — but the WRITER only changes key when
 * the daemon is restarted and re-reads its plist, which is not that moment.
 *
 * Measured 2026-08-08: the daemon picked up a secret rotated fifteen days
 * earlier, signed row 173949 with it, and the nightly verifier reported
 * `row_hash mismatch (content tampered)` on a chain nobody had touched. The
 * most alarming message the control can emit, for an intended operation — and a
 * control that cries tamper at routine maintenance is one an operator learns to
 * ignore.
 *
 * WHAT MAKES THIS SAFE, AND IT IS ONE RULE. An anchor is a licence for the key
 * to change at that point, so this refuses to seal one unless the change has
 * the shape of a rotation and could not have been produced by an attacker:
 *
 *   1. both sides verify under ring keys — forging either needs a key;
 *   2. the OLDER side is signed with a RETIRED key and the NEWER side with the
 *      CURRENT one. A rotation only ever runs old -> new. A suffix re-signed
 *      with a leaked retired key is current -> retired, the opposite, and is
 *      refused here however well it verifies.
 *
 * It never re-signs a row. Rewriting history to make it verify is forging an
 * audit trail; the only thing written is one metadata row saying "the key
 * legitimately changed here".
 *
 * Usage:
 *   php bin/seal-key-rotation.php [--db=<path>] [--apply]
 *
 * Dry run unless --apply. Exit 0 = nothing to seal or sealed; 2 = a boundary
 * was found that this refuses to seal (which is the interesting case, and it
 * must not read as success).
 */

require_once __DIR__ . '/../app/Model/AuditChain.php';

$db = null;
$apply = false;
foreach ($argv as $a) {
    if (str_starts_with($a, '--db=')) {
        $db = substr($a, 5);
    } elseif ($a === '--apply') {
        $apply = true;
    }
}
$db = $db ?: ((getenv('WING_DATA_DIR') ?: getenv('HOME') . '/wing/app/data') . '/wing.db');
if (!is_file($db)) {
    fwrite(STDERR, "DB not found: {$db}\n");
    exit(3);
}

$ring = \App\Model\AuditChain::chainKeys();
if ($ring === []) {
    fwrite(STDERR, "WING_EVENTS_HMAC_SECRET not set — nothing can be attributed\n");
    exit(3);
}
$current = $ring[0];

$s = new SQLite3($db, SQLITE3_OPEN_READONLY);
$s->enableExceptions(true);

$anchors = [\App\Model\AuditChain::GENESIS => true];
$ar = $s->query("SELECT v FROM audit_chain_meta WHERE k LIKE 'chain_segment_anchor_%'");
while ($a = $ar->fetchArray(SQLITE3_ASSOC)) {
    if (!empty($a['v'])) {
        $anchors[(string) $a['v']] = true;
    }
}

/** Which ring member signed this row, given its prev_hash? */
$attribute = static function (array $row, string $prev) use ($ring): ?int {
    foreach ($ring as $i => $k) {
        if (hash_equals(\App\Model\AuditChain::rowHash($prev, $row, $k), (string) $row['row_hash'])) {
            return $i;
        }
    }
    return null;
};

$res = $s->query('SELECT * FROM events WHERE row_hash IS NOT NULL ORDER BY id ASC');
$prevHash = null;
$prevKey = null;
$prevRow = null;
$found = [];
while ($row = $res->fetchArray(SQLITE3_ASSOC)) {
    $p = (string) $row['prev_hash'];
    $k = $attribute($row, $p);
    if ($k === null) {
        // Verifiable by no key in the ring. Not a rotation — say so and stop,
        // because everything after it is unattributable too.
        fwrite(STDERR, "row {$row['id']} verifies under NO key in the ring — this is "
            . "not a rotation boundary and this tool will not touch it.\n");
        $s->close();
        exit(2);
    }
    if ($prevKey !== null && $k !== $prevKey && !isset($anchors[$p])) {
        $found[] = ['id' => $row['id'], 'ts' => $row['ts'], 'anchor' => $p,
                    'from' => $prevKey, 'to' => $k, 'prev_id' => $prevRow['id']];
    }
    $prevHash = (string) $row['row_hash'];
    $prevKey = $k;
    $prevRow = $row;
}
$s->close();

if ($found === []) {
    echo "no unanchored key change; nothing to seal\n";
    exit(0);
}

$sealable = [];
foreach ($found as $b) {
    // Rule 2: old -> new only. `from` must be a retired index (>0), `to` must be
    // the current key (index 0). Anything else is refused.
    $ok = $b['from'] > 0 && $b['to'] === 0;
    printf("%s boundary at id=%d (%s): key %s -> %s\n",
        $ok ? ' SEALABLE ' : ' REFUSED  ', $b['id'], substr((string) $b['ts'], 0, 19),
        $b['from'] === 0 ? 'current' : "retired[{$b['from']}]",
        $b['to'] === 0 ? 'current' : "retired[{$b['to']}]");
    if ($ok) {
        $sealable[] = $b;
    } else {
        echo "            a rotation runs retired -> current. This runs the other "
            . "way, which is the shape a suffix re-signed with a leaked retired key "
            . "would have. Refusing.\n";
    }
}
if ($sealable === []) {
    exit(2);
}

if (!$apply) {
    echo "\nDRY RUN — nothing written. Re-run with --apply.\n";
    exit(0);
}

$w = new SQLite3($db, SQLITE3_OPEN_READWRITE);
$w->busyTimeout(5000);
$w->enableExceptions(true);
foreach ($sealable as $b) {
    $ah = SQLite3::escapeString($b['anchor']);
    $w->exec("INSERT OR IGNORE INTO audit_chain_meta (k,v) "
        . "VALUES ('chain_segment_anchor_{$ah}','{$ah}')");
    // The anchor alone says a key changed; this says WHEN and BETWEEN WHICH
    // rows, so the seal is auditable rather than an unexplained licence.
    $note = SQLite3::escapeString(sprintf(
        'key rotation sealed %s: rows %d->%d, retired[%d] -> current',
        gmdate('c'), $b['prev_id'], $b['id'], $b['from']));
    $w->exec("INSERT OR IGNORE INTO audit_chain_meta (k,v) "
        . "VALUES ('chain_rotation_note_{$ah}','{$note}')");
    echo "sealed anchor for the boundary at id={$b['id']}\n";
}
$w->close();
exit(0);
