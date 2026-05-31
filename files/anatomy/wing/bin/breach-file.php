<?php

declare(strict_types=1);

/**
 * Wing — file one personal-data breach (gdpr_breaches; GDPR Art 33/34 + NIS2/ZKB).
 *
 * Usage:
 *   php bin/breach-file.php --json=<path|->
 *
 * JSON shape:
 *   detected_at  (required)  ISO-8601 UTC ('...Z' or '...+00:00') — incident detection
 *   nature       (required)  short headline
 *   status       (required)  detected | notified | resolved | non-reportable
 *   risk_level   (opt)       none | low | medium | high  (default none)
 *   aware_at     (opt)       ISO-8601 UTC; defaults to detected_at ('became aware')
 *   affected_subjects, affected_records (int)
 *   data_categories, likely_consequences, measures_taken, notes (text)
 *   art34_exception            encryption | risk_mitigated | disproportionate_effort
 *   nis2_in_scope, nis2_cross_border, nis2_intentional_suspected (bool -> 0/1)
 *   nis2_regime                higher | lower | critical_infra
 *
 * detected_at/aware_at MUST be UTC — a LOCAL-time stamp would skew the
 * 24h/72h/1-month math by the host offset, so non-UTC is REJECTED (exit 2).
 *
 * Exit codes: 0 ok · 1 bad args / unreadable · 2 JSON shape / non-UTC ts · 3 DB error.
 */

require __DIR__ . '/../vendor/autoload.php';

$jsonArg = null;
foreach ($argv as $arg) {
    if (str_starts_with($arg, '--json=')) {
        $jsonArg = substr($arg, 7);
    }
}
if ($jsonArg === null || $jsonArg === '') {
    fwrite(STDERR, "Usage: php bin/breach-file.php --json=<path|->\n");
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

foreach (['detected_at', 'nature', 'status'] as $req) {
    if (empty($decoded[$req])) {
        fwrite(STDERR, "Missing required field: {$req}\n");
        exit(2);
    }
}

$validStatus = ['detected', 'notified', 'resolved', 'non-reportable'];
if (!in_array($decoded['status'], $validStatus, true)) {
    fwrite(STDERR, "status must be one of: " . implode(', ', $validStatus) . "\n");
    exit(2);
}

$risk = $decoded['risk_level'] ?? 'none';
if (!in_array($risk, ['none', 'low', 'medium', 'high'], true)) {
    fwrite(STDERR, "risk_level must be one of: none, low, medium, high\n");
    exit(2);
}

// UTC discipline — reject any offset other than Z / +00:00 (silent-skew guard).
$isUtc = static fn(string $ts): bool => (bool) preg_match('/(Z|\+00:00)$/', $ts);
$awareIn = $decoded['aware_at'] ?? $decoded['detected_at'];
foreach (['detected_at' => $decoded['detected_at'], 'aware_at' => $awareIn] as $label => $ts) {
    if (!$isUtc((string) $ts)) {
        fwrite(STDERR, "{$label} must be ISO-8601 UTC (suffix 'Z' or '+00:00'): {$ts}\n");
        exit(2);
    }
}

$bool = static fn($v): int => !empty($v) ? 1 : 0;

$payload = [
    'detected_at'                => $decoded['detected_at'],
    'aware_at'                   => $awareIn,
    'nature'                     => $decoded['nature'],
    'status'                     => $decoded['status'],
    'risk_level'                 => $risk,
    'affected_subjects'          => $decoded['affected_subjects'] ?? null,
    'affected_records'           => $decoded['affected_records'] ?? null,
    'data_categories'            => $decoded['data_categories'] ?? null,
    'likely_consequences'        => $decoded['likely_consequences'] ?? null,
    'measures_taken'             => $decoded['measures_taken'] ?? null,
    'art34_exception'            => $decoded['art34_exception'] ?? null,
    'nis2_in_scope'              => $bool($decoded['nis2_in_scope'] ?? false),
    'nis2_regime'                => $decoded['nis2_regime'] ?? null,
    'nis2_cross_border'          => $bool($decoded['nis2_cross_border'] ?? false),
    'nis2_intentional_suspected' => $bool($decoded['nis2_intentional_suspected'] ?? false),
    'regulator_ref'              => $decoded['regulator_ref'] ?? null,
    'notes'                      => $decoded['notes'] ?? null,
];

try {
    $container = App\Bootstrap\Booting::boot()->createContainer();
} catch (\Throwable $e) {
    fwrite(STDERR, "Container boot failed: " . $e->getMessage() . "\n");
    exit(3);
}

/** @var App\Model\GdprRepository $repo */
$repo = $container->getByType(App\Model\GdprRepository::class);

try {
    $id = $repo->recordBreach($payload); // stamps *_due_at via BreachDeadlines
} catch (\Throwable $e) {
    fwrite(STDERR, "DB recordBreach failed: " . $e->getMessage() . "\n");
    exit(3);
}

echo "OK filed gdpr_breach #{$id} (risk={$payload['risk_level']}, status={$payload['status']})\n";
exit(0);
