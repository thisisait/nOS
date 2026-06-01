<?php
/**
 * GdprRepository — consent ledger + DSAR terminal-status BEHAVIORAL coverage.
 *
 * Review finding C4: the consent/DSAR write methods shipped with string-presence
 * tests only (a stray `return 0;` satisfied the refuse-mass-withdraw guard, a
 * static substring satisfied updateDsarStatus). This executes them against a real
 * Nette Explorer on a temp sqlite seeded from schema-extensions.sql, so a logic
 * regression in any of them fails loudly instead of shipping green.
 */

declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

use App\Model\GdprRepository;

$db = gw_make_temp_db();
$explorer = gw_make_explorer($db);
$repo = new GdprRepository($explorer);

// ── Consent: grant inserts one ACTIVE row ────────────────────────────────────
$c1 = $repo->recordConsent([
    'subject_email' => 'alice@example.test',
    'activity'      => 'marketing-email',
    'processing_id' => 'svc_demo',
    'tos_version_hash' => 'sha256:abc',
]);
T::truthy($c1 > 0, 'recordConsent returns a positive id');
$rows = $repo->listConsent('alice@example.test');
T::eq(1, count($rows), 'one consent row for the subject');
T::eq(null, $rows[0]['withdrawn_at'], 'granted row is ACTIVE (withdrawn_at NULL)');
T::eq('consent', $rows[0]['lawful_basis'], 'lawful_basis defaults to consent');
T::eq('operator', $rows[0]['source'], 'source defaults to operator');

// ── Withdraw by id (Art. 7(3)) + idempotence ─────────────────────────────────
$n = $repo->withdrawConsent(id: $c1);
T::eq(1, $n, 'withdrawConsent(id) flips exactly the one active row');
$after = $repo->listConsent('alice@example.test')[0];
T::truthy($after['withdrawn_at'] !== null, 'row is now withdrawn');
$firstWithdrawnAt = $after['withdrawn_at'];
$n2 = $repo->withdrawConsent(id: $c1);
T::eq(0, $n2, 're-withdrawing the same id flips 0 rows (idempotent)');
$stillFirst = $repo->listConsent('alice@example.test')[0]['withdrawn_at'];
T::eq($firstWithdrawnAt, $stillFirst, 'original withdrawn_at preserved on re-withdraw');

// ── Withdraw by subject+activity flips ALL active rows for the pair ───────────
$repo->recordConsent(['subject_email' => 'bob@example.test', 'activity' => 'newsletter']);
$repo->recordConsent(['subject_email' => 'bob@example.test', 'activity' => 'newsletter']);  // double-grant
$repo->recordConsent(['subject_email' => 'bob@example.test', 'activity' => 'analytics']);   // different activity
$flipped = $repo->withdrawConsent(subjectEmail: 'bob@example.test', activity: 'newsletter');
T::eq(2, $flipped, 'withdraw by subject+activity flips both active newsletter grants, not analytics');

// ── Refuse-to-mass-withdraw guard (no addressing -> 0) ───────────────────────
$mass = $repo->withdrawConsent();
T::eq(0, $mass, 'withdrawConsent() with no id and no subject+activity refuses (0 rows)');
$onlySubject = $repo->withdrawConsent(subjectEmail: 'bob@example.test');
T::eq(0, $onlySubject, 'withdrawConsent(subject only, no activity) refuses (0 rows)');

// ── Art-17 pseudonymise: keep the proof row, blank the email ─────────────────
$before = $repo->withdrawConsent();  // no-op sanity already covered
$ps = $repo->pseudonymiseSubject('bob@example.test', 'erased-subject');
T::truthy($ps >= 3, 'pseudonymiseSubject overwrites all of the subject rows');
T::eq(0, count($repo->listConsent('bob@example.test')), 'no rows remain under the plaintext email');
T::truthy(count($repo->listConsent('erased-subject')) >= 3, 'rows survive under the opaque token (Art-7(1) proof kept)');

// ── DSAR: record intake + honest terminal transition ─────────────────────────
$d1 = $repo->recordDsar([
    'received_at'   => '2026-06-01 10:00:00',
    'subject_email' => 'carol@example.test',
    'request_type'  => 'erase',
    'status'        => 'received',
    'processing_ids' => ['svc_authentik', 'svc_gitea'],
]);
T::truthy($d1 > 0, 'recordDsar returns a positive id');
$open = $repo->listDsar('received');
T::truthy(count($open) >= 1, 'the received DSAR row is queryable');

$ok = $repo->updateDsarStatus($d1, 'in-progress', 'manual steps pending');
T::truthy($ok === true, 'updateDsarStatus transitions an existing row');
$ok2 = $repo->updateDsarStatus($d1, 'completed');
T::truthy($ok2 === true, 'updateDsarStatus -> completed succeeds');
$completed = $repo->listDsar('completed');
$row = array_values(array_filter($completed, fn($r) => (int) $r['id'] === $d1))[0];
T::truthy(!empty($row['completed_at']), 'completed status stamps completed_at');

$miss = $repo->updateDsarStatus(999999, 'completed');
T::truthy($miss === false, 'updateDsarStatus on a missing id returns false');

T::done('GdprRepository');
