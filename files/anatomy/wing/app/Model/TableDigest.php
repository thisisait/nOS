<?php

declare(strict_types=1);

namespace App\Model;

/**
 * A content fingerprint of one table, for "did this ingest change anything?".
 *
 * The bin/ingest-* scripts rewrite rows on every converge (truncate+reinsert,
 * upsert-all), so their output could only ever say "did work" — and Ansible
 * reported them `changed` on every run, on every platform. Hashing the table
 * before and after the write answers the question they are asked.
 *
 * Excluded: every `*_at` column (bookkeeping the write itself touches) and
 * whatever the caller names (autoincrement ids a reinsert renumbers, probe
 * columns another writer owns). Rows are sorted as strings, so neither rowid
 * nor insertion order matters.
 */
final class TableDigest
{
	/** @param list<string> $exclude */
	public static function of(\PDO $pdo, string $table, array $exclude = []): string
	{
		if (!preg_match('/^[a-z_][a-z0-9_]*$/', $table)) {
			throw new \InvalidArgumentException("bad table name: {$table}");
		}
		$cols = [];
		foreach ($pdo->query("PRAGMA table_info({$table})")->fetchAll(\PDO::FETCH_ASSOC) as $c) {
			$name = (string) $c['name'];
			if (str_ends_with($name, '_at') || in_array($name, $exclude, true)) {
				continue;
			}
			$cols[] = '"' . $name . '"';
		}
		if ($cols === []) {
			return sha1('');
		}
		$rows = [];
		foreach ($pdo->query('SELECT ' . implode(', ', $cols) . " FROM {$table}")->fetchAll(\PDO::FETCH_NUM) as $r) {
			$rows[] = json_encode($r);
		}
		sort($rows, SORT_STRING);
		return sha1(implode("\n", $rows));
	}
}
