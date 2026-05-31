<?php

declare(strict_types=1);

/**
 * Wing — scan gdpr_breaches for overdue regulator-notification deadlines and
 * emit ONE CRITICAL notification per overdue stage (GDPR Art-33 + NÚKIB
 * 24h/72h/30d). Raw SQLite3, no Bone, no HMAC — CI-seedable + standalone.
 *
 * NOTE: GDPR Art-34 (data-subject notification) is REPORT-only and is NOT
 * escalated here — its 'without undue delay' standard has no zero-hour
 * deadline, so escalating it from t=0 would alert-spam every high-risk filing.
 * See breach-report.php for the Art-34 status block.
 *
 * Usage:
 *   php bin/breach-scan.php [--db=<path>] [--dry-run]
 *   (WING_DB_PATH env, else ~/wing/app/data/wing.db)
 *
 * Exit codes: 0 ok · 1 bad args · 3 DB error.
 */

$db = getenv('WING_DB_PATH') ?: (($_SERVER['HOME'] ?? '') . '/wing/app/data/wing.db');
$dry = false;
foreach ($argv as $i => $a) {
    if ($i === 0) {
        continue;
    }
    if (str_starts_with($a, '--db=')) {
        $db = substr($a, 5);
    } elseif ($a === '--dry-run') {
        $dry = true;
    } else {
        fwrite(STDERR, "Usage: php bin/breach-scan.php [--db=<path>] [--dry-run]\n");
        exit(1);
    }
}
if (!is_file($db)) {
    fwrite(STDERR, "DB not found: {$db}\n");
    exit(3);
}

try {
    $s = new SQLite3($db, SQLITE3_OPEN_READWRITE);
    $s->enableExceptions(true);
} catch (\Throwable $e) {
    fwrite(STDERR, "Cannot open {$db}: " . $e->getMessage() . "\n");
    exit(3);
}

// Stage -> [due column, done column, human label]. Art-34 is ABSENT by design
// (report-only). A stage escalates only when its due column is non-NULL
// (recordBreach stamps NULL for non-applicable stages — the risk/NIS2 gate).
$stages = [
    'art33'      => ['art33_due_at', 'notified_supervisor_at', 'GDPR Art-33 supervisory (ÚOOÚ) 72h notification'],
    'nis2_24h'   => ['nis2_early_warning_due_at', 'nis2_early_warning_done_at', 'NÚKIB 24h early warning'],
    'nis2_72h'   => ['nis2_notification_due_at', 'nis2_notification_done_at', 'NÚKIB 72h incident notification'],
    'nis2_final' => ['nis2_final_report_due_at', 'nis2_final_report_done_at', 'NÚKIB 30-day final report'],
];

$fired = 0;
try {
    foreach ($stages as $stage => [$due, $done, $label]) {
        // julianday() parses ISO-8601 regardless of T/Z (purge-events.php idiom).
        $sql = "SELECT id, nature, risk_level, {$due} AS due_at FROM gdpr_breaches
                WHERE {$due} IS NOT NULL
                  AND {$done} IS NULL
                  AND status NOT IN ('resolved', 'non-reportable')
                  AND julianday({$due}) < julianday('now')
                  AND escalated_stages_json NOT LIKE '%\"{$stage}\"%'";
        $r = $s->query($sql);
        while ($row = $r->fetchArray(SQLITE3_ASSOC)) {
            $id = (int) $row['id'];
            $uuid = "breach-{$id}-{$stage}-overdue"; // deterministic dedup key (uuid UNIQUE)

            // Skip-on-exists: prevents a UNIQUE-violation throw from aborting the
            // whole scan if a stale escalated_stages_json was cleared.
            $exists = (int) $s->querySingle(
                "SELECT COUNT(*) FROM notifications WHERE uuid = '" . SQLite3::escapeString($uuid) . "'"
            );
            if ($exists > 0) {
                continue;
            }

            $fired++;
            if ($dry) {
                continue;
            }

            $title = "GDPR breach #{$id}: {$label} OVERDUE";
            if (strlen($title) > 500) {
                $title = substr($title, 0, 500);
            }
            $body = "**Breach #{$id}** — {$row['nature']} (risk {$row['risk_level']})\n\n"
                  . "The **{$label}** deadline ({$row['due_at']} UTC) has PASSED and the stage is not marked done.\n\n"
                  . "Discharge: file with the regulator, then stamp the done timestamp "
                  . "(GdprRepository::markStage). See `php bin/breach-report.php --id={$id}`.";
            $meta = json_encode(['breach_id' => $id, 'stage' => $stage, 'click_url' => '/gdpr']);

            $s->exec('BEGIN IMMEDIATE');
            try {
                // EXPLICIT channels — the PHP/SQLite insert path does NOT read
                // notification-routing.json; omitting channels would silently
                // default to wing-inbox-only and never reach phone/mail.
                $ins = $s->prepare(
                    "INSERT INTO notifications
                        (uuid, severity, title, body, origin_plugin, actor_id, target_actor_id, channels_json, metadata_json)
                     VALUES
                        (:u, 'critical', :t, :b, 'gdpr-breach', 'plugin:gdpr-breach-scan', 'operator',
                         '[\"wing-inbox\",\"ntfy\",\"mail\"]', :m)"
                );
                $ins->bindValue(':u', $uuid);
                $ins->bindValue(':t', $title);
                $ins->bindValue(':b', $body);
                $ins->bindValue(':m', $meta);
                $ins->execute();

                // Stamp escalated_stages_json so an hourly re-scan no-ops.
                $up = $s->prepare(
                    "UPDATE gdpr_breaches
                        SET escalated_stages_json = json_insert(escalated_stages_json, '$[#]', :st),
                            updated_at = :ts
                      WHERE id = :id"
                );
                $up->bindValue(':st', $stage);
                $up->bindValue(':ts', gmdate('c'));
                $up->bindValue(':id', $id);
                $up->execute();

                $s->exec('COMMIT');
            } catch (\Throwable $e) {
                @$s->exec('ROLLBACK');
                throw $e;
            }
        }
    }
} catch (\Throwable $e) {
    $s->close();
    fwrite(STDERR, 'escalate failed: ' . $e->getMessage() . "\n");
    exit(3);
}

$s->close();
echo ($dry ? "DRY-RUN: " : "") . "{$fired} overdue breach stage(s) escalated\n";
exit(0);
