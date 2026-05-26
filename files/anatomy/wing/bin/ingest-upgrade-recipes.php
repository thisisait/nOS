<?php

declare(strict_types=1);

/**
 * ingest-upgrade-recipes.php — load upgrades/*.yml into the upgrade_recipes
 * table (W5-B1, 2026-05-26).
 *
 * The /upgrades version matrix is built offline from the committed upgrade
 * recipes (deterministic, no upstream version calls — per operator decision).
 * Each recipe's `recipes:` entry becomes one upgrade_recipes row. Idempotent:
 * truncate + reinsert so removed recipes disappear. Safe to run every deploy.
 *
 * Usage:
 *   php bin/ingest-upgrade-recipes.php --recipes-dir=/path/to/upgrades [--data-dir=/path]
 */

require dirname(__DIR__) . '/vendor/autoload.php';

use Symfony\Component\Yaml\Yaml;

$opts = getopt('', ['recipes-dir:', 'data-dir:']);
$recipesDir = $opts['recipes-dir'] ?? (dirname(__DIR__, 4) . '/upgrades');
$dataDir = $opts['data-dir'] ?? (getenv('HOME') . '/wing/app/data');
$dbPath = rtrim($dataDir, '/') . '/wing.db';

if (!is_dir($recipesDir)) {
    fwrite(STDERR, "recipes dir not found: {$recipesDir}\n");
    exit(1);
}
if (!is_file($dbPath)) {
    fwrite(STDERR, "wing.db not found: {$dbPath}\n");
    exit(1);
}

$db = new PDO('sqlite:' . $dbPath);
$db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
$db->exec('DELETE FROM upgrade_recipes');

$ins = $db->prepare(
    'INSERT INTO upgrade_recipes (service, recipe_id, from_pattern, to_version, severity, docs_url, title)
     VALUES (:service, :recipe_id, :from_pattern, :to_version, :severity, :docs_url, :title)'
);

$count = 0;
foreach (glob(rtrim($recipesDir, '/') . '/*.yml') ?: [] as $file) {
    if (str_starts_with(basename($file), '_')) {
        continue; // _template.yml etc.
    }
    try {
        $doc = Yaml::parseFile($file);
    } catch (\Throwable $e) {
        fwrite(STDERR, "skip {$file}: " . $e->getMessage() . "\n");
        continue;
    }
    if (!is_array($doc) || empty($doc['service'])) {
        continue;
    }
    $service = (string) $doc['service'];
    $docsUrl = (string) ($doc['docs_url'] ?? '');
    foreach (($doc['recipes'] ?? []) as $recipe) {
        if (!is_array($recipe) || empty($recipe['id'])) {
            continue;
        }
        $title = $recipe['title'] ?? (trim(strtok((string) ($recipe['notes'] ?? ''), "\n")) ?: $recipe['id']);
        $ins->execute([
            ':service'      => $service,
            ':recipe_id'    => (string) $recipe['id'],
            ':from_pattern' => (string) ($recipe['from_regex'] ?? $recipe['from'] ?? ''),
            ':to_version'   => (string) ($recipe['to'] ?? $recipe['to_version'] ?? ''),
            ':severity'     => (string) ($recipe['severity'] ?? 'minor'),
            ':docs_url'     => $docsUrl,
            ':title'        => (string) $title,
        ]);
        $count++;
    }
}

echo "ingest-upgrade-recipes: loaded {$count} recipe(s) from {$recipesDir}.\n";
