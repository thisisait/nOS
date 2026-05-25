<?php

declare(strict_types=1);

/**
 * Wing — Record one Data Subject Access Request row (gdpr_dsar, Art. 12-22).
 *
 * Usage:
 *   php bin/record-dsar.php --json=<path-to-record.json>
 *   php bin/record-dsar.php --json=-                       # stdin
 *
 * Called by tasks/gdpr-forget.yml — one invocation per right-to-erasure run.
 * A dry-run logs status="received" (the request is real even if no deletion
 * happens yet); a confirmed run logs status="completed" with the
 * gdpr_processing ids touched. This row is the legal audit record a CNIL-style
 * inspection traces; it is intentionally append-only (one row per run).
 *
 * JSON shape (→ gdpr_dsar columns; recordDsar() JSON-encodes processing_ids):
 *   subject_email   (required)   the data subject
 *   request_type    (required)   access | rectify | erase | portability | object
 *   status          (required)   received | in-progress | completed | rejected
 *   processing_ids  (array)      gdpr_processing.id values touched (e.g. svc_*)
 *   notes           (string)     free-form (e.g. dry-run plan summary)
 *   received_at     (optional)   ISO-8601; defaults to now
 *
 * Exit codes: 0 ok · 1 bad args / unreadable · 2 JSON shape · 3 DB error.
 */

require __DIR__ . '/../vendor/autoload.php';

$jsonArg = null;
foreach ($argv as $arg) {
    if (str_starts_with($arg, '--json=')) {
        $jsonArg = substr($arg, 7);
    }
}
if ($jsonArg === null || $jsonArg === '') {
    fwrite(STDERR, "Usage: php bin/record-dsar.php --json=<path|->\n");
    exit(1);
}

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

foreach (['subject_email', 'request_type', 'status'] as $req) {
    if (empty($decoded[$req])) {
        fwrite(STDERR, "Missing required field: {$req}\n");
        exit(2);
    }
}

$validTypes = ['access', 'rectify', 'erase', 'portability', 'object'];
if (!in_array($decoded['request_type'], $validTypes, true)) {
    fwrite(STDERR, "request_type must be one of: " . implode(', ', $validTypes) . "\n");
    exit(2);
}

$payload = [
    'received_at'    => $decoded['received_at'] ?? date('Y-m-d H:i:s'),
    'subject_email'  => $decoded['subject_email'],
    'request_type'   => $decoded['request_type'],
    'status'         => $decoded['status'],
    'processing_ids' => array_values($decoded['processing_ids'] ?? []),
    'notes'          => $decoded['notes'] ?? null,
];
if ($payload['status'] === 'completed') {
    $payload['completed_at'] = $decoded['completed_at'] ?? date('Y-m-d H:i:s');
}

try {
    $container = App\Bootstrap\Booting::boot()->createContainer();
} catch (\Throwable $e) {
    fwrite(STDERR, "Container boot failed: " . $e->getMessage() . "\n");
    exit(3);
}

/** @var App\Model\GdprRepository $repo */
$repo = $container->getByType(App\Model\GdprRepository::class);

try {
    $id = $repo->recordDsar($payload);
} catch (\Throwable $e) {
    fwrite(STDERR, "DB recordDsar failed: " . $e->getMessage() . "\n");
    exit(3);
}

echo "OK recorded gdpr_dsar #{$id} ({$payload['request_type']}/{$payload['status']})\n";
exit(0);
