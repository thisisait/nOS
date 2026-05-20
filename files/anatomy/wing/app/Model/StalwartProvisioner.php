<?php

declare(strict_types=1);

namespace App\Model;

use RuntimeException;

/**
 * Stalwart Mail Server JMAP management client (Anatomy A18 invite-
 * provisioning, 2026-05-20).
 *
 * Provisions individual user mailboxes via Stalwart's JMAP management
 * API (v0.16+, where REST was replaced with JMAP at /jmap). One method
 * call: createMailbox(localPart, domain, password) → Principal/set
 * methodCall over POST /jmap with HTTP Basic auth on the admin creds.
 *
 * Why not REST: Stalwart v0.16.0 (2026-04-20) replaced the legacy REST
 * management API with JMAP entirely. v0.11.8 (our pre-A18 pin) had REST
 * but is 14+ months stale; A18 bundle bumps to v0.16.6 to get the
 * documented, RFC-spec'd surface. Both the WebUI and `stalwart-cli`
 * are now thin wrappers over /jmap.
 *
 * Wire format (single methodCall):
 *
 *     POST http://127.0.0.1:8080/jmap
 *     Authorization: Basic base64(admin:password)
 *     Content-Type: application/json
 *
 *     {
 *       "using": ["urn:stalwart:jmap"],
 *       "methodCalls": [[
 *         "Principal/set",
 *         {
 *           "create": {
 *             "m0": {
 *               "name": "alice@pazny.eu",
 *               "type": "individual",
 *               "secrets": ["<generated_password>"]
 *             }
 *           }
 *         },
 *         "c0"
 *       ]]
 *     }
 *
 * Response (success):
 *
 *     {
 *       "methodResponses": [[
 *         "Principal/set",
 *         { "created": { "m0": { "id": "<uuid>", ... } }, "notCreated": null },
 *         "c0"
 *       ]],
 *       "sessionState": "<state>"
 *     }
 *
 * Graceful degradation: when isConfigured() == false (admin creds missing
 * or install_smtp_stalwart=false), every method throws RuntimeException
 * with a calibrated "Stalwart not deployed — see docs/invite-provisioning.
 * md §Cesta C fallback" diagnostic. Callers (UsersPresenter) trap and
 * downgrade the invite flow to Infisical-only.
 */
final class StalwartProvisioner
{
	private const TIMEOUT_SECONDS = 10;
	private const JMAP_PATH = '/jmap';
	private const JMAP_USING = ['urn:stalwart:jmap'];

	private string $baseUrl;
	private string $adminUser;
	private string $adminPassword;

	public function __construct(
		?string $apiUrl = null,
		?string $adminUser = null,
		?string $adminPassword = null,
	) {
		$apiUrl = $apiUrl ?? (getenv('STALWART_API_URL') ?: 'http://127.0.0.1:8080');
		$this->baseUrl = rtrim($apiUrl, '/');
		$this->adminUser = $adminUser ?? (getenv('STALWART_ADMIN_USER') ?: '');
		$this->adminPassword = $adminPassword ?? (getenv('STALWART_ADMIN_PASSWORD') ?: '');
	}

	/**
	 * True when admin user + password are both set. Presenters use this
	 * to render a calibrated diagnostic rather than attempting a JMAP
	 * call against a Stalwart instance that doesn't exist on this host.
	 */
	public function isConfigured(): bool
	{
		return $this->adminUser !== '' && $this->adminPassword !== '';
	}

	/**
	 * Create a new mailbox for the given local-part + domain with the
	 * supplied password. Returns the Stalwart principal ID (UUID) on
	 * success.
	 *
	 * The operator-facing identity is `<localPart>@<domain>`; Stalwart's
	 * Principal/set creates the IMAP/SMTP account under that name. The
	 * password becomes the user's IMAP / SMTP-submission credential —
	 * stored hashed in Stalwart's own DB, never persisted to wing.db.
	 */
	public function createMailbox(string $localPart, string $domain, string $password): string
	{
		$this->assertConfigured();
		$this->assertLocalPartSafe($localPart);
		$this->assertDomainSafe($domain);
		if ($password === '' || strlen($password) < 12) {
			throw new RuntimeException('StalwartProvisioner: password must be ≥12 chars');
		}

		$email = $localPart . '@' . $domain;
		$body = [
			'using' => self::JMAP_USING,
			'methodCalls' => [[
				'Principal/set',
				[
					'create' => [
						'm0' => [
							'name'    => $email,
							'type'    => 'individual',
							'secrets' => [$password],
						],
					],
				],
				'c0',
			]],
		];

		$response = $this->request($body);

		// methodResponses is a list of [method, args, callId] triples.
		$methodResponses = $response['methodResponses'] ?? [];
		if (!is_array($methodResponses) || count($methodResponses) === 0) {
			throw new RuntimeException(
				'StalwartProvisioner: Principal/set returned no methodResponses',
			);
		}
		$first = $methodResponses[0] ?? null;
		if (!is_array($first) || count($first) < 2 || !is_array($first[1])) {
			throw new RuntimeException(
				'StalwartProvisioner: malformed methodResponses[0]',
			);
		}
		$args = $first[1];

		// notCreated is the Stalwart error path. Stalwart echoes the
		// existing principal's `name` and other metadata in $err which
		// would leak peer-user identities into the caller's exception →
		// Wing /events row → /audit log → launchd.err.log. Surface a
		// calibrated reason code instead. The full $err is available in
		// Stalwart's own logs for the operator to inspect privately.
		$notCreated = $args['notCreated'] ?? null;
		if (is_array($notCreated) && isset($notCreated['m0'])) {
			$err = $notCreated['m0'];
			$reason = 'unknown';
			if (is_array($err) && isset($err['type'])) {
				// Accept only Stalwart's canonical JMAP error type slugs
				// (alphabetic + underscore). Reject anything else as
				// `unknown` so we never echo back free-form text.
				$type = (string) $err['type'];
				if (preg_match('/^[a-zA-Z][a-zA-Z0-9_]{0,63}$/', $type)) {
					$reason = $type;
				}
			}
			throw new RuntimeException(
				"StalwartProvisioner: Principal/set notCreated (reason={$reason})",
			);
		}

		$created = $args['created'] ?? null;
		if (!is_array($created) || !isset($created['m0']['id'])) {
			throw new RuntimeException(
				'StalwartProvisioner: Principal/set response missing created.m0.id',
			);
		}
		return (string) $created['m0']['id'];
	}

	// ── Internals ────────────────────────────────────────────────────────

	private function assertConfigured(): void
	{
		if (!$this->isConfigured()) {
			throw new RuntimeException(
				'StalwartProvisioner: STALWART_ADMIN_USER + STALWART_ADMIN_PASSWORD '
				. 'must be set. Enable install_smtp_stalwart=true in config.yml and '
				. 'see docs/invite-provisioning.md §Cesta B for the bootstrap path.',
			);
		}
	}

	/**
	 * Stalwart accepts local-parts that match the SMTP standard but Wing
	 * tightens this to the username slug (≤64 chars, alnum + . _ -). Same
	 * pattern InfisicalClient uses so a single username flows through both
	 * paths without re-validation downstream.
	 *
	 * Tightened 2026-05-20: rejects `..` substring (RFC 5321 forbids
	 * consecutive dots in the local-part anyway, and downstream consumers
	 * could canonicalize `..` as parent traversal).
	 */
	private function assertLocalPartSafe(string $local): void
	{
		if ($local === '' || !preg_match('/^[a-z0-9][a-z0-9._-]{0,62}$/', $local)) {
			throw new RuntimeException("StalwartProvisioner: unsafe local-part");
		}
		if (str_contains($local, '..')) {
			throw new RuntimeException("StalwartProvisioner: unsafe local-part (consecutive dots)");
		}
	}

	private function assertDomainSafe(string $domain): void
	{
		if ($domain === '' || !preg_match('/^[a-z0-9][a-z0-9.-]{0,253}\.[a-z]{2,63}$/i', $domain)) {
			throw new RuntimeException("StalwartProvisioner: unsafe domain: {$domain}");
		}
	}

	/**
	 * Single JMAP POST. Stalwart accepts HTTP Basic on admin creds for
	 * the management JMAP scope (per v0.16 docs). Bearer tokens via
	 * `POST /api/auth` are an alternative but require an extra round-trip;
	 * Basic is simpler for a server-internal call over 127.0.0.1.
	 *
	 * @param  array<string,mixed>  $body  JMAP envelope
	 * @return array<string,mixed>         decoded response
	 */
	private function request(array $body): array
	{
		$url = $this->baseUrl . self::JMAP_PATH;
		$ch = curl_init($url);
		if ($ch === false) {
			throw new RuntimeException('curl_init failed for ' . $url);
		}

		$json = json_encode($body, JSON_THROW_ON_ERROR);
		curl_setopt($ch, CURLOPT_CUSTOMREQUEST, 'POST');
		curl_setopt($ch, CURLOPT_POSTFIELDS, $json);
		curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
		curl_setopt($ch, CURLOPT_TIMEOUT, self::TIMEOUT_SECONDS);
		curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 5);
		curl_setopt($ch, CURLOPT_HTTPHEADER, [
			'Content-Type: application/json',
			'Accept: application/json',
		]);
		curl_setopt($ch, CURLOPT_HTTPAUTH, CURLAUTH_BASIC);
		curl_setopt($ch, CURLOPT_USERPWD, $this->adminUser . ':' . $this->adminPassword);

		$raw = curl_exec($ch);
		$code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
		$err = curl_error($ch);
		unset($ch);

		if ($raw === false) {
			throw new RuntimeException("Stalwart JMAP curl error: {$err}");
		}
		if ($code >= 400) {
			// Drop the body — Stalwart's notCreated response can echo
			// existing principal names (i.e. other users' emails); we
			// must not let that propagate into Wing's /events row +
			// /audit log + host launchd.err.log. The HTTP code is
			// enough for diagnostics; full response in Stalwart's logs.
			throw new RuntimeException(
				"Stalwart JMAP HTTP {$code} (body suppressed; check Stalwart logs)",
			);
		}
		$decoded = json_decode((string) $raw, true);
		if (!is_array($decoded)) {
			throw new RuntimeException(
				'Stalwart JMAP: non-JSON response (body suppressed)',
			);
		}
		return $decoded;
	}
}
