<?php

declare(strict_types=1);

/**
 * Glasswing — Ingest service-registry.json into systems table.
 *
 * Usage:
 *   php bin/ingest-registry.php --registry=/path/to/service-registry.json
 *
 * Called by pazny.glasswing Ansible role after deploy + schema init.
 * Idempotent — re-running updates existing entries, never duplicates.
 */

require __DIR__ . '/../vendor/autoload.php';

$registryPath = null;
foreach ($argv as $arg) {
	if (str_starts_with($arg, '--registry=')) {
		$registryPath = substr($arg, 11);
	}
}

if (!$registryPath) {
	// Default: ~/projects/default/service-registry.json
	$home = getenv('HOME') ?: '/tmp';
	$registryPath = $home . '/projects/default/service-registry.json';
}

if (!is_file($registryPath)) {
	echo "Registry file not found: $registryPath\n";
	echo "Run: ansible-playbook main.yml --tags service-registry\n";
	exit(1);
}

// Boot Nette container to get DB connection
$container = App\Bootstrap\Booting::boot()->createContainer();

/** @var App\Model\SystemRepository $repo */
$repo = $container->getByType(App\Model\SystemRepository::class);

$result = $repo->ingestRegistry($registryPath);

$merged = $result['merged'] ?? 0;
echo "Ingested {$result['imported']} systems, created {$result['stacks_created']} stack parents, merged $merged duplicates\n";
echo "Registry: $registryPath\n";
