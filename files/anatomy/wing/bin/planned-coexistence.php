<?php

declare(strict_types=1);

/**
 * planned-coexistence.php — bridge the coexistence_planned queue to the
 * Ansible coexistence consumer (W5-B5c, 2026-05-27). Mirror of
 * planned-upgrades.php.
 *
 *   --list   → JSON array of {service, tag, target_version, port_offset} for
 *              status=planned rows (the consumer provisions each).
 *   --mark-applied --service=S --tag=T  → flip the row to status=applied.
 *   --cancel --service=S --tag=T        → flip a queued row to status=cancelled
 *              (the missing dequeue; pure Wing-DB op, NO host mutation — a
 *              queued track was never provisioned). Refuses if there is no
 *              status=planned row to cancel (exit 1).
 *
 * --data-dir defaults to ~/wing/app/data.
 */

$opts = getopt('', ['list', 'mark-applied', 'cancel', 'service:', 'tag:', 'reason:', 'data-dir:']);
$dataDir = $opts['data-dir'] ?? (getenv('HOME') . '/wing/app/data');
$dbPath = rtrim($dataDir, '/') . '/wing.db';

if (!is_file($dbPath)) {
    if (isset($opts['list'])) {
        echo "[]\n";
    }
    exit(0);
}

$db = new PDO('sqlite:' . $dbPath);
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

fwrite(STDERR, "usage: planned-coexistence.php --list | --mark-applied --service=S --tag=T"
    . " | --cancel --service=S --tag=T [--reason=R] [--data-dir=PATH]\n");
exit(2);
