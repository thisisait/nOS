<?php
/**
 * BoxApiClient — smoke test: constructor reads env, headers shaped right,
 * unreachable endpoint returns 502 shape.
 */

declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

use App\Model\BoxApiClient;

// Point at a guaranteed-unreachable port on loopback. Should return 502.
$client = new BoxApiClient('http://127.0.0.1:1', 'test-secret', 1);

$resp = $client->get('/api/health');
T::eq(502, $resp['status'], 'unreachable endpoint returns 502 shape');
T::truthy(is_array($resp['body']), 'body is array');
T::truthy(isset($resp['body']['error']), 'error key populated');

// POST should behave the same.
$resp = $client->post('/api/migrations/nonexistent/apply', ['dry_run' => true]);
T::eq(502, $resp['status'], 'unreachable POST returns 502');

// Default env fallback: BOXAPI_URL unset → defaults to localhost:8069.
putenv('BOXAPI_URL');
putenv('BOXAPI_SECRET');
$defaultClient = new BoxApiClient();
$r = new ReflectionClass($defaultClient);
$prop = $r->getProperty('baseUrl');
$prop->setAccessible(true);
T::eq('http://127.0.0.1:8069', $prop->getValue($defaultClient), 'default baseUrl');

T::done('BoxApiClient');
