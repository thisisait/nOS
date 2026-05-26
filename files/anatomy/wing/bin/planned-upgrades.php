<?php

declare(strict_types=1);

/**
 * planned-upgrades.php — bridge the upgrades_planned queue to the Ansible
 * upgrade-engine (W5-B3, 2026-05-26).
 *
 *   --list                          → JSON array of "service:recipe_id" keys
 *                                      (status=planned). The engine treats
 *                                      these as eligible under --tags upgrade.
 *   --mark-applied --service=S --recipe=R
 *                                   → flip the queued row to status=applied.
 *
 * Direct PDO (no container) so it runs fast inside the playbook loop.
 * --data-dir defaults to ~/wing/app/data.
 */

$opts = getopt('', ['list', 'mark-applied', 'service:', 'recipe:', 'data-dir:']);
$dataDir = $opts['data-dir'] ?? (getenv('HOME') . '/wing/app/data');
$dbPath = rtrim($dataDir, '/') . '/wing.db';

if (!is_file($dbPath)) {
    // No Wing DB (e.g. install_wing=false) — emit an empty queue, never fail.
    if (isset($opts['list'])) {
        echo "[]\n";
    }
    exit(0);
}

$db = new PDO('sqlite:' . $dbPath);
$db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

if (isset($opts['list'])) {
    $keys = [];
    foreach ($db->query("SELECT service, recipe_id FROM upgrades_planned WHERE status='planned'") as $r) {
        $keys[] = $r['service'] . ':' . $r['recipe_id'];
    }
    echo json_encode($keys) . "\n";
    exit(0);
}

if (isset($opts['mark-applied'])) {
    $service = $opts['service'] ?? '';
    $recipe = $opts['recipe'] ?? '';
    if ($service === '' || $recipe === '') {
        fwrite(STDERR, "--mark-applied requires --service and --recipe\n");
        exit(2);
    }
    $stmt = $db->prepare(
        "UPDATE upgrades_planned SET status='applied', applied_at=:ts
         WHERE service=:s AND recipe_id=:r AND status='planned'"
    );
    $stmt->execute([':ts' => gmdate('c'), ':s' => $service, ':r' => $recipe]);
    echo "marked-applied: {$service}:{$recipe} ({$stmt->rowCount()} row)\n";
    exit(0);
}

fwrite(STDERR, "usage: planned-upgrades.php --list | --mark-applied --service=S --recipe=R [--data-dir=PATH]\n");
exit(2);
