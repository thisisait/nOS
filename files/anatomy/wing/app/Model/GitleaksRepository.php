<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * gitleaks_findings table. Anatomy A7 (2026-05-06).
 *
 * All writes go through ingestBatch() — the gitleaks skill POSTs a
 * batch after each scan. Deduplication key is `fingerprint`
 * (gitleaks' commit:file:line:rule_id composite). Existing rows are
 * not overwritten so resolved_at is preserved across re-scans; the
 * scan_id on an existing row IS updated so the UI knows the finding
 * reappeared in the latest run.
 */
final class GitleaksRepository
{
	public function __construct(
		private Explorer $db,
	) {
	}

	/**
	 * List findings. Optional array filters:
	 *   rule_id, severity, scan_id — exact-match WHERE clause
	 *   open_only                  — omit rows where resolved_at IS NOT NULL
	 *
	 * @return list<array<string, mixed>>
	 */
	public function listFindings(array $filters = [], int $limit = 200): array
	{
		$q = $this->db->table('gitleaks_findings')
			->order('created_at DESC')
			->limit($limit);
		foreach (['rule_id', 'severity', 'scan_id'] as $col) {
			if (isset($filters[$col])) {
				$q = $q->where($col, $filters[$col]);
			}
		}
		if (!empty($filters['open_only'])) {
			$q = $q->where('resolved_at', null);
		}
		return array_map(fn($r) => $r->toArray(), iterator_to_array($q));
	}

	/**
	 * Fetch a single finding by id, or null.
	 */
	public function getOne(string $id): ?array
	{
		$row = $this->db->table('gitleaks_findings')->get($id);
		return $row ? $row->toArray() : null;
	}

	/**
	 * Batch-ingest findings from a gitleaks JSON report.
	 *
	 * New fingerprints → INSERT. Known fingerprints → UPDATE scan_id +
	 * updated_at only (preserves resolved_at). Returns inserted + skipped
	 * counts so the skill can log a one-line summary.
	 *
	 * @param list<array<string, mixed>> $findings  Normalised rows from skill.
	 * @return array{inserted: int, skipped: int}
	 */
	public function ingestBatch(string $scanId, array $findings): array
	{
		$inserted = 0;
		$skipped  = 0;
		$now      = date('c');

		foreach ($findings as $f) {
			$fp = $f['fingerprint'] ?? null;
			if (!$fp) {
				$skipped++;
				continue;
			}

			$existing = $this->db->table('gitleaks_findings')
				->where('fingerprint', $fp)
				->fetch();

			if ($existing) {
				// Touch scan_id so we know the finding appeared in this run.
				$this->db->table('gitleaks_findings')
					->where('fingerprint', $fp)
					->update(['scan_id' => $scanId, 'updated_at' => $now]);
				$skipped++;
				continue;
			}

			$this->db->table('gitleaks_findings')->insert([
				'id'            => $this->newUuid(),
				'fingerprint'   => $fp,
				'rule_id'       => $f['rule_id']       ?? 'unknown',
				'description'   => $f['description']   ?? null,
				'secret_masked' => $f['secret_masked']  ?? null,
				'file_path'     => $f['file_path']      ?? '',
				'line_start'    => (int) ($f['line_start'] ?? 0),
				'commit_sha'    => $f['commit_sha'] ?? $f['commit'] ?? null,
				'author'        => $f['author']         ?? null,
				'date'          => $f['date']           ?? null,
				'severity'      => $this->normalizeSeverity($f['severity'] ?? null),
				'repo_path'     => $f['repo_path']      ?? '',
				'scan_id'       => $scanId,
				'created_at'    => $now,
				'updated_at'    => $now,
			]);
			$inserted++;
		}

		return ['inserted' => $inserted, 'skipped' => $skipped];
	}

	/**
	 * Mark a finding as resolved. Returns true if the row existed and was open.
	 */
	public function resolve(string $id, ?string $resolvedBy = null): bool
	{
		$affected = $this->db->table('gitleaks_findings')
			->where('id', $id)
			->where('resolved_at', null)
			->update([
				'resolved_at' => date('c'),
				'resolved_by' => $resolvedBy,
				'updated_at'  => date('c'),
			]);
		return (bool) $affected;
	}

	private function normalizeSeverity(?string $s): string
	{
		return in_array($s, ['critical', 'high', 'medium', 'low', 'info'], true)
			? $s
			: 'high';
	}

	private function newUuid(): string
	{
		return sprintf(
			'%04x%04x-%04x-%04x-%04x-%04x%04x%04x',
			random_int(0, 0xffff), random_int(0, 0xffff),
			random_int(0, 0xffff),
			random_int(0x4000, 0x4fff),
			random_int(0x8000, 0xbfff),
			random_int(0, 0xffff), random_int(0, 0xffff), random_int(0, 0xffff),
		);
	}
}
