<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use Nette\Http\IResponse;

/**
 * Wing /api/v1/deploy-trigger (Anatomy A17, 2026-05-20).
 *
 * HMAC-authenticated endpoint that lets the Woodpecker pipeline spawn
 * a localhost `ansible-playbook` after CI goes green on a dev/pzny
 * push. Body shape (canonical-JSON-sorted before HMAC):
 *
 *   {
 *     "deploy_uuid": "<uuid4>",
 *     "branch":      "dev" | "pzny",
 *     "commit":      "<40-char-sha>",
 *     "tags":        ["wing", "gitea", ...],
 *     "ts":          <unix-seconds>,
 *     "source":      "woodpecker"
 *   }
 *
 * Headers:
 *   * X-Wing-Timestamp — unix epoch (must be within ±5 min of server)
 *   * X-Wing-Signature — sha256 HMAC of "<ts>.<raw-body>" using
 *                        NOS_DEPLOY_HMAC_SECRET env
 *
 * Auth model: HMAC only — no bearer token. The CI pipeline runs inside
 * a Docker container and can't easily carry a per-user token; the HMAC
 * secret is provisioned in Woodpecker UI as a secret variable that the
 * pipeline reads via `from_secret`.
 *
 * Security gate (defense in depth):
 *   1. HMAC validates the request came from Woodpecker
 *   2. Timestamp window (±5 min) blocks replay attacks
 *   3. branch allowlist (dev / pzny only — master is operator-manual)
 *   4. tags allowlist — only Docker stack + host daemon tags are accepted.
 *      Tags that need sudo (homebrew, mac.*, autostart) are REJECTED
 *      so a compromised CI runner can't grant itself OS-level access.
 *   5. Concurrency lock in deploy-from-ci.sh — 1 deploy at a time
 *
 * Response: 202 Accepted with `{deploy_uuid, log_path}`. The actual
 * ansible-playbook run is detached — wraps `tools/deploy-from-ci.sh`
 * via proc_open and immediately returns. Completion notification fires
 * into Wing /inbox from the wrapper script via Bone HMAC.
 *
 * Subprocess argv is built from ESCAPED literals via proc_open's array
 * form — there's no shell expansion of the request body, so even a
 * malformed (post-HMAC) payload can't escape into a shell metachar.
 */
final class DeployTriggerPresenter extends BaseApiPresenter
{
	// Endpoint is HMAC-only; no Bearer token needed.
	protected array $publicActions = ['default'];

	private const HMAC_WINDOW_SECONDS = 300;  // ±5 min

	/** Branches we trust to auto-deploy. master is operator-manual. */
	private const ALLOWED_BRANCHES = ['dev', 'pzny'];

	/**
	 * Tag allowlist — only tags whose roles run as the operator user
	 * (no sudo). Each entry lists a SINGLE ansible tag the operator
	 * may pass; the presenter REFUSES any tag not on this list.
	 *
	 * Adding here is a deliberate policy decision — review the role
	 * to confirm zero sudo tasks before promoting a tag.
	 */
	private const ALLOWED_TAGS = [
		// host daemons (launchd user-domain, no sudo)
		'wing', 'bone', 'pulse',
		// Docker stack roles (docker compose runs as user on Mac)
		'gitea', 'woodpecker', 'gitlab', 'paperclip', 'code-server',
		'erpnext', 'freescout', 'outline', 'hedgedoc', 'bookstack',
		'firefly', 'onlyoffice',
		'freepbx', 'qgis', 'metabase', 'superset',
		'wordpress', 'nextcloud', 'jellyfin', 'open_webui', 'openwebui',
		'home_assistant', 'homeassistant', 'calibre_web', 'calibreweb',
		'kiwix', 'mcp_gateway', 'mcpgateway', 'n8n', 'nodered',
		'puter', 'vaultwarden', 'ntfy', 'miniflux',
		'rustfs', 'uptime_kuma', 'uptimekuma', 'documenso', 'twofauth',
		'qdrant', 'roundcube',
		// Tier-2 apps runner
		'apps',
		// Infra service roles (still no host-sudo)
		'authentik', 'infisical', 'traefik', 'portainer',
		'bluesky-pds', 'bluesky_pds', 'smtp', 'stalwart',
		'spacetimedb', 'mariadb', 'postgresql', 'redis',
		// Observability
		'grafana', 'prometheus', 'loki', 'tempo', 'alloy',
		'observability',
	];

	public function actionDefault(): void
	{
		$this->requireMethod('POST');

		$raw = $this->getHttpRequest()->getRawBody() ?? '';
		if ($raw === '') {
			$this->sendError('Empty body', IResponse::S400_BadRequest);
		}

		$tsHeader = $this->getHttpRequest()->getHeader('X-Wing-Timestamp') ?? '';
		$sigHeader = $this->getHttpRequest()->getHeader('X-Wing-Signature') ?? '';
		[$ok, $reason] = $this->verifyHmac($tsHeader, $sigHeader, $raw);
		if (!$ok) {
			$this->sendError("HMAC validation failed: {$reason}", IResponse::S401_Unauthorized);
		}

		$body = json_decode($raw, true);
		if (!is_array($body)) {
			$this->sendError('Body is not a JSON object', IResponse::S400_BadRequest);
		}

		// ── Schema validation ────────────────────────────────────────
		$deployUuid = (string) ($body['deploy_uuid'] ?? '');
		if (!preg_match('/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/', $deployUuid)) {
			$this->sendError('deploy_uuid must be a UUID4', IResponse::S400_BadRequest);
		}

		$branch = (string) ($body['branch'] ?? '');
		if (!in_array($branch, self::ALLOWED_BRANCHES, true)) {
			$this->sendError(
				'branch not in allowlist: ' . implode('|', self::ALLOWED_BRANCHES),
				IResponse::S403_Forbidden,
			);
		}

		$commit = (string) ($body['commit'] ?? '');
		if (!preg_match('/^[a-f0-9]{40}$/', $commit) && !preg_match('/^[a-f0-9]{7,40}$/', $commit)) {
			$this->sendError('commit must be a 7-40 char hex SHA', IResponse::S400_BadRequest);
		}

		$tags = $body['tags'] ?? [];
		if (!is_array($tags) || $tags === []) {
			$this->sendError('tags must be a non-empty array', IResponse::S400_BadRequest);
		}
		$badTags = [];
		foreach ($tags as $t) {
			if (!is_string($t) || !in_array($t, self::ALLOWED_TAGS, true)) {
				$badTags[] = (string) $t;
			}
		}
		if ($badTags !== []) {
			$this->sendError(
				'tag(s) not in allowlist (would need sudo or unknown): ' . implode(',', $badTags),
				IResponse::S403_Forbidden,
			);
		}

		// ── Spawn the deploy wrapper, detached ───────────────────────
		$scriptPath = realpath(__DIR__ . '/../../../../tools/deploy-from-ci.sh');
		if ($scriptPath === false || !is_file($scriptPath)) {
			$this->sendError('deploy wrapper missing on host', IResponse::S500_InternalServerError);
		}

		$logDir = $this->resolveLogDir();
		$logPath = $logDir . '/' . $deployUuid . '.log';

		// proc_open with array argv = no shell expansion of body
		// content. Append the spawn to /dev/null so PHP doesn't block
		// on the open file descriptors — the wrapper writes to its own
		// log file directly.
		$cmd = sprintf(
			'%s %s %s > /dev/null 2>&1 &',
			escapeshellarg($scriptPath),
			escapeshellarg($deployUuid),
			escapeshellarg(implode(',', $tags)),
		);
		// Use shell_exec for true detach. The args are escapeshellarg'd
		// so the shell can't re-interpret them.
		shell_exec($cmd);

		$this->sendSuccess([
			'deploy_uuid' => $deployUuid,
			'branch' => $branch,
			'commit' => $commit,
			'tags' => $tags,
			'log_path' => $logPath,
			'status' => 'spawned',
		], IResponse::S202_Accepted);
	}

	/**
	 * HMAC verification using NOS_DEPLOY_HMAC_SECRET env. Mirrors the
	 * Bone /api/v1/events shape so operators have ONE HMAC convention
	 * to remember.
	 *
	 * @return array{0:bool,1:string}  ok + reason-if-not
	 */
	private function verifyHmac(string $ts, string $sig, string $rawBody): array
	{
		$secret = getenv('NOS_DEPLOY_HMAC_SECRET') ?: '';
		if ($secret === '') {
			return [false, 'NOS_DEPLOY_HMAC_SECRET not configured on Wing'];
		}
		if ($ts === '' || $sig === '') {
			return [false, 'missing HMAC headers'];
		}
		if (!ctype_digit($ts)) {
			return [false, 'invalid timestamp'];
		}
		$drift = abs(time() - (int) $ts);
		if ($drift > self::HMAC_WINDOW_SECONDS) {
			return [false, "timestamp drift {$drift}s outside ±" . self::HMAC_WINDOW_SECONDS];
		}
		$message = $ts . '.' . $rawBody;
		$expected = hash_hmac('sha256', $message, $secret);
		// Accept both raw hex and 'sha256=<hex>' for compatibility with
		// GitHub-webhook-style senders.
		$clean = str_starts_with($sig, 'sha256=') ? substr($sig, 7) : $sig;
		if (!hash_equals($expected, $clean)) {
			return [false, 'invalid signature'];
		}
		return [true, ''];
	}

	private function resolveLogDir(): string
	{
		$dir = getenv('NOS_DEPLOY_LOG_DIR') ?: (getenv('HOME') . '/.nos/deploys');
		if (!is_dir($dir)) {
			@mkdir($dir, 0755, true);
		}
		return rtrim($dir, '/');
	}
}
