<?php
/**
 * Shared test harness: minimal assertion helpers + Nette DI container setup
 * against a disposable SQLite database.
 */

declare(strict_types=1);

define('GW_ROOT', dirname(__DIR__, 2) . '/files/project-wing');

require GW_ROOT . '/vendor/autoload.php';

// --- Assertion helpers -----------------------------------------------------

final class T
{
	public static int $passed = 0;
	public static int $failed = 0;
	public static array $failures = [];

	public static function eq(mixed $expected, mixed $actual, string $msg): void
	{
		if ($expected === $actual) {
			self::$passed++;
			return;
		}
		self::$failed++;
		self::$failures[] = sprintf(
			"FAIL: %s\n  expected: %s\n  actual:   %s",
			$msg,
			var_export($expected, true),
			var_export($actual, true),
		);
	}

	public static function truthy(mixed $actual, string $msg): void
	{
		if ($actual) {
			self::$passed++;
			return;
		}
		self::$failed++;
		self::$failures[] = "FAIL: $msg (got: " . var_export($actual, true) . ')';
	}

	public static function contains(string $needle, string $haystack, string $msg): void
	{
		if (str_contains($haystack, $needle)) {
			self::$passed++;
			return;
		}
		self::$failed++;
		self::$failures[] = "FAIL: $msg (missing `$needle` in: " . substr($haystack, 0, 200) . ')';
	}

	public static function done(string $suite): never
	{
		$total = self::$passed + self::$failed;
		$colorOk = self::$failed === 0 ? "\033[32m" : "\033[31m";
		$reset = "\033[0m";
		$p = self::$passed;
		fwrite(STDERR, "{$colorOk}{$suite}: {$p}/{$total} passed{$reset}\n");
		foreach (self::$failures as $line) {
			fwrite(STDERR, "  $line\n");
		}
		exit(self::$failed === 0 ? 0 : 1);
	}
}

// --- SQLite setup ----------------------------------------------------------

/**
 * Create a temp SQLite DB initialized with the schema extensions.
 * We only create the tables we exercise (events, migrations_applied,
 * upgrades_applied, coexistence_tracks) — the base schema isn't needed
 * for these unit tests.
 */
function gw_make_temp_db(): string
{
	$dir = sys_get_temp_dir() . '/gw-test-' . bin2hex(random_bytes(4));
	mkdir($dir, 0755, true);
	$dbPath = $dir . '/wing.db';

	$pdo = new PDO('sqlite:' . $dbPath);
	$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

	$extensions = file_get_contents(GW_ROOT . '/db/schema-extensions.sql');
	if ($extensions === false) {
		throw new RuntimeException('Cannot read schema-extensions.sql');
	}
	// Strip comment-only lines, then split on `;` (no ; appears inside any
	// of our extension statements). Trim, skip empty.
	$lines = [];
	foreach (explode("\n", $extensions) as $line) {
		$trim = ltrim($line);
		if ($trim === '' || str_starts_with($trim, '--')) {
			continue;
		}
		$lines[] = $line;
	}
	$cleaned = implode("\n", $lines);
	foreach (explode(';', $cleaned) as $stmt) {
		$stmt = trim($stmt);
		if ($stmt === '') {
			continue;
		}
		$pdo->exec($stmt);
	}

	return $dbPath;
}

function gw_make_explorer(string $dbPath): Nette\Database\Explorer
{
	$conn = new Nette\Database\Connection('sqlite:' . $dbPath);
	$structure = new Nette\Database\Structure(
		$conn,
		new Nette\Caching\Storages\MemoryStorage(),
	);
	$conventions = new Nette\Database\Conventions\DiscoveredConventions($structure);
	return new Nette\Database\Explorer($conn, $structure, $conventions);
}
