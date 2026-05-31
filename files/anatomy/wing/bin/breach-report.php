<?php

declare(strict_types=1);

/**
 * Wing — render a GDPR Art-33/34 + NÚKIB/ZKB regulator report for one breach.
 *
 * Usage:
 *   php bin/breach-report.php --id=<n> [--format=md|json]
 *
 * Env (Art-33(3)(b) controller identity): GDPR_CONTROLLER_NAME,
 *   GDPR_DPO_NAME, GDPR_DPO_CONTACT.
 *
 * Exit codes: 0 ok · 1 bad args · 3 not found / DB error.
 */

require __DIR__ . '/../vendor/autoload.php';

$id = null;
$fmt = 'md';
foreach ($argv as $a) {
    if (str_starts_with($a, '--id=')) {
        $id = (int) substr($a, 5);
    } elseif (str_starts_with($a, '--format=')) {
        $fmt = substr($a, 9);
    }
}
if (!$id) {
    fwrite(STDERR, "Usage: php bin/breach-report.php --id=<n> [--format=md|json]\n");
    exit(1);
}
if (!in_array($fmt, ['md', 'json'], true)) {
    fwrite(STDERR, "--format must be md or json\n");
    exit(1);
}

try {
    $container = App\Bootstrap\Booting::boot()->createContainer();
} catch (\Throwable $e) {
    fwrite(STDERR, "Container boot failed: " . $e->getMessage() . "\n");
    exit(3);
}
/** @var App\Model\GdprRepository $repo */
$repo = $container->getByType(App\Model\GdprRepository::class);

$b = $repo->getBreach($id);
if (!$b) {
    fwrite(STDERR, "breach #{$id} not found\n");
    exit(3);
}

// Assembly + markdown live in App\Model\BreachReport so this CLI and the web
// API (Api\GdprPresenter::actionBreachReport) render byte-identically.
$report = App\Model\BreachReport::build($b);

if ($fmt === 'json') {
    echo json_encode($report, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE), "\n";
    exit(0);
}
echo App\Model\BreachReport::renderMarkdown($report);
exit(0);
