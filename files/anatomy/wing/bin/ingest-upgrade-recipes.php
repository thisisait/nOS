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
    'INSERT INTO upgrade_recipes (service, recipe_id, from_pattern, to_version, severity, docs_url, title, coexistence_supported, reset_json)
     VALUES (:service, :recipe_id, :from_pattern, :to_version, :severity, :docs_url, :title, :coexistence_supported, :reset_json)'
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
        // Reset-scope (Phase 1): persist the AUTHORED reset block (JSON) when the
        // recipe declares one, else NULL. We do NOT derive a floor here — the engine
        // (files/anatomy/module_utils/.../reset_scope.py) derives + escalates at apply
        // time from the real step types, which is the authoritative path. The UI treats
        // a NULL reset_json as the 'container' floor for display only. Mirrors the
        // coexistence_supported extraction (DELETE+reinsert keeps it idempotent).
        $reset = (isset($recipe['reset']) && is_array($recipe['reset'])) ? $recipe['reset'] : null;
        $resetJson = $reset !== null ? json_encode($reset) : null;
        $ins->execute([
            ':service'      => $service,
            ':recipe_id'    => (string) $recipe['id'],
            ':from_pattern' => (string) ($recipe['from_regex'] ?? $recipe['from'] ?? ''),
            ':to_version'   => (string) ($recipe['to'] ?? $recipe['to_version'] ?? ''),
            ':severity'     => (string) ($recipe['severity'] ?? 'minor'),
            ':docs_url'     => $docsUrl,
            ':title'        => (string) $title,
            // F1: the per-recipe coexistence_supported flag → /upgrades matrix →
            // plan-choice modal option (b) gate. Stored as 0/1 (SQLite has no bool).
            ':coexistence_supported' => !empty($recipe['coexistence_supported']) ? 1 : 0,
            ':reset_json'   => $resetJson,
        ]);
        $count++;
    }
}

echo "ingest-upgrade-recipes: loaded {$count} recipe(s) from {$recipesDir}.\n";
