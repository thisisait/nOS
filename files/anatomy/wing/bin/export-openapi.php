<?php

declare(strict_types=1);

/**
 * Wing — Export the API surface as OpenAPI 3.1 YAML.
 *
 * Anatomy A5 (2026-05-04) — OpenAPI half of the contracts pair.
 *
 * Wing is Nette PHP, not FastAPI; there is no introspect-the-app shortcut.
 * This script reads ``app/Core/RouterFactory.php`` for the route list and
 * walks the ``app/Presenters/Api/*Presenter.php`` files for class-level
 * docblocks describing HTTP methods + summaries. Auth requirement is
 * derived from ``protected array $publicActions`` per presenter.
 *
 * The output is intentionally pragmatic: paths + methods + auth +
 * summaries. Request/response body schemas are NOT introspected (Wing's
 * presenters don't carry typed DTOs). Drift detection on the path/method
 * surface is the v1 goal — body schemas come with A8 conductor work if
 * the operator decides we need them.
 *
 * Usage:
 *   php bin/export-openapi.php [--output=/path/to/file.yml]
 */

$args = [];
foreach (array_slice($argv, 1) as $a) {
	if (str_starts_with($a, '--')) {
		$kv = explode('=', substr($a, 2), 2);
		$args[$kv[0]] = $kv[1] ?? '1';
	}
}

$here = __DIR__;
$wingDir = dirname($here);
$repoRoot = dirname($wingDir, 3);

$routerPath = $wingDir . '/app/Core/RouterFactory.php';
$presentersDir = $wingDir . '/app/Presenters/Api';
$outPath = $args['output'] ?? ($repoRoot . '/files/anatomy/skills/contracts/wing.openapi.yml');

// -- Step 1: parse the router. -------------------------------------------
$router = file_get_contents($routerPath);
if ($router === false) {
	fwrite(STDERR, "Cannot read $routerPath\n");
	exit(1);
}

// Match: $api->addRoute('<path>', '<Presenter>:<action>')
// Routes outside the $api->withModule('Api') section are browser routes
// and are not part of the API contract — we look for the $api-> prefix.
preg_match_all(
	"/\\\$api->addRoute\\(\\s*'([^']+)'\\s*,\\s*'([A-Za-z]+):([a-zA-Z]+)'\\s*\\)/",
	$router,
	$matches,
	PREG_SET_ORDER
);

if (empty($matches)) {
	fwrite(STDERR, "No \$api->addRoute() calls found in RouterFactory.php\n");
	exit(1);
}

// -- Step 2: parse each presenter once. ----------------------------------
$presenterCache = [];

/**
 * Pull the class-level docblock out of a presenter and parse out lines
 * matching ``METHOD path — summary`` (or ``METHOD path?qs — summary``).
 * Returns a map keyed by the route path with sub-keys per HTTP method.
 *
 * @return array<string, array<string, string>>  path => method => summary
 */
function parse_presenter_docblock(string $file): array
{
	$src = file_get_contents($file);
	if ($src === false) {
		return [];
	}
	// Class-level docblock: the /** ... */ block immediately before
	// "final class XxxPresenter" or "class XxxPresenter".
	if (!preg_match('#/\*\*([\s\S]*?)\*/\s*(?:final\s+)?class\s+\w+Presenter#', $src, $m)) {
		return [];
	}
	$doc = $m[1];
	$out = [];
	foreach (preg_split('/\R/', $doc) as $line) {
		// Strip leading "* " from docblock line.
		$line = preg_replace('/^\s*\*\s?/', '', $line) ?? $line;
		// Match: METHOD /path  — summary  (em-dash or hyphen).
		if (preg_match(
			'#^(GET|POST|PUT|PATCH|DELETE)\s+(/?\S+)\s*[—\-]+\s*(.+)$#',
			trim($line),
			$mm
		)) {
			$method = strtolower($mm[1]);
			$path = '/' . ltrim($mm[2], '/');
			$summary = trim($mm[3]);
			$out[$path][$method] = $summary;
		}
	}
	return $out;
}

/**
 * Pull the ``protected array $publicActions = [...];`` value from a
 * presenter source file. Returns the action names as an array.
 */
function parse_public_actions(string $file): array
{
	$src = file_get_contents($file);
	if ($src === false) {
		return [];
	}
	if (!preg_match(
		'/protected\s+array\s+\$publicActions\s*=\s*\[([^\]]*)\]/',
		$src,
		$m
	)) {
		return [];
	}
	preg_match_all("/'([^']+)'/", $m[1], $names);
	return $names[1] ?? [];
}

/**
 * Convert a Nette router pattern like ``api/v1/foo[/<id>]`` into one or
 * more OpenAPI paths. ``[/...]`` is an optional trailing segment, which
 * we expand into two paths. ``<name>`` becomes ``{name}``.
 *
 * @return array{paths: list<string>, params: list<string>}
 */
function nette_pattern_to_openapi(string $pattern): array
{
	$basePath = '/' . ltrim($pattern, '/');
	$paths = [];
	if (preg_match('/^(.*)\[(\/<\w+>(?:\/<\w+>)?)\](.*)$/', $basePath, $m)) {
		// Optional segment present — emit both forms.
		$paths[] = $m[1] . $m[3];
		$paths[] = $m[1] . $m[2] . $m[3];
	} else {
		$paths[] = $basePath;
	}

	// Replace <name> → {name}; collect param names.
	$expanded = [];
	$params = [];
	foreach ($paths as $p) {
		$p = preg_replace_callback(
			'/<(\w+)>/',
			static function ($mm) use (&$params) {
				$params[$mm[1]] = true;
				return '{' . $mm[1] . '}';
			},
			$p
		);
		$expanded[] = $p;
	}
	return ['paths' => $expanded, 'params' => array_keys($params)];
}

// -- Step 3: build the OpenAPI document. ---------------------------------
$paths = [];
foreach ($matches as $row) {
	[$_, $pattern, $presenter, $action] = $row;
	$presenterFile = $presentersDir . '/' . $presenter . 'Presenter.php';
	if (!isset($presenterCache[$presenter])) {
		$presenterCache[$presenter] = [
			'docblock' => parse_presenter_docblock($presenterFile),
			'public'   => parse_public_actions($presenterFile),
		];
	}
	$pInfo = $presenterCache[$presenter];

	$mapped = nette_pattern_to_openapi($pattern);
	foreach ($mapped['paths'] as $oaPath) {
		// Pull docblock entries that match this path. The docblock paths
		// may have ``[/<id>]`` style or expanded form; match liberally
		// by stripping query strings and trailing slashes.
		$matchedMethods = [];
		foreach ($pInfo['docblock'] as $dPath => $methods) {
			$dCanon = nette_pattern_to_openapi($dPath)['paths'];
			if (in_array($oaPath, $dCanon, true)) {
				$matchedMethods += $methods;
			}
		}
		if (!$matchedMethods) {
			$matchedMethods = ['get' => "$presenter::action$action"];
		}

		$isPublic = in_array(
			lcfirst($action),
			array_map('lcfirst', $pInfo['public']),
			true
		);

		foreach ($matchedMethods as $method => $summary) {
			$op = [
				'summary'     => $summary,
				'operationId' => $presenter . '_' . $action . '_' . $method,
				'tags'        => [$presenter],
				'responses'   => [
					'200' => ['description' => 'OK'],
					'400' => ['description' => 'Bad request'],
					'401' => ['description' => 'Authentication required'],
					'404' => ['description' => 'Not found'],
				],
			];
			if (!$isPublic) {
				$op['security'] = [['BearerAuth' => []]];
			}

			// Path parameters.
			preg_match_all('/\{(\w+)\}/', $oaPath, $pm);
			if ($pm[1]) {
				$op['parameters'] = [];
				foreach ($pm[1] as $pname) {
					$op['parameters'][] = [
						'name'     => $pname,
						'in'       => 'path',
						'required' => true,
						'schema'   => ['type' => 'string'],
					];
				}
			}

			$paths[$oaPath][$method] = $op;
		}
	}
}

// Stable ordering.
ksort($paths);
foreach ($paths as $p => &$ops) {
	ksort($ops);
}
unset($ops);

$spec = [
	'openapi' => '3.1.0',
	'info'    => [
		'title'       => 'nOS Wing API',
		'version'     => '0.2.0',
		'description' => "Security-research dashboard + state/migration framework API. "
			. "Auto-extracted from RouterFactory + presenter docblocks; "
			. "request/response body schemas are not introspected.",
	],
	'servers' => [
		['url' => 'http://127.0.0.1:9000', 'description' => 'Local FrankenPHP launchd daemon'],
	],
	'components' => [
		'securitySchemes' => [
			'BearerAuth' => [
				'type'         => 'http',
				'scheme'       => 'bearer',
				'description'  => 'API token issued by Wing (api_tokens table).',
			],
		],
	],
	'paths' => $paths,
];

// -- Step 4: emit YAML. --------------------------------------------------
function yaml_emit(mixed $v, int $indent = 0): string
{
	$pad = str_repeat('  ', $indent);
	if (is_array($v)) {
		if ($v === []) {
			return "{}\n";
		}
		// List vs map.
		$isList = array_is_list($v);
		$out = '';
		if ($isList) {
			foreach ($v as $item) {
				if (is_array($item)) {
					// Render at indent+1; replace its first-line padding
					// with "- " marker, leave subsequent lines as-is.
					$itemStr = yaml_emit($item, $indent + 1);
					$lines = explode("\n", rtrim($itemStr, "\n"));
					$childPad = str_repeat('  ', $indent + 1);
					$first = $lines[0];
					if (str_starts_with($first, $childPad)) {
						$first = substr($first, strlen($childPad));
					} else {
						$first = ltrim($first);
					}
					$out .= $pad . '- ' . $first . "\n";
					for ($i = 1, $n = count($lines); $i < $n; $i++) {
						$out .= $lines[$i] . "\n";
					}
				} else {
					$out .= $pad . '- ' . yaml_scalar($item) . "\n";
				}
			}
		} else {
			foreach ($v as $k => $item) {
				$key = (string) $k;
				if (preg_match('/[:#@\s\[\]\{\},&\*\?\|\>\<\!%\'\"]/', $key)
					|| in_array(strtolower($key), ['true', 'false', 'null', 'yes', 'no'], true)
					|| is_numeric($key)) {
					$key = "'" . str_replace("'", "''", $key) . "'";
				}
				if (is_array($item)) {
					if ($item === []) {
						$out .= $pad . $key . ": []\n";
					} else {
						$out .= $pad . $key . ":\n" . yaml_emit($item, $indent + 1);
					}
				} else {
					$out .= $pad . $key . ': ' . yaml_scalar($item) . "\n";
				}
			}
		}
		return $out;
	}
	return $pad . yaml_scalar($v) . "\n";
}

function yaml_scalar(mixed $v): string
{
	if ($v === null) {
		return 'null';
	}
	if (is_bool($v)) {
		return $v ? 'true' : 'false';
	}
	if (is_int($v) || is_float($v)) {
		return (string) $v;
	}
	$s = (string) $v;
	// Quote if special characters or ambiguous tokens.
	if ($s === ''
		|| preg_match('/^[\s]|[\s]$|[:#&\*\?\|\>\<\!%\'\"\\\\]|^[\-\?]\s|^@/', $s)
		|| in_array(strtolower($s), ['true', 'false', 'null', 'yes', 'no'], true)
		|| is_numeric($s)
	) {
		return "'" . str_replace("'", "''", $s) . "'";
	}
	return $s;
}

if (!is_dir(dirname($outPath))) {
	mkdir(dirname($outPath), 0755, true);
}

$header = "# AUTO-GENERATED — do not edit by hand.\n"
	. "# Source: files/anatomy/wing/app/Core/RouterFactory.php +\n"
	. "#         files/anatomy/wing/app/Presenters/Api/*Presenter.php docblocks.\n"
	. "# Regenerate: php files/anatomy/wing/bin/export-openapi.php\n"
	. "# CI drift check: .github/workflows/ci.yml — contracts-drift job.\n"
	. "---\n";
file_put_contents($outPath, $header . yaml_emit($spec));

echo "Wrote $outPath (" . count($paths) . " paths)\n";
