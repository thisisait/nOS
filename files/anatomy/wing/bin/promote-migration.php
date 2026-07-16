<?php

declare(strict_types=1);

/**
 * promote-migration.php — the forge-merge → review_status='merged' bridge
 * (Phase B / B6). The PULL-model writer (§7-Q1: pull, NO inbound forge webhook):
 * tools/migration-pr.sh --mark-merged calls this after the operator merges the
 * local-forge MR, and the same entry point doubles as the next-deploy ingest
 * pass. Mirror of planned-coexistence.php (raw PDO, --data-dir, getopt idiom).
 *
 * GATE 2 boundary: this is the ONLY path to migrations_authored.review_status=
 * 'merged'. Wing's setReviewStatus() hard-refuses 'merged'; no Wing UI/API can
 * reach it. Reaching here means the operator already merged the MR on the local
 * forge — the merge IS the gate; this only records it.
 *
 *   --mark-merged --uuid=U --committed-sha=SHA [--applied-migration-id=ID]
 *   --mark-merged --migration-id=ID --committed-sha=SHA [--applied-migration-id=ID]
 *       Flip the matching draft/in_review row to review_status='merged', stamp
 *       committed_sha (+ optional applied_migration_id), and emit the
 *       migration_promoted event (audit-chain-aware via App\Model\AuditChain).
 *       Idempotent: re-running on an already-merged row re-stamps committed_sha
 *       and does NOT re-emit (changed=0). Exit 0 on success, 1 if no matching
 *       row, 2 on usage error.
 *
 *   --list-merged-pending
 *       JSON array of merged rows whose migration has not yet RUN
 *       (applied_migration_id IS NULL) — the next-deploy ingest reads this to
 *       know which merged migrations are awaiting their first apply.
 *
 * Identity: --actor defaults to 'operator' (the merge is a human action on the
 * forge). source defaults to 'operator'. actor_action_id reuses the row's
 * session_uuid so SELECT WHERE actor_action_id=? still reconstructs the whole
 * authoring→promotion run (A14 lineage).
 *
 * --data-dir defaults to ~/wing/app/data.
 */

require dirname(__DIR__) . '/vendor/autoload.php';

use App\Model\AuditChain;

$opts = getopt('', [
    'mark-merged', 'list-merged-pending',
    'uuid:', 'migration-id:', 'committed-sha:', 'applied-migration-id:',
    'actor:', 'data-dir:',
]);
$dataDir = $opts['data-dir'] ?? (getenv('HOME') . '/wing/app/data');
$dbPath = rtrim($dataDir, '/') . '/wing.db';

if (!is_file($dbPath)) {
    if (isset($opts['list-merged-pending'])) {
        echo "[]\n";
        exit(0);
    }
    fwrite(STDERR, "wing.db not found: {$dbPath}\n");
    exit(1);
}

$db = new PDO('sqlite:' . $dbPath);
$db->setAttribute(PDO::ATTR_TIMEOUT, 5); // seconds; prevents 'database is locked' under concurrent writers (scout HIGH 2026-07-15)
$db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

if (isset($opts['list-merged-pending'])) {
    $rows = [];
    foreach ($db->query(
        "SELECT service, recipe_id, migration_id, uuid, committed_sha
         FROM migrations_authored
         WHERE review_status='merged' AND (applied_migration_id IS NULL OR applied_migration_id='')
         ORDER BY updated_at DESC"
    ) as $r) {
        $rows[] = [
            'service'        => $r['service'],
            'recipe_id'      => $r['recipe_id'],
            'migration_id'   => $r['migration_id'],
            'migration_uuid' => $r['uuid'],
            'committed_sha'  => $r['committed_sha'],
        ];
    }
    echo json_encode($rows) . "\n";
    exit(0);
}

if (isset($opts['mark-merged'])) {
    $uuid = (string) ($opts['uuid'] ?? '');
    $migrationId = (string) ($opts['migration-id'] ?? '');
    $committedSha = (string) ($opts['committed-sha'] ?? '');
    $appliedMigrationId = isset($opts['applied-migration-id']) ? (string) $opts['applied-migration-id'] : '';
    $actor = (string) ($opts['actor'] ?? 'operator');

    if ($uuid === '' && $migrationId === '') {
        fwrite(STDERR, "--mark-merged requires --uuid or --migration-id\n");
        exit(2);
    }
    if ($committedSha === '') {
        fwrite(STDERR, "--mark-merged requires --committed-sha (the merged commit SHA on the local forge)\n");
        exit(2);
    }

    // Resolve the target row. Prefer the authoring uuid (stable, unique); fall
    // back to migration_id (the files/anatomy/migrations/<id>.yml filename).
    if ($uuid !== '') {
        $q = $db->prepare("SELECT * FROM migrations_authored WHERE uuid=:u LIMIT 1");
        $q->execute([':u' => $uuid]);
    } else {
        // migration_id is not UNIQUE across review_status churn; take the newest
        // non-terminal (draft/in_review) row first, else the newest merged row so
        // a re-run is idempotent.
        $q = $db->prepare(
            "SELECT * FROM migrations_authored
             WHERE migration_id=:m
             ORDER BY (review_status IN ('draft','in_review')) DESC, id DESC LIMIT 1"
        );
        $q->execute([':m' => $migrationId]);
    }
    $row = $q->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        fwrite(STDERR, "no migrations_authored row for "
            . ($uuid !== '' ? "uuid={$uuid}" : "migration-id={$migrationId}") . " to mark merged\n");
        exit(1);
    }

    $id = (int) $row['id'];
    $service = (string) $row['service'];
    $recipeId = (string) $row['recipe_id'];
    $rowUuid = (string) $row['uuid'];
    $rowMigrationId = $row['migration_id'] !== null ? (string) $row['migration_id'] : null;
    $alreadyMerged = (($row['review_status'] ?? '') === 'merged');

    $db->beginTransaction();
    try {
        // Delete-prior any OTHER stale 'merged' row for the same (service,recipe)
        // so the flip can't trip UNIQUE(service,recipe_id,review_status). Never
        // touch the row we're updating. Mirrors insertAuthored()'s draft/in_review
        // delete-prior + MigrationAuthoredRepository::markMerged().
        if (!$alreadyMerged) {
            $del = $db->prepare(
                "DELETE FROM migrations_authored
                 WHERE service=:s AND recipe_id=:r AND review_status='merged' AND id<>:id"
            );
            $del->execute([':s' => $service, ':r' => $recipeId, ':id' => $id]);
        }

        $sql = "UPDATE migrations_authored
                SET review_status='merged', committed_sha=:sha, updated_at=:ts";
        $params = [':sha' => $committedSha, ':ts' => gmdate('c'), ':id' => $id];
        if ($appliedMigrationId !== '') {
            $sql .= ", applied_migration_id=:amid";
            $params[':amid'] = $appliedMigrationId;
        }
        $sql .= " WHERE id=:id";
        $db->prepare($sql)->execute($params);

        $db->commit();
    } catch (\Throwable $e) {
        $db->rollBack();
        fwrite(STDERR, "mark-merged failed: " . $e->getMessage() . "\n");
        exit(1);
    }

    // Re-running on an already-merged row re-stamps committed_sha but does NOT
    // re-emit the promotion event (idempotent; changed=0). A first-time flip
    // emits migration_promoted (audit-lineaged to the authoring session_uuid).
    if ($alreadyMerged) {
        echo "marked-merged: {$service}/{$recipeId} ({$rowUuid}) already merged — committed_sha re-stamped (changed=0)\n";
        exit(0);
    }

    $result = ['migration_uuid' => $rowUuid, 'committed_sha' => $committedSha];
    if ($appliedMigrationId !== '') {
        $result['applied_migration_id'] = $appliedMigrationId;
    }
    emitEvent($db, [
        'type'         => 'migration_promoted',
        'migration_id' => $rowMigrationId,   // FK col carries the migration id (§2.6)
        'result'       => $result,
        'source'       => 'operator',
        'actor_id'     => $actor,
        // session_uuid groups the authoring run + this promotion (A14 lineage).
        'actor_action_id' => $rowUuid,
        'task'         => "migration {$service} merged on forge",
    ]);

    echo "marked-merged: {$service}/{$recipeId} ({$rowUuid}) → merged @ {$committedSha} (changed=1)\n";
    exit(0);
}

fwrite(STDERR, "usage: promote-migration.php --mark-merged (--uuid=U | --migration-id=ID) --committed-sha=SHA"
    . " [--applied-migration-id=ID] [--actor=ID] [--data-dir=PATH]\n"
    . "       promote-migration.php --list-merged-pending [--data-dir=PATH]\n");
exit(2);

/**
 * Insert one events row, mirroring EventRepository::insert() /
 * clients/wing.py insert_event() — including the tamper-evident hash-chain
 * when WING_AUDIT_CHAIN_ENABLED=1. AuditChain is the shared algorithm
 * (canonical() byte-parity pinned by tests/anatomy/test_audit_chain.py), so
 * this third writer stays chain-correct.
 *
 * @param array<string,mixed> $payload
 */
function emitEvent(PDO $db, array $payload): void
{
    $values = [
        'ts'           => (string) ($payload['ts'] ?? gmdate('c')),
        'run_id'       => (string) ($payload['run_id'] ?? ''),
        'type'         => (string) ($payload['type'] ?? ''),
        'playbook'     => $payload['playbook']     ?? null,
        'play'         => $payload['play']         ?? null,
        'task'         => $payload['task']         ?? null,
        'role'         => $payload['role']         ?? null,
        'host'         => $payload['host']         ?? null,
        'duration_ms'  => isset($payload['duration_ms']) ? (int) $payload['duration_ms'] : null,
        'changed'      => array_key_exists('changed', $payload)
            ? ((bool) $payload['changed'] ? 1 : 0)
            : null,
        'result_json'  => isset($payload['result']) && is_array($payload['result'])
            ? json_encode($payload['result'])
            : null,
        'migration_id' => $payload['migration_id'] ?? null,
        'upgrade_id'   => $payload['upgrade_id']   ?? null,
        'patch_id'     => $payload['patch_id']     ?? null,
        'coexist_svc'  => $payload['coexistence_service'] ?? null,
        'source'       => $payload['source']       ?? null,
        'actor_id'     => $payload['actor_id']     ?? null,
        'acted_at'     => $payload['acted_at']     ?? null,
    ];
    $actorActionId = $payload['actor_action_id'] ?? null;

    $cols = 'ts, run_id, type, playbook, play, task, role, host, duration_ms, changed, '
        . 'result_json, migration_id, upgrade_id, patch_id, coexist_svc, source, '
        . 'actor_id, actor_action_id, acted_at';

    $chainKey = AuditChain::chainKey();
    if (getenv('WING_AUDIT_CHAIN_ENABLED') === '1' && $chainKey !== null) {
        // Serialize tail read + sign + insert in one write txn (BEGIN IMMEDIATE)
        // so prev_hash can't race the PHP/Python writers.
        $db->exec('BEGIN IMMEDIATE');
        try {
            $prev = $db->query('SELECT row_hash FROM events WHERE row_hash IS NOT NULL ORDER BY id DESC LIMIT 1')
                ->fetchColumn();
            $prev = ($prev === false || $prev === null) ? AuditChain::GENESIS : (string) $prev;
            $rowHash = AuditChain::rowHash($prev, $values, $chainKey);
            $stmt = $db->prepare(
                "INSERT INTO events ({$cols}, prev_hash, row_hash) "
                . 'VALUES (:ts,:run_id,:type,:playbook,:play,:task,:role,:host,:duration_ms,:changed,'
                . ':result_json,:migration_id,:upgrade_id,:patch_id,:coexist_svc,:source,'
                . ':actor_id,:actor_action_id,:acted_at,:prev_hash,:row_hash)'
            );
            $stmt->execute(bindEventParams($values, $actorActionId) + [':prev_hash' => $prev, ':row_hash' => $rowHash]);
            $db->commit();
            return;
        } catch (\Throwable $e) {
            if ($db->inTransaction()) {
                $db->rollBack();
            }
            throw $e;
        }
    }

    // Default chain-off path — prev_hash/row_hash left NULL by column default.
    $stmt = $db->prepare(
        "INSERT INTO events ({$cols}) "
        . 'VALUES (:ts,:run_id,:type,:playbook,:play,:task,:role,:host,:duration_ms,:changed,'
        . ':result_json,:migration_id,:upgrade_id,:patch_id,:coexist_svc,:source,'
        . ':actor_id,:actor_action_id,:acted_at)'
    );
    $stmt->execute(bindEventParams($values, $actorActionId));
}

/**
 * @param array<string,mixed> $values
 * @return array<string,mixed>
 */
function bindEventParams(array $values, $actorActionId): array
{
    return [
        ':ts' => $values['ts'], ':run_id' => $values['run_id'], ':type' => $values['type'],
        ':playbook' => $values['playbook'], ':play' => $values['play'], ':task' => $values['task'],
        ':role' => $values['role'], ':host' => $values['host'], ':duration_ms' => $values['duration_ms'],
        ':changed' => $values['changed'], ':result_json' => $values['result_json'],
        ':migration_id' => $values['migration_id'], ':upgrade_id' => $values['upgrade_id'],
        ':patch_id' => $values['patch_id'], ':coexist_svc' => $values['coexist_svc'],
        ':source' => $values['source'], ':actor_id' => $values['actor_id'],
        ':actor_action_id' => $actorActionId, ':acted_at' => $values['acted_at'],
    ];
}
