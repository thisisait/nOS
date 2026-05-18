<?php

declare(strict_types=1);

namespace App\Model;

use RuntimeException;

/**
 * Authentik admin-API client (Anatomy A15, 2026-05-17).
 *
 * Thin HTTP wrapper around https://<AUTHENTIK_DOMAIN>/api/v3/. Reads the
 * bearer token from the AUTHENTIK_BOOTSTRAP_TOKEN env (operator-provisioned
 * `nos-api` token on the Authentik side; the same one the playbook uses for
 * blueprint reconvergence + PDS bridge). All methods return decoded arrays
 * or throw RuntimeException with the Authentik error body wrapped — the
 * caller surfaces the failure to the operator instead of swallowing it.
 *
 * Why a separate model vs. AgentIdentity:
 *   * AgentIdentity does client_credentials OIDC against
 *     /application/o/token/ — that gives a SCOPED token for Bone proxying.
 *   * The bootstrap admin token is a long-lived `intent: api` row on the
 *     akadmin user and unlocks the full /api/v3 surface (users, groups,
 *     applications, invitations) — which is what the /users presenter
 *     needs. Mixing the two would either widen agent scopes (bad) or
 *     leave the presenter without admin reach (broken).
 *
 * Scope of methods (intentionally small — grows when a presenter needs more):
 *   * listUsers(query?, page?)         — GET /core/users/?include_groups=true
 *   * listGroups()                     — GET /core/groups/
 *   * listApplications()               — GET /core/applications/
 *   * listEnrollmentFlows()            — GET /flows/instances/?designation=enrollment
 *   * findUserByPk(pk)                 — GET /core/users/{pk}/
 *   * createInvitation(...)            — POST /stages/invitation/invitations/
 *   * deleteInvitation(pk)             — DELETE /stages/invitation/invitations/{pk}/
 *   * listInvitations()                — GET /stages/invitation/invitations/
 *
 * All list methods follow Authentik pagination automatically (up to 200
 * pages = 20k rows; enough for any realistic operator install).
 */
final class AuthentikClient
{
	private const PAGE_SIZE = 100;
	private const MAX_PAGES = 200;
	private const TIMEOUT_SECONDS = 10;

	private string $baseUrl;
	private string $bearerToken;

	public function __construct(?string $domain = null, ?string $token = null)
	{
		$domain = $domain ?? (getenv('AUTHENTIK_DOMAIN') ?: 'auth.dev.local');
		$token = $token ?? (getenv('AUTHENTIK_BOOTSTRAP_TOKEN') ?: '');

		$this->baseUrl = 'https://' . rtrim($domain, '/') . '/api/v3';
		$this->bearerToken = $token;
	}

	/**
	 * True when a bearer token is configured. Presenters use this to render
	 * a calibrated diagnostic ("operator must run fetch-authentik-bootstrap-
	 * token.py first") instead of bleeding raw HTTP 401s into the UI when
	 * the bootstrap step was skipped on a fresh install.
	 */
	public function isConfigured(): bool
	{
		return $this->bearerToken !== '';
	}

	// ── Reads ─────────────────────────────────────────────────────────────

	/** @return list<array<string,mixed>> */
	public function listUsers(?string $search = null): array
	{
		$query = ['include_groups' => 'true', 'page_size' => self::PAGE_SIZE];
		if ($search !== null && $search !== '') {
			$query['search'] = $search;
		}
		return $this->paginate('/core/users/', $query);
	}

	/** @return list<array<string,mixed>> */
	public function listGroups(): array
	{
		return $this->paginate('/core/groups/', ['page_size' => self::PAGE_SIZE]);
	}

	/** @return list<array<string,mixed>> */
	public function listApplications(): array
	{
		return $this->paginate('/core/applications/', ['page_size' => self::PAGE_SIZE]);
	}

	/** @return list<array<string,mixed>> */
	public function listEnrollmentFlows(): array
	{
		return $this->paginate('/flows/instances/', [
			'designation' => 'enrollment',
			'page_size'   => self::PAGE_SIZE,
		]);
	}

	/** @return list<array<string,mixed>> */
	public function listInvitations(): array
	{
		return $this->paginate('/stages/invitation/invitations/', ['page_size' => self::PAGE_SIZE]);
	}

	/** @return array<string,mixed>|null */
	public function findUserByPk(int $pk): ?array
	{
		try {
			return $this->request('GET', '/core/users/' . $pk . '/');
		} catch (RuntimeException $e) {
			if (str_contains($e->getMessage(), 'HTTP 404')) {
				return null;
			}
			throw $e;
		}
	}

	// ── Writes ────────────────────────────────────────────────────────────

	/**
	 * Create an Authentik invitation. Returns the decoded response which
	 * includes the `pk` (UUID, used as itoken query param) and `expires`
	 * timestamp Authentik finalized.
	 *
	 * @param string $name           Authentik display name (audit-readable)
	 * @param string $flowSlug       Slug of the enrollment flow to wire the invitation to
	 * @param string $expiresIso     ISO8601 absolute expiry
	 * @param bool   $singleUse      Authentik enforces; default true
	 * @param array<string,mixed> $fixedData  Merged into request.context.prompt_data during enrollment
	 * @return array<string,mixed>
	 */
	public function createInvitation(
		string $name,
		string $flowSlug,
		string $expiresIso,
		bool $singleUse = true,
		array $fixedData = [],
	): array {
		// Authentik wants the flow PK, not the slug — look it up once.
		$flowPk = $this->resolveFlowPkBySlug($flowSlug);
		if ($flowPk === null) {
			throw new RuntimeException(
				"Authentik enrollment flow not found: slug={$flowSlug}. Run "
				. "the playbook to converge the nos-enrollment blueprint.",
			);
		}

		return $this->request('POST', '/stages/invitation/invitations/', [
			'name'        => $name,
			'expires'     => $expiresIso,
			'fixed_data'  => $fixedData,
			'single_use'  => $singleUse,
			'flow'        => $flowPk,
		]);
	}

	public function deleteInvitation(string $invitationPk): void
	{
		$this->request('DELETE', '/stages/invitation/invitations/' . $invitationPk . '/');
	}

	/**
	 * Builds the human-shareable invitation URL.
	 *
	 * Authentik resolves invitations via ?itoken=<pk> against an enrollment
	 * flow's executor URL. The base URL is /if/flow/<slug>/.
	 */
	public function buildInvitationUrl(string $flowSlug, string $invitationPk): string
	{
		$domain = parse_url($this->baseUrl, PHP_URL_HOST) ?: 'auth.dev.local';
		return 'https://' . $domain . '/if/flow/' . rawurlencode($flowSlug) . '/?itoken=' . rawurlencode($invitationPk);
	}

	// ── internals ─────────────────────────────────────────────────────────

	private function resolveFlowPkBySlug(string $slug): ?string
	{
		$res = $this->request('GET', '/flows/instances/?' . http_build_query(['slug' => $slug]));
		$results = $res['results'] ?? [];
		if (!is_array($results) || $results === []) {
			return null;
		}
		return (string) ($results[0]['pk'] ?? '');
	}

	/**
	 * @param array<string,mixed> $query
	 * @return list<array<string,mixed>>
	 */
	private function paginate(string $path, array $query): array
	{
		$rows = [];
		$page = 1;
		while ($page <= self::MAX_PAGES) {
			$query['page'] = $page;
			$res = $this->request('GET', $path . '?' . http_build_query($query));
			$results = $res['results'] ?? [];
			if (!is_array($results)) {
				break;
			}
			foreach ($results as $r) {
				if (is_array($r)) {
					$rows[] = $r;
				}
			}
			$pagination = $res['pagination'] ?? null;
			if (!is_array($pagination)) {
				break;
			}
			$next = (int) ($pagination['next'] ?? 0);
			if ($next <= 0 || $next === $page) {
				break;
			}
			$page = $next;
		}
		return $rows;
	}

	/**
	 * @param array<string,mixed>|null $body
	 * @return array<string,mixed>
	 */
	private function request(string $method, string $path, ?array $body = null): array
	{
		if (!$this->isConfigured()) {
			throw new RuntimeException(
				'AuthentikClient: AUTHENTIK_BOOTSTRAP_TOKEN not set. Run '
				. 'tools/fetch-authentik-bootstrap-token.py to provision.',
			);
		}

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
		// PHP 8.0+ closes the handle on $ch destruction; curl_close() was
		// deprecated in 8.5 and raises E_DEPRECATED which FrankenPHP's strict
		// reporting bubbles up as a 500. Letting $ch fall out of scope is
		// the canonical close.
		unset($ch);

		if ($raw === false) {
			throw new RuntimeException("Authentik {$method} {$path}: curl error: {$err}");
		}
		if ($code === 204 || $raw === '') {
			return [];
		}
		if ($code >= 400) {
			throw new RuntimeException(
				"Authentik {$method} {$path}: HTTP {$code}: " . substr((string) $raw, 0, 500),
			);
		}
		$decoded = json_decode((string) $raw, true);
		if (!is_array($decoded)) {
			throw new RuntimeException(
				"Authentik {$method} {$path}: non-JSON body: " . substr((string) $raw, 0, 200),
			);
		}
		return $decoded;
	}
}
