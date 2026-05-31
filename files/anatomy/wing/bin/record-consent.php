<?php

declare(strict_types=1);

/**
 * Wing — Record one GDPR consent lifecycle row (gdpr_consent, Art. 6(1)(a) + Art. 7).
 *
 * Usage:
 *   php bin/record-consent.php --json=<path-to-record.json>     # grant (intake)
 *   php bin/record-consent.php --json=-                          # grant from stdin
 *   php bin/record-consent.php --withdraw=<id> [--notes=...]     # withdraw by row id
 *   php bin/record-consent.php --withdraw-subject=<email> --activity=<a> [--notes=...]
 *                                                                # withdraw by subject+activity
 *
 * GRANT inserts one ACTIVE row (withdrawn_at NULL) — the Art. 7(1) demonstrable
 * proof that THIS subject consented to THIS activity. tos_version_hash pins WHICH
 * terms text was presented (evidence of the terms shown — NOT proof the act was
 * freely-given/specific/informed/unambiguous per Art-4(11)/Art-7(2)). Consent is
 * an explicit act, NEVER inferred from an Authentik login: SSO is authentication,
 * consent is a separate recorded decision.
 *
 * WITHDRAW stamps withdrawn_at on the matching active row(s) (Art. 7(3) — as easy
 * to withdraw as to give). It never deletes: grant + withdrawal both stay in the
 * ledger as the audit record. Idempotent — re-withdrawing keeps the original
 * timestamp.
 *
 * JSON shape (grant; → gdpr_consent columns):
 *   subject_email     (required)   the data subject
 *   activity          (required)   the consented-to activity slug
 *   processing_id     (optional)   gdpr_processing.id this covers (slug | svc_<x> | app_<x>)
 *   lawful_basis      (optional)   Art. 6(1) basis; defaults to 'consent'
 *   tos_version_hash  (optional)   hash of the terms presented (NOT a secret)
 *   source            (optional)   operator | ui | api | import; defaults 'operator'
 *   granted_at        (optional)   ISO-8601; defaults to now
 *   notes             (optional)   free-form
 *
 * Exit codes: 0 ok · 1 bad args / unreadable · 2 JSON shape · 3 DB error.
 */

require __DIR__ . '/../vendor/autoload.php';

$jsonArg = null;
$withdrawId = null;
$withdrawSubject = null;
$activity = null;
$notes = null;
foreach ($argv as $arg) {
    if (str_starts_with($arg, '--json=')) {
        $jsonArg = substr($arg, 7);
    } elseif (str_starts_with($arg, '--withdraw=')) {
        $withdrawId = (int) substr($arg, 11);
    } elseif (str_starts_with($arg, '--withdraw-subject=')) {
        $withdrawSubject = substr($arg, 19);
    } elseif (str_starts_with($arg, '--activity=')) {
        $activity = substr($arg, 11);
    } elseif (str_starts_with($arg, '--notes=')) {
        $notes = substr($arg, 8);
    }
}

// ── Withdraw mode (Art. 7(3)) ────────────────────────────────────────────────
if ($withdrawId !== null && $withdrawId > 0) {
    try {
        $container = App\Bootstrap\Booting::boot()->createContainer();
        /** @var App\Model\GdprRepository $repo */
        $repo = $container->getByType(App\Model\GdprRepository::class);
        $n = $repo->withdrawConsent(id: $withdrawId, notes: $notes);
    } catch (\Throwable $e) {
        fwrite(STDERR, "DB withdrawConsent failed: " . $e->getMessage() . "\n");
        exit(3);
    }
    echo "OK withdrew gdpr_consent #{$withdrawId} ({$n} row(s) transitioned)\n";
    exit(0);
}

if ($withdrawSubject !== null && $withdrawSubject !== '') {
    if ($activity === null || $activity === '') {
        fwrite(STDERR, "Usage: php bin/record-consent.php --withdraw-subject=<email> --activity=<a> [--notes=...]\n");
        exit(1);
    }
    try {
        $container = App\Bootstrap\Booting::boot()->createContainer();
        /** @var App\Model\GdprRepository $repo */
        $repo = $container->getByType(App\Model\GdprRepository::class);
        $n = $repo->withdrawConsent(subjectEmail: $withdrawSubject, activity: $activity, notes: $notes);
    } catch (\Throwable $e) {
        fwrite(STDERR, "DB withdrawConsent failed: " . $e->getMessage() . "\n");
        exit(3);
    }
    echo "OK withdrew consent for {$withdrawSubject}/{$activity} ({$n} row(s) transitioned)\n";
    exit(0);
}

// ── Grant mode (intake) ──────────────────────────────────────────────────────
if ($jsonArg === null || $jsonArg === '') {
    fwrite(STDERR, "Usage: php bin/record-consent.php --json=<path|-> | --withdraw=<id> | --withdraw-subject=<email> --activity=<a>\n");
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

foreach (['subject_email', 'activity'] as $req) {
    if (empty($decoded[$req])) {
        fwrite(STDERR, "Missing required field: {$req}\n");
        exit(2);
    }
}

$payload = [
    'subject_email'    => $decoded['subject_email'],
    'activity'         => $decoded['activity'],
    'processing_id'    => $decoded['processing_id'] ?? null,
    'lawful_basis'     => $decoded['lawful_basis'] ?? 'consent',
    'tos_version_hash' => $decoded['tos_version_hash'] ?? null,
    'source'           => $decoded['source'] ?? 'operator',
    'granted_at'       => $decoded['granted_at'] ?? date('Y-m-d H:i:s'),
    'notes'            => $decoded['notes'] ?? null,
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
    $id = $repo->recordConsent($payload);
} catch (\Throwable $e) {
    fwrite(STDERR, "DB recordConsent failed: " . $e->getMessage() . "\n");
    exit(3);
}

echo "OK recorded gdpr_consent #{$id} ({$payload['subject_email']}/{$payload['activity']})\n";
exit(0);
