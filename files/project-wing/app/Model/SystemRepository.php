<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Unified repository for all managed systems (services, components, stacks).
 * Replaces ComponentRepository + ServiceRegistry with a single DB-backed
 * entity that supports parent-child hierarchy and health tracking.
 */
final class SystemRepository
{
	public function __construct(
		private Explorer $db,
	) {
	}


	// ── List / Tree ────────────────────────────────────────────────────

	/**
	 * Flat list with optional filters. Joins scan_state.
	 *
	 * @param array{category?:string,stack?:string,priority?:string,health?:string,parent_id?:string,source?:string,has_findings?:bool,type?:string} $filters
	 * @return array{systems:list<array>,total:int}
	 */
	public function list(array $filters = []): array
	{
		$query = $this->db->table('systems')
			->order('stack ASC, priority DESC, name ASC');

		foreach (['category', 'stack', 'priority', 'source', 'type'] as $col) {
			if (!empty($filters[$col])) {
				$query->where($col, $filters[$col]);
			}
		}
		if (isset($filters['health']) && $filters['health'] !== '') {
			$query->where('health_status', $filters['health']);
		}
		if (array_key_exists('parent_id', $filters)) {
			$query->where('parent_id', $filters['parent_id']);
		}

		$rows = [];
		foreach ($query->fetchAll() as $row) {
			$rows[] = $this->enrich($row->toArray());
		}

		if (!empty($filters['has_findings'])) {
			$rows = array_values(array_filter($rows, fn($r) => ($r['scan_state']['findings_count'] ?? 0) > 0));
		}

		return ['systems' => $rows, 'total' => count($rows)];
	}


	/**
	 * Tree structure: top-level systems (parent_id IS NULL) with nested children.
	 *
	 * @return list<array>
	 */
	public function tree(): array
	{
		$all = $this->list()['systems'];
		$byId = [];
		foreach ($all as &$item) {
			$item['children'] = [];
			$byId[$item['id']] = &$item;
		}
		unset($item);

		$roots = [];
		foreach ($byId as &$item) {
			$pid = $item['parent_id'] ?? null;
			if ($pid !== null && isset($byId[$pid])) {
				$byId[$pid]['children'][] = &$item;
			} else {
				$roots[] = &$item;
			}
		}
		return $roots;
	}


	/**
	 * Group flat list by stack.
	 *
	 * @return array<string,list<array>>
	 */
	public function byStack(): array
	{
		$groups = [];
		foreach ($this->list()['systems'] as $sys) {
			$key = $sys['stack'] ?? 'other';
			$groups[$key][] = $sys;
		}
		ksort($groups);
		return $groups;
	}


	// ── CRUD ───────────────────────────────────────────────────────────

	public function get(string $id): ?array
	{
		$row = $this->db->table('systems')->where('id', $id)->fetch();
		if (!$row) {
			return null;
		}
		$item = $this->enrich($row->toArray());
		$item['children'] = [];
		foreach ($this->db->table('systems')->where('parent_id', $id)->order('name ASC')->fetchAll() as $child) {
			$item['children'][] = $this->enrich($child->toArray());
		}
		return $item;
	}


	public function upsert(array $data): void
	{
		$id = $data['id'] ?? null;
		if (!$id) {
			throw new \InvalidArgumentException('System id is required');
		}

		$exists = $this->db->table('systems')->where('id', $id)->count('*') > 0;
		$data['updated_at'] = (new \DateTimeImmutable)->format('Y-m-d H:i:s');

		if ($exists) {
			$this->db->table('systems')->where('id', $id)->update($data);
		} else {
			$this->db->table('systems')->insert($data);
		}
	}


	public function delete(string $id): bool
	{
		return $this->db->table('systems')->where('id', $id)->delete() > 0;
	}


	// ── Health ──────────────────────────────────────────────────────────

	/**
	 * Update health status for a system after a probe.
	 */
	public function setHealth(string $id, string $status, int $httpCode, int $ms): void
	{
		$this->db->table('systems')->where('id', $id)->update([
			'health_status' => $status,
			'health_http_code' => $httpCode,
			'health_ms' => $ms,
			'health_checked_at' => (new \DateTimeImmutable)->format('Y-m-d H:i:s'),
		]);
	}


	/**
	 * Probe a URL and return result. Does NOT persist — caller decides.
	 *
	 * @return array{status:string,http_code:int,ms:int}
	 */
	public function probe(string $url, float $timeout = 2.0): array
	{
		$start = microtime(true);
		$handle = curl_init($url);
		if ($handle === false) {
			return ['status' => 'unknown', 'http_code' => 0, 'ms' => 0];
		}
		curl_setopt_array($handle, [
			CURLOPT_NOBODY => true,
			CURLOPT_FOLLOWLOCATION => false,
			CURLOPT_SSL_VERIFYPEER => false,
			CURLOPT_SSL_VERIFYHOST => 0,
			CURLOPT_TIMEOUT => (int) ceil($timeout),
			CURLOPT_CONNECTTIMEOUT_MS => (int) ($timeout * 1000),
			CURLOPT_RETURNTRANSFER => true,
			CURLOPT_USERAGENT => 'Glasswing/2.0',
		]);
		curl_exec($handle);
		$code = (int) curl_getinfo($handle, CURLINFO_HTTP_CODE);
		$errno = curl_errno($handle);
		curl_close($handle);
		$ms = (int) round((microtime(true) - $start) * 1000);

		$status = ($code >= 200 && $code < 500 && $errno === 0) ? 'up' : 'down';
		return ['status' => $status, 'http_code' => $code, 'ms' => $ms];
	}


	/**
	 * Probe all systems with a URL and persist results.
	 *
	 * @return array<string,array{status:string,http_code:int,ms:int}>
	 */
	public function probeAll(float $timeout = 2.0): array
	{
		$results = [];
		foreach ($this->db->table('systems')->where('url IS NOT NULL AND url != ?', '')->fetchAll() as $row) {
			$sys = $row->toArray();
			$result = $this->probe($sys['url'], $timeout);
			$this->setHealth($sys['id'], $result['status'], $result['http_code'], $result['ms']);
			$results[$sys['id']] = $result;
		}
		return $results;
	}


	// ── Registry ingest ────────────────────────────────────────────────

	/**
	 * Import services from Ansible-generated service-registry.json.
	 * Upserts each service, creates stack-level parents if missing.
	 *
	 * @return array{imported:int,stacks_created:int}
	 */
	public function ingestRegistry(string $jsonPath): array
	{
		if (!is_file($jsonPath) || !is_readable($jsonPath)) {
			return ['imported' => 0, 'stacks_created' => 0];
		}
		$raw = @file_get_contents($jsonPath);
		if ($raw === false) {
			return ['imported' => 0, 'stacks_created' => 0];
		}
		$data = json_decode($raw, true);
		if (!is_array($data) || empty($data['services'])) {
			return ['imported' => 0, 'stacks_created' => 0];
		}

		$stacksCreated = 0;
		$imported = 0;

		foreach ($data['services'] as $svc) {
			$stack = $svc['stack'] ?? null;
			$stackId = $stack ? 'stack-' . $stack : null;

			// Ensure stack-level parent exists
			if ($stackId) {
				$exists = $this->db->table('systems')->where('id', $stackId)->count('*') > 0;
				if (!$exists) {
					$this->upsert([
						'id' => $stackId,
						'name' => ucfirst((string) $stack) . ' Stack',
						'type' => 'stack',
						'category' => 'stack',
						'stack' => $stack,
						'source' => 'registry',
						'enabled' => 1,
					]);
					$stacksCreated++;
				}
			}

			// Normalize service ID
			$name = $svc['name'] ?? 'unknown';
			$id = $svc['toggle_var'] ?? strtolower(preg_replace('/[^a-zA-Z0-9_]/', '_', $name));

			$this->upsert([
				'id' => $id,
				'parent_id' => $stackId,
				'name' => $name,
				'description' => $svc['description'] ?? null,
				'type' => $svc['type'] ?? 'docker',
				'category' => $svc['category'] ?? 'service',
				'stack' => $stack,
				'version' => $svc['version'] ?? null,
				'domain' => $svc['domain'] ?? null,
				'port' => isset($svc['port']) ? (int) $svc['port'] : null,
				'url' => $svc['url'] ?? null,
				'network_exposed' => !empty($svc['domain']) ? 1 : 0,
				'has_web_ui' => !empty($svc['domain']) ? 1 : 0,
				'toggle_var' => $svc['toggle_var'] ?? null,
				'enabled' => ($svc['enabled'] ?? true) ? 1 : 0,
				'source' => 'registry',
			]);
			$imported++;
		}

		// After ingest: merge orphan components_db entries into their registry
		// counterparts by name, then delete the orphans.
		$merged = $this->dedup();

		return ['imported' => $imported, 'stacks_created' => $stacksCreated, 'merged' => $merged];
	}


	/**
	 * Merge duplicate systems (same name, different source). Copies version,
	 * upstream_repo, image, priority, version_var from components_db entry
	 * into the registry entry, migrates scan_state, then deletes the orphan.
	 *
	 * @return int number of orphans merged + deleted
	 */
	public function dedup(): int
	{
		// Find names with >1 entry
		$dupes = $this->db->query(
			'SELECT name, COUNT(*) AS c FROM systems WHERE category != ? GROUP BY name HAVING c > 1',
			'stack'
		)->fetchAll();

		$merged = 0;
		foreach ($dupes as $row) {
			$name = $row['name'];
			$entries = $this->db->table('systems')->where('name', $name)->fetchAll();

			// Prefer registry entry as the survivor (has parent_id, health)
			$registry = null;
			$others = [];
			foreach ($entries as $entry) {
				$arr = $entry->toArray();
				if ($arr['source'] === 'registry') {
					$registry = $arr;
				} else {
					$others[] = $arr;
				}
			}

			if (!$registry || empty($others)) {
				continue;
			}

			// Merge fields from the richest "other" into registry
			foreach ($others as $other) {
				$updates = [];
				// Copy version if registry lacks one
				if (empty($registry['version']) && !empty($other['version'])) {
					$updates['version'] = $other['version'];
				}
				if (empty($registry['version_var']) && !empty($other['version_var'])) {
					$updates['version_var'] = $other['version_var'];
				}
				if (empty($registry['upstream_repo']) && !empty($other['upstream_repo'])) {
					$updates['upstream_repo'] = $other['upstream_repo'];
				}
				if (empty($registry['image']) && !empty($other['image'])) {
					$updates['image'] = $other['image'];
				}
				// Prefer higher priority
				$priOrder = ['high' => 3, 'medium' => 2, 'low' => 1];
				$otherPri = $priOrder[$other['priority'] ?? 'medium'] ?? 2;
				$regPri = $priOrder[$registry['priority'] ?? 'medium'] ?? 2;
				if ($otherPri > $regPri) {
					$updates['priority'] = $other['priority'];
				}

				if ($updates) {
					$updates['updated_at'] = (new \DateTimeImmutable)->format('Y-m-d H:i:s');
					$this->db->table('systems')->where('id', $registry['id'])->update($updates);
				}

				// Migrate scan_state FK from old ID to registry ID
				$this->db->table('component_scan_state')
					->where('component_id', $other['id'])
					->update(['component_id' => $registry['id']]);

				// Migrate remediation_items, pentest_targets, patches references
				foreach (['remediation_items', 'pentest_targets', 'patches'] as $tbl) {
					$this->db->table($tbl)
						->where('component_id', $other['id'])
						->update(['component_id' => $registry['id']]);
				}

				// Delete the orphan
				$this->db->table('systems')->where('id', $other['id'])->delete();
				$merged++;
			}
		}

		return $merged;
	}


	// ── Stats ──────────────────────────────────────────────────────────

	/**
	 * Quick counts for dashboard stats row.
	 *
	 * @return array{total:int,up:int,down:int,unknown:int,stacks:int,findings:int}
	 */
	public function stats(): array
	{
		$total = $this->db->table('systems')->where('category != ?', 'stack')->count('*');
		$up = $this->db->table('systems')->where('health_status', 'up')->where('category != ?', 'stack')->count('*');
		$down = $this->db->table('systems')->where('health_status', 'down')->where('category != ?', 'stack')->count('*');
		$stacks = $this->db->table('systems')->where('category', 'stack')->count('*');

		$findings = (int) $this->db->query('SELECT COALESCE(SUM(findings_count), 0) AS f FROM component_scan_state')->fetch()['f'];

		return [
			'total' => $total,
			'up' => $up,
			'down' => $down,
			'unknown' => $total - $up - $down,
			'stacks' => $stacks,
			'findings' => $findings,
		];
	}


	// ── Private ─────────────────────────────────────────────────────────

	private function enrich(array $item): array
	{
		$scanState = $this->db->table('component_scan_state')
			->where('component_id', $item['id'])
			->fetch();
		$item['scan_state'] = $scanState ? $scanState->toArray() : null;

		$port = is_int($item['port'] ?? null) ? $item['port'] : 0;
		$domain = is_string($item['domain'] ?? null) ? $item['domain'] : null;
		$item['ip_url'] = $port > 0 ? 'http://127.0.0.1:' . $port : null;
		$item['domain_url'] = $domain ? 'https://' . $domain : null;
		if (empty($item['url'])) {
			$item['url'] = $item['domain_url'] ?? $item['ip_url'];
		}

		return $item;
	}
}
