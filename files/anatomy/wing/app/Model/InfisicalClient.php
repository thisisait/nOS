<?php

declare(strict_types=1);

namespace App\Model;

use RuntimeException;

/**
 * Infisical CE REST client (Anatomy A18 invite-provisioning, 2026-05-20).
 *
 * Thin HTTP wrapper around the Infisical REST API for the Wing-side invite
 * flow (Cesta B Hybrid). Pushes per-user credentials into a "users" folder
 * inside a configured Infisical project so the operator can hand the user
 * a single Infisical share link covering all auto-provisioned creds
 * (mailbox password, future Bluesky handle, etc).
 *
 * Auth model: bearer JWT, identical to the Python seeder (`roles/pazny.
 * infisical/files/seed.py`). The token comes from INFISICAL_API_TOKEN env,
 * provisioned by the playbook into wing.plist.j2 from
 * `infisical_admin_token` in default.credentials.yml.
 *
 * Why a separate model from App\AgentKit\Vault\InfisicalClient:
 *   * AgentKit's InfisicalClient is READ-ONLY (`fetch()` only), invoked via
 *     the `infisical secrets get` CLI under hardened subprocess constraints.
 *     It's the agent-runtime path — minimal env allowlist, no token in the
 *     process env, secret never persisted beyond function-local memory.
 *   * This model is WRITE-CAPABLE (folder + secret CRUD) and lives on the
 *     FrankenPHP request path. Different threat model, different surface.
 *     Mixing the two would either widen the agent-runtime auth or leave
 *     the presenter without write reach.
 *
 * Path layout for per-user credentials:
 *
 *     <project> / <environment> / users / <username> / <secret_key>
 *
 * Examples:
 *
 *     /users/alice/mailbox_password
 *     /users/alice/bsky_handle           (future)
 *     /users/alice/service_xyz_token     (future)
 *
 * Scope (intentionally small — grows when the invite flow needs more):
 *   * createUserFolder(username)   — POST /api/v2/folders (idempotent)
 *   * upsertSecret(user, key, val) — POST /api/v3/secrets/raw/<key> +
 *                                    PATCH fallback (mirrors seed.py)
 *   * listUserSecrets(username)    — GET /api/v3/secrets/raw?secretPath=...
 *
 * Graceful degradation: when isConfigured() == false (token missing or
 * project not set), every method throws RuntimeException with a calibrated
 * "operator must run pazny.infisical bootstrap first" diagnostic instead
 * of bleeding raw 401s into the invite UI.
 */
final class InfisicalClient
{
	private const TIMEOUT_SECONDS = 10;
	private const USERS_FOLDER = 'users';

	private string $baseUrl;
	private string $bearerToken;
	private string $projectId;
	private string $environment;

	public function __construct(
		?string $apiUrl = null,
		?string $token = null,
		?string $projectId = null,
		?string $environment = null,
	) {
		$apiUrl = $apiUrl ?? (getenv('INFISICAL_API_URL') ?: 'http://127.0.0.1:8075');
		$this->baseUrl = rtrim($apiUrl, '/');
		$this->bearerToken = $token ?? (getenv('INFISICAL_API_TOKEN') ?: '');
		$this->projectId = $projectId ?? (getenv('INFISICAL_USERS_PROJECT_ID') ?: '');
		$this->environment = $environment ?? (getenv('INFISICAL_USERS_ENVIRONMENT') ?: 'prod');
	}

	/**
	 * True when token + project_id are both set. Presenters use this to
	 * render a calibrated diagnostic ("Infisical not yet bootstrapped —
	 * see docs/invite-provisioning.md") instead of attempting the call
	 * and surfacing 401/422 to the operator.
	 */
	public function isConfigured(): bool
	{
		return $this->bearerToken !== '' && $this->projectId !== '';
	}

	// ── Writes ───────────────────────────────────────────────────────────

	/**
	 * Ensure a `/users/<username>` folder exists inside the configured
	 * project + environment. Idempotent: returns silently if the folder
	 * already exists (Infisical returns HTTP 200 with the existing folder
	 * on duplicate create).
	 *
	 * Parent `/users` folder is also auto-created on first invite.
	 */
	public function createUserFolder(string $username): void
	{
		$this->assertConfigured();
		$this->assertUsernameSafe($username);

		// Step 1: ensure /users parent exists. The seeder doesn't create it;
		// we do it lazily here to keep the surface idempotent.
		$this->createFolderIfMissing(self::USERS_FOLDER, '/');

		// Step 2: create /users/<username>.
		$this->createFolderIfMissing($username, '/' . self::USERS_FOLDER);
	}

	/**
	 * Write (or overwrite) a secret at `/users/<username>/<key>`.
	 * Mirrors seed.py's upsert pattern: POST first; on 4xx (already
	 * exists), PATCH the existing value. Returns the final secret value
	 * the API echoed back.
	 */
	public function upsertSecret(string $username, string $key, string $value): void
	{
		$this->assertConfigured();
		$this->assertUsernameSafe($username);
		$this->assertSecretKeySafe($key);

		$path = '/' . self::USERS_FOLDER . '/' . $username;
		$body = [
			'workspaceId' => $this->projectId,
			'environment' => $this->environment,
			'secretPath'  => $path,
			'secretValue' => $value,
			'type'        => 'shared',
		];

		// POST = create. On 400/409 (already exists), PATCH = update.
		[$code] = $this->request('POST', '/api/v3/secrets/raw/' . rawurlencode($key), $body, allowErrorCodes: [400, 409]);
		if ($code >= 400) {
			$this->request('PATCH', '/api/v3/secrets/raw/' . rawurlencode($key), $body);
		}
	}

	// ── Reads ────────────────────────────────────────────────────────────

	/**
	 * List secret keys present under `/users/<username>/`. Does NOT return
	 * values — the UI shows the operator which credentials have been
	 * provisioned, but the actual values are fetched via the Infisical
	 * webadmin or CLI (operator-only consumption path).
	 *
	 * @return list<string> secret key names
	 */
	public function listUserSecrets(string $username): array
	{
		$this->assertConfigured();
		$this->assertUsernameSafe($username);

		$path = '/' . self::USERS_FOLDER . '/' . $username;
		$query = http_build_query([
			'workspaceId' => $this->projectId,
			'environment' => $this->environment,
			'secretPath'  => $path,
		]);
		[$code, $body] = $this->request('GET', '/api/v3/secrets/raw?' . $query, null, allowErrorCodes: [404]);
		if ($code === 404) {
			return [];
		}
		$secrets = $body['secrets'] ?? [];
		$keys = [];
		foreach ($secrets as $s) {
			$key = $s['secretKey'] ?? null;
			if (is_string($key) && $key !== '') {
				$keys[] = $key;
			}
		}
		return $keys;
	}

	// ── Internals ────────────────────────────────────────────────────────

	private function createFolderIfMissing(string $name, string $path): void
	{
		// POST returns 200 on create, 409 (or similar) if duplicate.
		// We tolerate both so the surface is idempotent across re-runs.
		[$code] = $this->request(
			'POST',
			'/api/v2/folders',
			[
				'projectId'   => $this->projectId,
				'environment' => $this->environment,
				'name'        => $name,
				'path'        => $path,
			],
			allowErrorCodes: [400, 409],
		);
		if ($code >= 400 && $code !== 409 && $code !== 400) {
			throw new RuntimeException("InfisicalClient: createFolder {$path}/{$name} HTTP {$code}");
		}
	}

	private function assertConfigured(): void
	{
		if (!$this->isConfigured()) {
			throw new RuntimeException(
				'InfisicalClient: INFISICAL_API_TOKEN + INFISICAL_USERS_PROJECT_ID '
				. 'must be set. Run the playbook with install_infisical=true and '
				. 'see docs/invite-provisioning.md for the bootstrap steps.',
			);
		}
	}

	/**
	 * Username goes into Infisical paths + Bone audit events; reject anything
	 * that could escape the path (slash, traversal, control chars). Mirrors
	 * the Authentik invitation flow's slug rules.
	 */
	private function assertUsernameSafe(string $username): void
	{
		if ($username === '' || !preg_match('/^[a-z0-9][a-z0-9._-]{0,62}$/', $username)) {
			throw new RuntimeException("InfisicalClient: unsafe username: {$username}");
		}
	}

	/**
	 * Secret-key naming convention: snake_case, max 64 chars. Rejects
	 * anything that could collide with Infisical's internal columns.
	 */
	private function assertSecretKeySafe(string $key): void
	{
		if ($key === '' || !preg_match('/^[a-z][a-z0-9_]{0,63}$/', $key)) {
			throw new RuntimeException("InfisicalClient: unsafe secret key: {$key}");
		}
	}

	/**
	 * JSON-in, JSON-out HTTP request.
	 *
	 * @param  list<int>  $allowErrorCodes  HTTP codes that should NOT throw
	 *                                       — instead the caller inspects
	 *                                       the returned code (used for the
	 *                                       upsert / already-exists pattern).
	 * @return array{0:int,1:array<string,mixed>}  (status_code, decoded_body)
	 */
	private function request(
		string $method,
		string $path,
		?array $body = null,
		array $allowErrorCodes = [],
	): array {
		$url = $this->baseUrl . $path;
		$ch = curl_init($url);
		if ($ch === false) {
			throw new RuntimeException('curl_init failed for ' . $url);
		}

		$headers = [
			'Authorization: Bearer ' . $this->bearerToken,
			'Accept: application/json',
		];
		curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $method);
		curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
		curl_setopt($ch, CURLOPT_TIMEOUT, self::TIMEOUT_SECONDS);
		curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 5);

		if ($body !== null) {
			$json = json_encode($body, JSON_THROW_ON_ERROR);
			curl_setopt($ch, CURLOPT_POSTFIELDS, $json);
			$headers[] = 'Content-Type: application/json';
		}
		curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);

		$raw = curl_exec($ch);
		$code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
		$err = curl_error($ch);
		// PHP 8.5 deprecated curl_close(); $ch falls out of scope on unset.
		unset($ch);

		if ($raw === false) {
			throw new RuntimeException("Infisical {$method} {$path}: curl error: {$err}");
		}
		if ($code === 204 || $raw === '') {
			return [$code, []];
		}
		$decoded = json_decode((string) $raw, true);
		if (!is_array($decoded)) {
			$decoded = ['raw' => substr((string) $raw, 0, 500)];
		}
		if ($code >= 400 && !in_array($code, $allowErrorCodes, true)) {
			throw new RuntimeException(
				"Infisical {$method} {$path}: HTTP {$code}: " . substr((string) $raw, 0, 500),
			);
		}
		return [$code, $decoded];
	}
}
