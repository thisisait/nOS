<?php

declare(strict_types=1);

/**
 * Wing — Upsert one row into the gdpr_processing register (Article 30).
 *
 * Usage:
 *   php bin/upsert-gdpr.php --id=app_<name> --json=<path-to-record.json>
 *   php bin/upsert-gdpr.php --id=app_<name> --json=-              # stdin
 *
 * Called by roles/pazny.apps_runner/tasks/post.yml — one invocation per
 * onboarded apps/<name>.yml manifest. The JSON record is the resolved
 * record.gdpr block from nos_apps_render (the parser already validated it
 * against state/schema/app.schema.json), augmented with a `name` and
 * `purpose` so the Wing /gdpr UI has something to show.
 *
 * Mapping (nos_apps_render → gdpr_processing columns):
 *   id                  ← --id (caller-set, "app_<name>" by convention)
 *   name                ← record.name      (the app's human-readable name)
 *   purpose             ← record.purpose
 *   legal_basis         ← record.legal_basis
 *   data_categories     ← record.data_categories     (JSON array)
 *   data_subjects       ← record.data_subjects       (JSON array)
 *   processors          ← record.processors          (JSON array)
 *   security_measures   ← record.security_measures   (JSON array)
 *   retention_days      ← record.retention_days
 *   transfers_outside_eu ← record.transfers_outside_eu (0/1)
 *   notes               ← record.notes
 *
 * The repository (App\Model\GdprRepository) handles JSON-encoding the
 * array columns + setting updated_at. INSERT-or-UPDATE based on `id`.
 *
 * Exit codes:
 *   0 — upserted (or no-op when JSON is empty)
 *   1 — bad CLI args / unreadable input
 *   2 — JSON decode error / invalid shape
 *   3 — DB error
 */

require __DIR__ . '/../vendor/autoload.php';

$id = null;
$jsonArg = null;
foreach ($argv as $arg) {
    if (str_starts_with($arg, '--id=')) {
        $id = substr($arg, 5);
    } elseif (str_starts_with($arg, '--json=')) {
        $jsonArg = substr($arg, 7);
    }
}

if ($id === null || $id === '' || $jsonArg === null || $jsonArg === '') {
    fwrite(STDERR, "Usage: php bin/upsert-gdpr.php --id=app_<name> --json=<path|->\n");
    exit(1);
}

// Resolve JSON source: literal path on disk OR '-' for stdin.
if ($jsonArg === '-') {
    $raw = stream_get_contents(STDIN);
    if ($raw === false) {
        fwrite(STDERR, "Failed to read JSON from stdin\n");
        exit(1);
    }
} else {
    if (!is_file($jsonArg)) {
        fwrite(STDERR, "JSON file not found: {$jsonArg}\n");
        exit(1);
    }
    $raw = file_get_contents($jsonArg);
    if ($raw === false) {
        fwrite(STDERR, "Failed to read {$jsonArg}\n");
        exit(1);
    }
}

$decoded = json_decode($raw, true);
if (!is_array($decoded)) {
    fwrite(STDERR, "Invalid JSON shape (expected object): " . json_last_error_msg() . "\n");
    exit(2);
}

// Boot Nette container so we can get the GdprRepository service.
try {
    $container = App\Bootstrap\Booting::boot()->createContainer();
} catch (\Throwable $e) {
    fwrite(STDERR, "Container boot failed: " . $e->getMessage() . "\n");
    exit(3);
}

/** @var App\Model\GdprRepository $repo */
$repo = $container->getByType(App\Model\GdprRepository::class);

// The repository handles JSON-encoding for array cols (data_categories,
// data_subjects, processors, security_measures) and setting updated_at.
// Pass through whatever subset of columns the caller provided — the parser
// has already enforced that mandatory keys exist. We coerce booleans to
// 0/1 for SQLite compatibility.
$payload = [];
$copyKeys = [
    'name', 'purpose', 'legal_basis', 'data_categories', 'data_subjects',
    'processors', 'security_measures', 'retention_days', 'notes',
];
foreach ($copyKeys as $k) {
    if (array_key_exists($k, $decoded)) {
        $payload[$k] = $decoded[$k];
    }
}
if (array_key_exists('transfers_outside_eu', $decoded)) {
    $payload['transfers_outside_eu'] = $decoded['transfers_outside_eu'] ? 1 : 0;
}
// Default the human-readable name to the id if the caller forgot — the
// /gdpr UI uses it for the table heading.
if (!isset($payload['name']) || $payload['name'] === '') {
    $payload['name'] = $id;
}

try {
    $repo->upsertProcessing($id, $payload);
} catch (\Throwable $e) {
    fwrite(STDERR, "DB upsert failed: " . $e->getMessage() . "\n");
    exit(3);
}

echo "OK upserted gdpr_processing.{$id}\n";
exit(0);
