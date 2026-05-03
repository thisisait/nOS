<?php

declare(strict_types=1);

namespace App\Bootstrap;

use Nette\Bootstrap\Configurator;

class Booting
{
	public static function boot(): Configurator
	{
		$configurator = new Configurator;
		$appDir = dirname(__DIR__);

		$configurator->setDebugMode('127.0.0.1');
		$configurator->enableTracy($appDir . '/../log');
		$configurator->setTempDirectory($appDir . '/../temp');

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
