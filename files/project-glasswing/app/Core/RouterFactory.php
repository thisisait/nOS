<?php

declare(strict_types=1);

namespace App\Core;

use Nette;
use Nette\Application\Routers\RouteList;

final class RouterFactory
{
	use Nette\StaticClass;

	public static function createRouter(): RouteList
	{
		$router = new RouteList;

		// API v1 routes (must be before dashboard catch-all)
		$api = $router->withModule('Api');
		$api->addRoute('api/v1/dashboard/summary', 'Dashboard:summary');
		$api->addRoute('api/v1/dashboard/timeline', 'Dashboard:timeline');
		$api->addRoute('api/v1/components[/<id>]', 'Components:default');
		$api->addRoute('api/v1/scan/state', 'Scan:state');
		$api->addRoute('api/v1/scan/cycles', 'Scan:cycles');
		$api->addRoute('api/v1/scan/cycle', 'Scan:cycle');
		$api->addRoute('api/v1/scan/component/<id>', 'Scan:component');
		$api->addRoute('api/v1/scan/config', 'Scan:config');
		$api->addRoute('api/v1/scan/rotation', 'Scan:rotation');
		$api->addRoute('api/v1/scan/probe/<name>/complete', 'Scan:probeComplete');
		$api->addRoute('api/v1/advisories[/<id>]', 'Advisories:default');
		$api->addRoute('api/v1/remediation/bulk-status', 'Remediation:bulkStatus');
		$api->addRoute('api/v1/remediation/next-id', 'Remediation:nextId');
		$api->addRoute('api/v1/remediation[/<id>]', 'Remediation:default');
		$api->addRoute('api/v1/pentest/patches[/<id>]', 'Pentest:patches');
		$api->addRoute('api/v1/pentest/findings/<id>', 'Pentest:findingUpdate');
		$api->addRoute('api/v1/pentest/targets/<id>/areas-tested', 'Pentest:areasTested');
		$api->addRoute('api/v1/pentest/targets/<id>/areas-planned', 'Pentest:areasPlanned');
		$api->addRoute('api/v1/pentest/targets/<id>/findings', 'Pentest:findings');
		$api->addRoute('api/v1/pentest/targets[/<id>]', 'Pentest:targets');

		// Hub API (public — service names/ports are non-sensitive, nginx still
		// gates the /hub browser page behind Authentik proxy auth)
		$api->addRoute('api/v1/hub/systems[/<id>]', 'Hub:systems');
		$api->addRoute('api/v1/hub/health', 'Hub:health');

		// State & Migration Framework API (agent 7)
		// Events: POST = ingestion (HMAC), GET = paginated query (bearer).
		$api->addRoute('api/v1/events', 'Events:default');
		$api->addRoute('api/v1/state/services[/<id>]', 'State:services');
		$api->addRoute('api/v1/state/sync', 'State:sync');
		$api->addRoute('api/v1/state', 'State:default');
		$api->addRoute('api/v1/migrations/<id>/preview', 'Migrations:preview');
		$api->addRoute('api/v1/migrations/<id>/apply', 'Migrations:apply');
		$api->addRoute('api/v1/migrations/<id>/rollback', 'Migrations:rollback');
		$api->addRoute('api/v1/migrations[/<id>]', 'Migrations:default');
		$api->addRoute('api/v1/upgrades/history', 'Upgrades:history');
		$api->addRoute('api/v1/upgrades/<service>/<recipe>/plan', 'Upgrades:plan');
		$api->addRoute('api/v1/upgrades/<service>/<recipe>/apply', 'Upgrades:apply');
		$api->addRoute('api/v1/upgrades/<service>/<recipe>', 'Upgrades:recipe');
		$api->addRoute('api/v1/upgrades/<service>', 'Upgrades:service');
		$api->addRoute('api/v1/upgrades', 'Upgrades:default');
		$api->addRoute('api/v1/coexistence/<service>/provision', 'Coexistence:provision');
		$api->addRoute('api/v1/coexistence/<service>/cutover', 'Coexistence:cutover');
		$api->addRoute('api/v1/coexistence/<service>/cleanup/<tag>', 'Coexistence:cleanup');
		$api->addRoute('api/v1/coexistence', 'Coexistence:default');

		// Public homepage (no auth — nginx exempts exact /)
		$router->addRoute('', 'Homepage:default');

		// Dashboard routes (browser, behind Authentik proxy auth)
		$router->addRoute('hub', 'Hub:default');
		$router->addRoute('dashboard', 'Dashboard:default');
		$router->addRoute('pentest', 'Pentest:default');
		$router->addRoute('remediation', 'Remediation:default');
		$router->addRoute('help', 'Help:default');

		// State & Migration Framework browser routes (agent 7)
		$router->addRoute('migrations/<id>', 'Migrations:detail');
		$router->addRoute('migrations', 'Migrations:default');
		$router->addRoute('upgrades/<service>', 'Upgrades:service');
		$router->addRoute('upgrades', 'Upgrades:default');
		$router->addRoute('timeline', 'Timeline:default');
		$router->addRoute('coexistence', 'Coexistence:default');

		return $router;
	}
}
