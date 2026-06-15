<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Upgrade read model.
 *
 * Static recipes live in upgrades/*.yml (agent 6). Live version/state comes
 * from BoxAPI. History mirror is `upgrades_applied` in SQLite.
 */
final class UpgradeRepository
{
	public function __construct(
		private Explorer $db,
		private BoneClient $box,
		private EventRepository $events,
		// B3 (Phase B): the plan-choice path-(b) "coexist" branch hands off to the
		// coexistence queue. Injected as a Nette DI service (both repos are listed
		// in app/config/common.neon, autowired by type) — no container edits.
		private CoexistenceRepository $coexistence,
	) {
	}

	/**
	 * Full matrix of services — installed vs target vs recipe vs planned.
	 *
	 * W5-B1 (2026-05-26): built offline from the local upgrade_recipes catalog
	 * (ingested from upgrades/*.yml) joined to systems (best-effort installed
	 * version) and upgrades_planned (queued upgrades). Was a Bone /api/upgrades
	 * proxy that 401'd (HMAC vs the endpoint's JWT-scope gate) → empty matrix.
	 *
	 * @return array<int,array<string,mixed>>
	 */
	public function matrix(): array
	{
		// Recipe catalog grouped by service (target version DESC → [0] is latest).
		$recipes = [];
		foreach ($this->db->table('upgrade_recipes')->order('service ASC, to_version DESC') as $r) {
			$recipes[$r->service][] = $r->toArray();
		}
		// Queued upgrades, keyed by service.
		$planned = [];
		foreach ($this->db->table('upgrades_planned')->where('status', 'planned') as $p) {
			$planned[$p->service] = $p->toArray();
		}
		// Installed versions from ~/.nos/state.yml — the authoritative source the
		// upgrade-engine itself reads (keyed by the same lowercase service ids as
		// the recipes). systems.version is unreliable (mostly NULL), which left
		// the matrix "installed" column blank.
		$installed = $this->installedVersionsFromState();

		$out = [];
		foreach ($recipes as $service => $svcRecipes) {
			$inst = $installed[$service] ?? null;
			$latest = $svcRecipes[0]['to_version'] ?? null;   // highest target (ordered DESC)

			// "stable" = the next applicable step: the recipe whose from_pattern
			// matches the installed version (lowest such target). Distinct from
			// "latest" only when there are stepping-stones (e.g. 17→17.11→18).
			$applicable = [];
			foreach ($svcRecipes as $r) {
				$pat = (string) ($r['from_pattern'] ?? '');
				if ($inst !== null && $pat !== '' && @preg_match('~' . $pat . '~', $inst) === 1) {
					$applicable[] = $r;
				}
			}
			$next = $applicable !== [] ? end($applicable) : $svcRecipes[0];   // lowest applicable, else highest
			$stable = $next['to_version'] ?? $latest;
			$sev = $next['severity'] ?? 'minor';
			$sevClass = match ($sev) {
				'breaking'             => 'breaking',
				'security', 'critical' => 'critical',
				'patch', 'minor'       => 'minor',
				default                => 'unknown',
			};
			// At-target = installed already equals the only/next target.
			$atTarget = $inst !== null && ($inst === $stable);
			$out[] = [
				'id'               => $service,
				'service'          => $service,
				'category'         => null,
				'installed'        => $inst,
				'installed_class'  => $atTarget ? 'current' : ($inst !== null ? 'minor' : 'unknown'),
				'stable'           => $stable,
				'stable_class'     => $atTarget ? 'current' : $sevClass,
				'latest'           => $latest,
				'latest_class'     => ($inst !== null && $inst === $latest) ? 'current' : $sevClass,
				'upstream'         => null,        // offline matrix — no upstream scanner (B1 decision)
				'upstream_class'   => 'unknown',
				'severity'         => $sev,
				'recipe_available' => true,
				'recipe_count'     => count($svcRecipes),
				'recipes'          => $svcRecipes,
				'planned'          => isset($planned[$service]),
				'planned_target'   => $planned[$service]['target_version'] ?? null,
				'planned_by'       => $planned[$service]['planned_by'] ?? null,
			];
		}
		return $out;
	}

	/**
	 * Installed versions keyed by service id, read from ~/.nos/state.yml
	 * (services.<id>.installed) — the same authoritative state the
	 * upgrade-engine consumes. Empty map if the file is absent/unparseable.
	 *
	 * @return array<string,string>
	 */
	private function installedVersionsFromState(): array
	{
		$path = (getenv('HOME') ?: '') . '/.nos/state.yml';
		if ($path === '/.nos/state.yml' || !is_file($path)) {
			return [];
		}
		try {
			$state = \Symfony\Component\Yaml\Yaml::parseFile($path);
		} catch (\Throwable $e) {
			return [];
		}
		$out = [];
		foreach (($state['services'] ?? []) as $svc => $info) {
			if (is_array($info) && !empty($info['installed'])) {
				$out[(string) $svc] = (string) $info['installed'];
			}
		}
		return $out;
	}

	/**
	 * Planned (queued) upgrades. status defaults to 'planned'.
	 *
	 * @return array<int,array<string,mixed>>
	 */
	public function listPlanned(string $status = 'planned'): array
	{
		$out = [];
		foreach ($this->db->table('upgrades_planned')->where('status', $status)->order('planned_at DESC') as $r) {
			$out[] = $r->toArray();
		}
		return $out;
	}

	/**
	 * Queue an upgrade as planned (idempotent on service+recipe+status).
	 * planned_by carries the attribution (operator / agent name).
	 *
	 * Mismatch guard (2026-05-27): REFUSES by default when the recipe's
	 * from_pattern does not match the installed version — that is how a
	 * downgrade/inapplicable recipe got queued (authentik-2024-to-2025 on a
	 * 2025.12.4 install). Pass $force=true to override deliberately.
	 *
	 * @return array{ok:bool, status:string, detail:string}
	 */
	public function planUpgrade(string $service, string $recipeId, ?string $targetVersion, string $plannedBy, ?string $notes = null, bool $force = false): array
	{
		$exists = $this->db->table('upgrades_planned')
			->where('service', $service)
			->where('recipe_id', $recipeId)
			->where('status', 'planned')
			->fetch();
		if ($exists) {
			return ['ok' => false, 'status' => 'already_queued', 'detail' => 'already queued'];
		}

		if (!$force) {
			$mismatch = $this->recipeMismatch($service, $recipeId);
			if ($mismatch !== null) {
				return ['ok' => false, 'status' => 'mismatch', 'detail' => $mismatch];
			}
		}

		$this->db->table('upgrades_planned')->insert([
			'service'        => $service,
			'recipe_id'      => $recipeId,
			'target_version' => $targetVersion,
			'planned_by'     => $plannedBy,
			'status'         => 'planned',
			'notes'          => $notes,
		]);
		return ['ok' => true, 'status' => 'queued', 'detail' => 'queued'];
	}

	/**
	 * Plan-choice branch point (B3 §3.1/§5): queue an upgrade AND stamp the
	 * operator's chosen path. Reuses planUpgrade() — keeping the recipeMismatch()
	 * guard intact — then writes the plan-mode link rows:
	 *
	 *   mode='migration' → just stamps upgrades_planned.plan_mode='migration'
	 *                      (today's in-place behaviour, no track).
	 *   mode='coexist'   → also calls CoexistenceRepository::planCoexistence()
	 *                      with parent_upgrade_id + data_copy, then back-links
	 *                      upgrades_planned.coexistence_planned_id.
	 *
	 * Returns the same shape as planUpgrade() plus the link ids so the presenter
	 * can render the dry-run preview / emit plan_choice_recorded.
	 *
	 * @return array{ok:bool, status:string, detail:string, upgrade_id:int|null, coexistence_planned_id:int|null}
	 */
	public function planUpgradeWithMode(
		string $service,
		string $recipeId,
		?string $targetVersion,
		string $plannedBy,
		string $mode = 'migration',
		int $portOffset = 100,
		bool $dataCopy = true,
		bool $force = false,
		?string $notes = null
	): array {
		$mode = ($mode === 'coexist') ? 'coexist' : 'migration';
		$result = $this->planUpgrade($service, $recipeId, $targetVersion, $plannedBy, $notes, $force);
		if (!$result['ok']) {
			// mismatch / already_queued — surface as-is, write no link rows.
			return $result + ['upgrade_id' => null, 'coexistence_planned_id' => null];
		}

		// The just-queued (or existing) planned row carries the id we link from.
		$planned = $this->db->table('upgrades_planned')
			->where('service', $service)->where('recipe_id', $recipeId)->where('status', 'planned')->fetch();
		$upgradeId = $planned !== null ? (int) $planned->id : null;

		$coexistencePlannedId = null;
		if ($mode === 'coexist') {
			$tag = $this->coexistTag($targetVersion);
			$coex = $this->coexistence->planCoexistence(
				$service, $tag, $portOffset, $plannedBy, $targetVersion, 'plan-choice (b) coexist', $upgradeId, $dataCopy,
			);
			$coexistencePlannedId = $coex['id'] ?? null;
		}

		if ($planned !== null) {
			$update = ['plan_mode' => $mode, 'plan_choice_at' => gmdate('c')];
			if ($coexistencePlannedId !== null) {
				$update['coexistence_planned_id'] = $coexistencePlannedId;
			}
			$this->db->table('upgrades_planned')->where('id', $upgradeId)->update($update);
		}

		return $result + [
			'upgrade_id'             => $upgradeId,
			'coexistence_planned_id' => $coexistencePlannedId,
		];
	}

	/**
	 * Derive the coexistence track tag from a target version: '17.2' → 'v17',
	 * '2.13.1' → 'v2', falling back to 'new' when the version is unknown. Matches
	 * the §8 walkthrough's v17 tag for the pg16→17 acceptance run.
	 */
	private function coexistTag(?string $targetVersion): string
	{
		if ($targetVersion === null || $targetVersion === '') {
			return 'new';
		}
		$major = explode('.', ltrim($targetVersion, 'vV'))[0] ?? '';
		return $major !== '' ? 'v' . $major : 'new';
	}

	/**
	 * Returns a human-readable reason if the recipe is NOT applicable to the
	 * installed version (its from_pattern doesn't match), else null. Unknown
	 * installed version or recipe → no objection (can't prove a mismatch).
	 */
	public function recipeMismatch(string $service, string $recipeId): ?string
	{
		$recipe = $this->db->table('upgrade_recipes')
			->where('service', $service)->where('recipe_id', $recipeId)->fetch();
		if ($recipe === null) {
			return "recipe '{$recipeId}' not found for service '{$service}'";
		}
		$pattern = (string) ($recipe->from_pattern ?? '');
		$installed = $this->installedVersionsFromState()[$service] ?? null;
		if ($pattern === '' || $installed === null) {
			return null; // can't evaluate → allow
		}
		if (@preg_match('~' . $pattern . '~', $installed) === 1) {
			return null; // applicable
		}
		return "installed '{$installed}' does not match recipe from-pattern '{$pattern}'"
			. " (target {$recipe->to_version}) — applying it would downgrade or break;"
			. ' pass force=true to override.';
	}

	/** Mark a queued upgrade as applied (called by the upgrade-engine). */
	public function markPlannedApplied(string $service, string $recipeId): void
	{
		// Drop any prior terminal marker first: UNIQUE(service,recipe_id,status)
		// would otherwise collide on a repeat apply of the same recipe.
		$this->db->table('upgrades_planned')
			->where('service', $service)->where('recipe_id', $recipeId)->where('status', 'applied')
			->delete();
		$this->db->table('upgrades_planned')
			->where('service', $service)
			->where('recipe_id', $recipeId)
			->where('status', 'planned')
			->update(['status' => 'applied', 'applied_at' => gmdate('c')]);
	}

	/** Cancel a queued upgrade (by id, or by service+recipe). */
	public function cancelPlanned(int $id): void
	{
		$row = $this->db->table('upgrades_planned')->where('id', $id)->where('status', 'planned')->fetch();
		if ($row === null) {
			return;
		}
		// Avoid the UNIQUE(service,recipe_id,status) collision when a prior
		// cancelled marker for the same recipe already exists.
		$this->db->table('upgrades_planned')
			->where('service', $row->service)->where('recipe_id', $row->recipe_id)->where('status', 'cancelled')
			->delete();
		$this->db->table('upgrades_planned')->where('id', $id)->update(['status' => 'cancelled']);
	}

	/**
	 * All recipes for a given service.
	 */
	public function forService(string $service): ?array
	{
		$resp = $this->box->get('/api/upgrades/' . rawurlencode($service));
		if ($resp['status'] >= 400 || !is_array($resp['body'])) {
			return null;
		}
		return $resp['body'];
	}

	/**
	 * Single recipe detail.
	 */
	public function getRecipe(string $service, string $recipeId): ?array
	{
		$resp = $this->box->get(
			'/api/upgrades/' . rawurlencode($service) . '/' . rawurlencode($recipeId),
		);
		if ($resp['status'] >= 400 || !is_array($resp['body'])) {
			return null;
		}
		return $resp['body'];
	}

	/** Past upgrades for a service (local mirror). */
	public function history(?string $service = null, int $limit = 50): array
	{
		$query = $this->db->table('upgrades_applied')->order('applied_at DESC')->limit($limit);
		if ($service !== null) {
			$query->where('service', $service);
		}
		$out = [];
		foreach ($query->fetchAll() as $row) {
			$item = $row->toArray();
			if (!empty($item['raw_record_json'])) {
				$item['record'] = json_decode($item['raw_record_json'], true);
			}
			$out[] = $item;
		}
		return $out;
	}

	/** Append an upgrade history row. */
	public function recordApplied(array $record): int
	{
		$row = [
			'service'         => (string) ($record['service']      ?? ''),
			'recipe_id'       => (string) ($record['recipe_id']    ?? ''),
			'from_version'    => $record['from_version'] ?? null,
			'to_version'      => $record['to_version']   ?? null,
			'severity'        => $record['severity']     ?? null,
			'applied_at'      => (string) ($record['applied_at']   ?? gmdate('c')),
			'success'         => !empty($record['success']) ? 1 : 0,
			'duration_sec'    => isset($record['duration_sec']) ? (int) $record['duration_sec'] : null,
			'rolled_back'     => !empty($record['rolled_back']) ? 1 : 0,
			'event_run_id'    => $record['event_run_id'] ?? null,
			'raw_record_json' => json_encode($record),
		];
		$this->db->table('upgrades_applied')->insert($row);
		return (int) $this->db->getConnection()->getPdo()->lastInsertId();
	}

	/** Events tied to an upgrade_id. */
	public function getEventsFor(string $upgradeId): array
	{
		return $this->events->listForUpgrade($upgradeId);
	}

	/** BoxAPI passthroughs. */
	public function plan(string $service, string $recipeId): array
	{
		return $this->box->post(
			'/api/upgrades/' . rawurlencode($service) . '/' . rawurlencode($recipeId) . '/plan',
		);
	}

	public function apply(string $service, string $recipeId): array
	{
		return $this->box->post(
			'/api/upgrades/' . rawurlencode($service) . '/' . rawurlencode($recipeId) . '/apply',
		);
	}
}
