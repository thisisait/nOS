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

		// Public homepage (no auth — nginx exempts exact /)
		$router->addRoute('', 'Homepage:default');

		// Dashboard routes (browser, behind Authentik proxy auth)
		$router->addRoute('dashboard', 'Dashboard:default');
		$router->addRoute('pentest', 'Pentest:default');
		$router->addRoute('remediation', 'Remediation:default');
		$router->addRoute('help', 'Help:default');

		return $router;
	}
}
