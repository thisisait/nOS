<?php

declare(strict_types=1);

namespace App\Bootstrap;

use Nette\Bootstrap\Configurator;
use Tracy\Debugger;

class Booting
{
	/**
	 * Env var name substrings that mark a sensitive value. Tracy's
	 * BlueScreen + log dumper consult this list at exception-render
	 * time and replace matching keys' values with `***` in the dump.
	 *
	 * SEC-2 (2026-05-23): expanded from Tracy's stock list (which
	 * covers `password`, `authorization`, `php-auth-pw` only) to also
	 * mask every nOS-specific secret env key. Pre-SEC-2, Wing's
	 * exception HTMLs in ~/wing/app/log/exception--*.html (mode 0644
	 * → world-readable to local UIDs) dumped live values of
	 * WING_API_TOKEN, BONE_SECRET, AUTHENTIK_BOOTSTRAP_TOKEN,
	 * INFISICAL_API_TOKEN, STALWART_ADMIN_PASSWORD,
	 * NOS_DEPLOY_HMAC_SECRET, WING_EVENTS_HMAC_SECRET.
	 *
	 * Pattern matching is substring-case-insensitive (Tracy's stock
	 * behavior). Order doesn't matter.
	 */
	private const SECRET_KEY_SUBSTRINGS = [
		'password',
		'authorization',
		'php-auth-pw',
		'token',           // *_TOKEN, *_token, hmac_token
		'secret',          // *_SECRET, *_secret
		'api_key',         // generic
		'apikey',
		'key',             // *_KEY (e.g. APP_KEY, NOS_DEPLOY_HMAC_SECRET via "key" substring)
		'hmac',
		'jwt',
		'bearer',
		'credentials',
		'salt',
		'pepper',
		'cookie',          // session cookies in $_COOKIE dump
		'session_id',
		'sessid',
	];

	public static function boot(): Configurator
	{
		$configurator = new Configurator;
		$appDir = dirname(__DIR__);

		$configurator->setDebugMode('127.0.0.1');
		$configurator->enableTracy($appDir . '/../log');
		$configurator->setTempDirectory($appDir . '/../temp');

		// SEC-2: extend Tracy's secret-redaction list BEFORE the first
		// exception can fire. `enableTracy` above registered the
		// debugger; setting $keysToHide afterwards still applies because
		// Tracy reads the property at dump time, not at register time.
		Debugger::$keysToHide = array_merge(
			Debugger::$keysToHide,
			self::SECRET_KEY_SUBSTRINGS,
		);

		$configurator->createRobotLoader()
			->addDirectory($appDir)
			->register();

		$configurator->addConfig($appDir . '/config/common.neon');

		$localConfig = $appDir . '/config/local.neon';
		if (is_file($localConfig)) {
			$configurator->addConfig($localConfig);
		}

		return $configurator;
	}
}
