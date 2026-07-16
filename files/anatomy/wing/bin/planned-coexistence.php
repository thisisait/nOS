<?php

declare(strict_types=1);

/**
 * planned-coexistence.php — bridge the coexistence_planned queue to the
 * Ansible coexistence consumer (W5-B5c, 2026-05-27). Mirror of
 * planned-upgrades.php.
 *
 *   --list   → JSON array of {service, tag, target_version, port_offset} for
 *              status=planned rows (the consumer provisions each).
 *   --list-gated → like --list but each row also carries the G-PROVISION-MIGRATED
 *              gate fields {plan_mode, source_migration_uuid, migration_merged}.
 *              A plan_mode='coexist' row may ONLY provision once its linked
 *              migrations_authored row reaches review_status='merged' (GATE 2 —
 *              the operator's local-forge MR merge). tasks/coexistence-apply.yml
 *              filters on migration_merged so a coexist track whose migration is
 *              not yet merged is refused (skipped) until the operator merges.
 *              A plan_mode='migration' (or unlinked legacy) row has no migration
 *              prerequisite → migration_merged=true (gate open).
 *   --mark-applied --service=S --tag=T  → flip the row to status=applied.
 *   --cancel --service=S --tag=T        → flip a queued row to status=cancelled
 *              (the missing dequeue; pure Wing-DB op, NO host mutation — a
 *              queued track was never provisioned). Refuses if there is no
 *              status=planned row to cancel (exit 1).
 *
 * --data-dir defaults to ~/wing/app/data.
 */

$opts = getopt('', ['list', 'list-gated', 'mark-applied', 'cancel', 'service:', 'tag:', 'reason:', 'data-dir:']);
$dataDir = $opts['data-dir'] ?? (getenv('HOME') . '/wing/app/data');
$dbPath = rtrim($dataDir, '/') . '/wing.db';

if (!is_file($dbPath)) {
    if (isset($opts['list']) || isset($opts['list-gated'])) {
        echo "[]\n";
    }
    exit(0);
}

$db = new PDO('sqlite:' . $dbPath);
$db->setAttribute(PDO::ATTR_TIMEOUT, 5); // seconds; prevents 'database is locked' under concurrent writers (scout HIGH 2026-07-15)
$db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

if (isset($opts['list'])) {
    $rows = [];
    foreach ($db->query("SELECT service, tag, target_version, port_offset FROM coexistence_planned WHERE status='planned'") as $r) {
        $rows[] = [
            'service'        => $r['service'],
            'tag'            => $r['tag'],
            'target_version' => $r['target_version'],
            'port_offset'    => (int) ($r['port_offset'] ?? 10),
        ];
    }
    echo json_encode($rows) . "\n";
    exit(0);
}

if (isset($opts['list-gated'])) {
    // Each planned row, annotated with the G-PROVISION-MIGRATED gate. The
    // plan_mode comes from the linked upgrades_planned row (parent_upgrade_id);
    // a coexist row's migration prerequisite is a migrations_authored row at
    // review_status='merged' whose uuid == coexistence_planned.source_migration_uuid
    // (the migration the track is built ON). Only a forge merge (GATE 2) sets
    // 'merged' — no agent / Wing API can. plan_mode='migration' (or an unlinked
    // legacy row) carries no migration prerequisite, so migration_merged=true.
    // Resolve the merged migration the track is built ON. Returns the
    // migrations_authored.migration_id (the files/anatomy/migrations/<id>.yml id
    // the track records as source_migration_id and the cutover hook consumes via
    // nos_migrate action=apply) when a merged row matches the uuid, else null.
    $mergedMigrationId = static function (PDO $db, string $uuid): ?string {
        if ($uuid === '') {
            return null;
        }
        $q = $db->prepare(
            "SELECT migration_id FROM migrations_authored
             WHERE uuid = :u AND review_status = 'merged' LIMIT 1"
        );
        $q->execute([':u' => $uuid]);
        $row = $q->fetch(PDO::FETCH_ASSOC);
        if ($row === false) {
            return null;
        }
        // A merged row with a NULL migration_id is still a gate pass (the merge
        // happened); fall back to the empty string so the gate reads as merged.
        return (string) ($row['migration_id'] ?? '');
    };

    $rows = [];
    foreach ($db->query(
        "SELECT cp.service, cp.tag, cp.target_version, cp.port_offset,
                cp.source_migration_uuid AS source_migration_uuid,
                up.plan_mode AS plan_mode
         FROM coexistence_planned cp
         LEFT JOIN upgrades_planned up ON up.id = cp.parent_upgrade_id
         WHERE cp.status = 'planned'"
    ) as $r) {
        $planMode = $r['plan_mode'] ?? 'migration';
        $sourceUuid = (string) ($r['source_migration_uuid'] ?? '');
        // A coexist row gates on a merged migration; anything else is open.
        $migrationId = null;
        if ($planMode === 'coexist') {
            $migrationId = $mergedMigrationId($db, $sourceUuid);
            $merged = $migrationId !== null;
        } else {
            $merged = true;
        }
        $rows[] = [
            'service'               => $r['service'],
            'tag'                   => $r['tag'],
            'target_version'        => $r['target_version'],
            'port_offset'           => (int) ($r['port_offset'] ?? 10),
            'plan_mode'             => $planMode,
            'source_migration_uuid' => $sourceUuid !== '' ? $sourceUuid : null,
            'source_migration_id'   => ($migrationId !== null && $migrationId !== '') ? $migrationId : null,
            'migration_merged'      => $merged,
        ];
    }
    echo json_encode($rows) . "\n";
    exit(0);
}

if (isset($opts['mark-applied'])) {
    $service = $opts['service'] ?? '';
    $tag = $opts['tag'] ?? '';
    if ($service === '' || $tag === '') {
        fwrite(STDERR, "--mark-applied requires --service and --tag\n");
        exit(2);
    }
    // delete-prior avoids the UNIQUE(service,tag,status) collision on re-apply
    $db->prepare("DELETE FROM coexistence_planned WHERE service=:s AND tag=:t AND status='applied'")
        ->execute([':s' => $service, ':t' => $tag]);
    $stmt = $db->prepare(
        "UPDATE coexistence_planned SET status='applied', applied_at=:ts
         WHERE service=:s AND tag=:t AND status='planned'"
    );
    $stmt->execute([':ts' => gmdate('c'), ':s' => $service, ':t' => $tag]);
    echo "marked-applied: {$service}/{$tag} ({$stmt->rowCount()} row)\n";
    exit(0);
}

if (isset($opts['cancel'])) {
    $service = $opts['service'] ?? '';
    $tag = $opts['tag'] ?? '';
    if ($service === '' || $tag === '') {
        fwrite(STDERR, "--cancel requires --service and --tag\n");
        exit(2);
    }
    // Refuse if there is no queued row to cancel: an already-applied track must
    // go deactivate → cleanup (the destructive path), not cancel. Cancel is the
    // dequeue of a row that was NEVER provisioned, so there is no host state.
    $check = $db->prepare(
        "SELECT COUNT(*) FROM coexistence_planned WHERE service=:s AND tag=:t AND status='planned'"
    );
    $check->execute([':s' => $service, ':t' => $tag]);
    if ((int) $check->fetchColumn() === 0) {
        fwrite(STDERR, "no status=planned row for {$service}/{$tag} to cancel\n");
        exit(1);
    }
    // delete-prior avoids the UNIQUE(service,tag,status) collision: a future
    // re-plan + re-cancel must not trip the constraint on the old cancelled row.
    $db->prepare("DELETE FROM coexistence_planned WHERE service=:s AND tag=:t AND status='cancelled'")
        ->execute([':s' => $service, ':t' => $tag]);
    $reason = $opts['reason'] ?? null;
    $stmt = $db->prepare(
        "UPDATE coexistence_planned
         SET status='cancelled', cancelled_at=:ts, cancelled_by=:by
         WHERE service=:s AND tag=:t AND status='planned'"
    );
    $stmt->execute([
        ':ts' => gmdate('c'),
        ':by' => $reason ?? 'operator',
        ':s' => $service,
        ':t' => $tag,
    ]);
    echo "cancelled: {$service}/{$tag} ({$stmt->rowCount()} row)\n";
    exit(0);
}

fwrite(STDERR, "usage: planned-coexistence.php --list | --list-gated | --mark-applied --service=S --tag=T"
    . " | --cancel --service=S --tag=T [--reason=R] [--data-dir=PATH]\n");
exit(2);
