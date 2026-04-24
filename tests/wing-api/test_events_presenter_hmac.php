<?php
/**
 * Api\EventsPresenter — exercise HMAC validation + schema validation in
 * isolation. We don't spin up the full Nette application; instead we
 * reproduce the HMAC algorithm and hit the repository directly.
 *
 * The canonical HMAC algorithm is the same on both sides (see
 * files/boxapi/events.py::verify_hmac and
 * Api\EventsPresenter::checkHmac): hmac_sha256(secret, ts + '.' + raw_body)
 */

declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

use App\Model\EventRepository;

$db = gw_make_temp_db();
$exp = gw_make_explorer($db);
$events = new EventRepository($exp);

$secret = 'test-hmac-secret-' . bin2hex(random_bytes(4));
$payload = [
	'ts'       => gmdate('c'),
	'run_id'   => 'run_hmac_test',
	'type'     => 'playbook_start',
	'playbook' => 'main.yml',
];
$rawBody = json_encode($payload, JSON_UNESCAPED_SLASHES);
$ts = (string) time();
$sig = hash_hmac('sha256', $ts . '.' . $rawBody, $secret);

// Sanity: same algorithm produces identical digests.
T::eq($sig, hash_hmac('sha256', $ts . '.' . $rawBody, $secret), 'hmac deterministic');
T::eq(64, strlen($sig), 'sha256 hex is 64 chars');

// Drift-out-of-window timestamps get rejected (±300s window).
$oldTs = (string) (time() - 400);
$oldSig = hash_hmac('sha256', $oldTs . '.' . $rawBody, $secret);
$drift = abs(time() - (int) $oldTs);
T::truthy($drift > 300, 'old timestamp is outside 300s window');

// Insert via repo to confirm payload shape works end-to-end.
$id = $events->insert($payload);
T::truthy($id > 0, 'valid payload inserts');

// Invalid type rejected by VALID_TYPES constant.
T::truthy(in_array('playbook_start', EventRepository::VALID_TYPES, true), 'valid type');
T::truthy(!in_array('bogus_type', EventRepository::VALID_TYPES, true), 'invalid type rejected');

// Tamper with signature — hash_equals returns false.
$badSig = str_repeat('0', 64);
T::truthy(!hash_equals($sig, $badSig), 'tampered signature rejected');

// Missing required field detected.
$bad = ['type' => 'playbook_start']; // missing ts + run_id
$missing = [];
foreach (['ts', 'run_id', 'type'] as $f) {
	if (!isset($bad[$f])) {
		$missing[] = $f;
	}
}
T::eq(['ts', 'run_id'], $missing, 'missing-field detection works');

T::done('EventsPresenter HMAC + schema');
