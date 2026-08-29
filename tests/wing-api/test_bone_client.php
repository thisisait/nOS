<?php
/**
 * BoneClient — smoke test: an unreachable endpoint returns the 502 shape, a
 * missing identity returns 503 rather than a bare 401, and BONE_URL defaults.
 *
 * The identity half is the 2026-08-29 change. Bone retired the shared
 * X-API-Key with decision O4 and this client kept sending one, so every state
 * proxy answered 401. It now mints an Authentik client_credentials Bearer
 * through App\Core\AgentIdentity — cached here so the test makes no network
 * call and still exercises the real class.
 */

declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

use App\Core\AgentIdentity;
use App\Model\BoneClient;

$cacheDir = sys_get_temp_dir() . '/bone-client-test-' . getmypid();
@mkdir($cacheDir, 0700, true);
file_put_contents($cacheDir . '/nos-wing.json', json_encode([
    'access_token' => 'cached-test-token',
    'expires_at' => time() + 3600,
]));
$identity = new AgentIdentity('https://auth.invalid/token/', 'nos-wing', 'secret',
    ['nos:state:read'], $cacheDir);

// Point at a guaranteed-unreachable port on loopback. Should return 502.
$client = new BoneClient('http://127.0.0.1:1', $identity, 1);

$resp = $client->get('/api/health');
T::eq(502, $resp['status'], 'unreachable endpoint returns 502 shape');
T::truthy(is_array($resp['body']), 'body is array');
T::truthy(isset($resp['body']['error']), 'error key populated');

// POST should behave the same.
$resp = $client->post('/api/migrations/nonexistent/apply', ['dry_run' => true]);
T::eq(502, $resp['status'], 'unreachable POST returns 502');

// No secret to mint with → 503 naming the identity, not a 401 the caller has
// to reverse-engineer. This is the failure an unconverged host actually hits.
putenv('WING_AGENT_CLIENT_SECRET=');
$mintless = new BoneClient('http://127.0.0.1:1', new AgentIdentity(
    'https://auth.invalid/token/', 'nos-wing', '', ['nos:state:read'], $cacheDir . '/empty'), 1);
$resp = $mintless->get('/api/state');
T::eq(503, $resp['status'], 'no mintable identity returns 503');
T::truthy(str_contains((string) ($resp['body']['error'] ?? ''), 'identity'),
    'the 503 names the identity as the cause');

// Default env fallback: BONE_URL unset → defaults to localhost:8069.
putenv('BONE_URL');
$defaultClient = new BoneClient();
$r = new ReflectionClass($defaultClient);
$prop = $r->getProperty('baseUrl');
T::eq('http://127.0.0.1:8069', $prop->getValue($defaultClient), 'default baseUrl');

array_map('unlink', glob($cacheDir . '/*.json') ?: []);
@rmdir($cacheDir);

T::done('BoneClient');
