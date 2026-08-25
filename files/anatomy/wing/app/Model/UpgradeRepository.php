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
		// B4c: live coexistence tracks keyed by service. When a service is running
		// a dual-version scenario, the matrix shows it TWICE (primary + secondary)
		// with a compact deep-link to /coexistence#<service> (the authoritative
		// toggle lives there — no duplicated toggle logic in the matrix). Reads the
		// local mirror (cheap; same store as pendingCutoverCount).
		$coexistTracks = $this->coexistenceTracksByService();
		// Installed versions from ~/.nos/state.yml — the authoritative source the
		// upgrade-engine itself reads (keyed by the same lowercase service ids as
		// the recipes). systems.version is unreliable (mostly NULL), which left
		// the matrix "installed" column blank.
		$installed = $this->installedVersionsFromState();
		// Pending security rows per service (2026-08-25, REM-159). The matrix is
		// the ONE artifact the upgrade agents read; a security floor that lives
		// only in the remediation queue is a floor no matrix consumer can see —
		// which is how the architect repaired gitlab's stale target to the
		// installed 18.11.9 and made the row read "at target" for a service
		// inside an unauthenticated CVSS 9.4 (floor 19.2.4). The agent did its
		// brief; the wiring withheld the number. NULL map = source unreadable,
		// reported as unavailable, never as green.
		$securityBySvc = $this->pendingSecurityByService();

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
			// A TARGET AT OR BELOW WHAT IS INSTALLED IS NOT AN UPGRADE.
			// `from_pattern` alone does not establish that: gitlab's
			// `^18\.([0-9]|[1-9][0-9])\.` matches an installed 18.11.9 and
			// targets 18.10.3, so the row offered a downgrade as its next step.
			// Drop those, and if nothing survives say the catalog is BEHIND the
			// estate rather than inventing a step (2026-08-25).
			$applicable = array_values(array_filter($applicable, static function ($r) use ($inst) {
				$cmp = self::compareVersions($r['to_version'] ?? null, $inst);
				return $cmp === null || $cmp > 0;
			}));
			$aheadOfCatalog = false;
			if ($applicable === []) {
				$cmp = self::compareVersions($latest, $inst);
				$aheadOfCatalog = ($cmp !== null && $cmp <= 0);
			}
			$next = $applicable !== [] ? end($applicable) : $svcRecipes[0];   // lowest applicable, else highest
			$stable = $next['to_version'] ?? $latest;
			$sev = $next['severity'] ?? 'minor';
			// F1: the plan-choice modal's option (b) "coexist" radio is enabled
			// only when the recipe being planned declares coexistence_supported.
			// The matrix plans $next (the applicable/next step), so the flag must
			// come from THAT recipe — ingested from the recipe YAML into the
			// upgrade_recipes.coexistence_supported column (0/1). Without this the
			// matrix's "Plan" modal hardcoded the option off, greying it out even
			// for postgresql/grafana (which ARE coexistence_supported).
			$coexistSupported = !empty($next['coexistence_supported']);
			$nextRecipeId = (string) ($next['recipe_id'] ?? ($svcRecipes[0]['recipe_id'] ?? ''));
			// Reset-scope (Phase 1): decode the next recipe's resolved reset block —
			// the matrix plans $next, so the blast-radius badge must describe THAT
			// recipe (same reasoning as coexistence_supported above). NULL reset_json
			// → 'container' floor for display (a recipe with restart-class steps but
			// no authored reset must never read as no-restart); the engine derives the
			// real floor at apply time. session_risk is recomputed from scope, never
			// trusted from a stored bool ("derived not authored" doctrine).
			// Mirror coexistence_supported: NO [0] fallback. For a stepping-stone
			// upgrade ($next != latest) the badge must describe $next — borrowing
			// the latest recipe's reset_json would mis-state the planned scope. A
			// NULL on $next resolves to the 'container' display floor for $next.
			$resetData = $this->decodeReset($next['reset_json'] ?? null);
			$sevClass = match ($sev) {
				'breaking'             => 'breaking',
				'security', 'critical' => 'critical',
				'patch', 'minor'       => 'minor',
				default                => 'unknown',
			};
			// At-target = installed is at or past the next target. Compared
			// NUMERICALLY: `===` made `16.15-alpine` differ from `16` for ever,
			// so postgresql and infisical read as upgradable indefinitely.
			$cmpStable = self::compareVersions($inst, $stable);
			$atTarget = $inst !== null && ($cmpStable !== null ? $cmpStable >= 0 : $inst === $stable);
			$base = [
				'id'               => $service,
				'service'          => $service,
				'category'         => null,
				'installed'        => $inst,
				'installed_class'  => $atTarget ? 'current' : ($inst !== null ? 'minor' : 'unknown'),
				'stable'           => $stable,
				'stable_class'     => $atTarget ? 'current' : $sevClass,
				'latest'           => $latest,
				'latest_class'     => ($inst !== null
					&& (($c = self::compareVersions($inst, $latest)) !== null ? $c >= 0 : $inst === $latest))
					? 'current' : $sevClass,
				// The catalog has nothing left above the running version. Not
				// "up to date" — the RECIPES are behind, which is a different
				// fact and the operator must not read one as the other.
				'ahead_of_catalog' => $aheadOfCatalog,
				// Security posture from the remediation queue. null = no pending
				// row for this service; ['unavailable' => true] = the queue
				// mirror could not be read (UNKNOWN, not green); otherwise
				// {pending_ids, max_severity, floor, below_floor}. below_floor
				// true means: whatever "at target" says, this service runs
				// UNDER its security floor and the gap is still open.
				'security'         => $securityBySvc === null
					? ['unavailable' => true]
					: self::securityPosture($inst, $securityBySvc[$service] ?? []),
				'upstream'         => null,        // offline matrix — no upstream scanner (B1 decision)
				'upstream_class'   => 'unknown',
				'severity'         => $sev,
				'recipe_available' => true,
				'recipe_count'     => count($svcRecipes),
				'recipes'          => $svcRecipes,
				// F1: the next applicable recipe + its coexistence flag, so the
				// matrix's Plan modal plans the SAME recipe the flag describes and
				// enables/disables option (b) truthfully (was hardcoded off).
				'next_recipe_id'        => $nextRecipeId,
				'coexistence_supported' => $coexistSupported,
				// Reset-scope (Phase 1): the resolved reset block + scalar scope +
				// derived session_risk for the disruption preview in the plan-choice
				// modal (Phase 2 reads $row['reset_scope']/$row['session_risk']).
				'reset'            => $resetData['reset'],
				'reset_scope'      => $resetData['scope'],
				'session_risk'     => $resetData['session_risk'],
				'planned'          => isset($planned[$service]),
				'planned_target'   => $planned[$service]['target_version'] ?? null,
				'planned_by'       => $planned[$service]['planned_by'] ?? null,
				// F2: the recipe id behind a queued upgrade, so the matrix's
				// "planned" badge can deep-link to the SPECIFIC recipe card on
				// /upgrades/<service>#recipe-<id> (where the steps/changelog
				// already render). The detail page is the single recipe-rendering
				// surface — the matrix only links to it, never duplicates it.
				'planned_recipe_id' => $planned[$service]['recipe_id'] ?? null,
			];

			// B4c: a coexisting service renders as TWO rows (primary + secondary),
			// each carrying a coexist_role + the live track tag/version so the
			// template shows a role badge and a deep-link to /coexistence#<service>
			// (the single source of toggle truth). A non-coexisting service is one
			// plain row, exactly as before.
			$tracks = $coexistTracks[$service] ?? [];
			if (count($tracks) > 1) {
				foreach ($tracks as $t) {
					$out[] = $base + [
						'coexist_role'    => (string) ($t['role'] ?? ($t['active'] ? 'primary' : 'secondary')),
						'coexist_tag'     => $t['tag'] ?? null,
						'coexist_version' => $t['version'] ?? null,
						'coexist_active'  => !empty($t['active']),
					];
				}
			} else {
				$out[] = $base;
			}
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
	/**
	 * Compare two version strings numerically. Returns -1/0/1, or null when
	 * either side carries no digits to compare.
	 *
	 * WHY THIS EXISTS. The matrix compared versions with `===` and ordered the
	 * catalog with a STRING sort. Both are wrong for versions, and both failed
	 * in the same direction — towards "an upgrade is available":
	 *
	 *   `16.15-alpine` !== `16`          → postgresql read as upgradable for ever
	 *   `v0.162.19`    !== `0.160.4`     → infisical likewise
	 *
	 * Measured 2026-08-25: 22 of 29 catalog targets sat AT OR BELOW the running
	 * version, and the page presented them as the next step. For GitLab it
	 * offered `18.10.3-ce.0` against a box running `18.11.9-ce.0` — a DOWNGRADE
	 * shown as an upgrade, on the one service then carrying an unauthenticated
	 * CVSS 9.4 whose floor is 19.2.4.
	 *
	 * Suffixes are ignored deliberately: `-ce.0`, `-alpine`, `-ls264` and a
	 * leading `v` are packaging, not version. Where that is not true the
	 * comparison returns null and the caller must not claim anything — the
	 * estate's rule that an unreadable answer is UNKNOWN, never green.
	 */
	/**
	 * Pending remediation rows grouped by component_id, or NULL when the
	 * mirror is unreadable (missing table/column on a pre-migration DB). The
	 * caller must surface NULL as "unavailable" — an unreadable security
	 * source must never render as "no pending findings".
	 *
	 * @return array<string,array<int,array{id:string,severity:string,security_floor:?string}>>|null
	 */
	private function pendingSecurityByService(): ?array
	{
		try {
			$out = [];
			$rows = $this->db->query(
				"SELECT id, component_id, severity, security_floor
				 FROM remediation_items WHERE status = 'pending' AND component_id IS NOT NULL",
			);
			foreach ($rows as $r) {
				$out[(string) $r->component_id][] = [
					'id'             => (string) $r->id,
					'severity'       => (string) $r->severity,
					'security_floor' => $r->security_floor !== null ? (string) $r->security_floor : null,
				];
			}
			return $out;
		} catch (\Throwable) {
			return null;
		}
	}

	/**
	 * Fold a service's pending remediation rows into the matrix row's
	 * security posture. Pure and static so the gate can exercise it without a
	 * DB — the same testability split as compareVersions.
	 *
	 *   null                      — no pending rows: nothing to say.
	 *   max_severity              — worst pending severity (CRITICAL first).
	 *   floor                     — highest machine-readable security_floor
	 *                               among the pending rows (versions compare
	 *                               numerically; an uncomparable candidate
	 *                               never displaces a comparable one).
	 *   below_floor               — installed < floor. NULL when there is no
	 *                               floor or the comparison refuses: UNKNOWN
	 *                               is not false, and a consumer treating
	 *                               null as "fine" repeats the 2026-08-25
	 *                               blindness this field exists to end.
	 *
	 * @param array<int,array{id:string,severity:string,security_floor:?string}> $rows
	 * @return array{pending_ids:array<int,string>,max_severity:?string,floor:?string,below_floor:?bool}|null
	 */
	public static function securityPosture(?string $installed, array $rows): ?array
	{
		if ($rows === []) {
			return null;
		}
		$rank = ['CRITICAL' => 4, 'HIGH' => 3, 'MEDIUM' => 2, 'LOW' => 1];
		$ids = [];
		$maxSev = null;
		$floor = null;
		foreach ($rows as $r) {
			$ids[] = $r['id'];
			$sev = strtoupper((string) ($r['severity'] ?? ''));
			if (($rank[$sev] ?? 0) > ($rank[$maxSev ?? ''] ?? 0)) {
				$maxSev = $sev;
			}
			$cand = $r['security_floor'] ?? null;
			if ($cand === null || $cand === '') {
				continue;
			}
			if ($floor === null) {
				$floor = $cand;
				continue;
			}
			$cmp = self::compareVersions($cand, $floor);
			if ($cmp !== null && $cmp > 0) {
				$floor = $cand;
			}
		}
		$below = null;
		if ($floor !== null && $installed !== null) {
			$cmp = self::compareVersions($installed, $floor);
			$below = $cmp === null ? null : $cmp < 0;
		}
		return [
			'pending_ids'  => $ids,
			'max_severity' => $maxSev,
			'floor'        => $floor,
			'below_floor'  => $below,
		];
	}

	public static function compareVersions(?string $a, ?string $b): ?int
	{
		$parse = static function (?string $v): array {
			// A VERSION STARTS WITH ITS NUMBER — after an optional `v`. That is
			// what separates `16` (a major-only recipe target, real) from
			// `sha-b9a80dc` (a build id, from which [9, 80, 0] could be pulled
			// and two unrelated digests ordered with confidence). paperclip is
			// pinned that way, and `latest` is not a version either.
			//
			// Requiring a DOTTED core was the first cut and it was too strict:
			// it refused `16` and so broke the postgresql case this whole
			// comparison exists to fix.
			$t = ltrim(trim((string) $v), 'vV');
			if (!preg_match('/^\d+(?:\.\d+)*/', $t, $core)) {
				return [];
			}
			preg_match_all('/\d+/', $core[0], $m);
			return array_map('intval', array_slice($m[0], 0, 4));
		};
		$x = $parse($a);
		$y = $parse($b);
		if ($x === [] || $y === []) {
			return null;
		}
		$n = max(count($x), count($y));
		for ($i = 0; $i < $n; $i++) {
			$xi = $x[$i] ?? 0;
			$yi = $y[$i] ?? 0;
			if ($xi !== $yi) {
				return $xi <=> $yi;
			}
		}
		return 0;
	}

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
	 * The host_reboot pending marker (Phase 3), or null when none is present.
	 *
	 * The upgrade-engine writes ~/.nos/reboot-required.json after a successful
	 * host_reboot-class apply — completing the change needs a full machine reboot
	 * (the engine NEVER auto-reboots; destructive-op safety = manual over auto).
	 * Wing surfaces it as a persistent /upgrades banner until the operator reboots
	 * (which clears the marker). Read from the SAME ~/.nos/ runtime sidecar the
	 * engine + state_manager use; Wing runs as launchd so getenv('HOME') resolves
	 * to the operator home (same convention installedVersionsFromState() uses).
	 *
	 * Honest-absent: a missing OR malformed marker returns null (no banner) — an
	 * unreadable sidecar must never crash the page or spuriously nag.
	 *
	 * @return array<string,mixed>|null { service, recipe_id, upgrade_id, scope, requested_at }
	 */
	public function rebootMarker(): ?array
	{
		$home = getenv('HOME') ?: '';
		if ($home === '') {
			return null;
		}
		$path = $home . '/.nos/reboot-required.json';
		if (!is_file($path)) {
			return null;
		}
		$raw = @file_get_contents($path);
		if ($raw === false || $raw === '') {
			return null;
		}
		try {
			$marker = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
		} catch (\JsonException) {
			return null;
		}
		// A well-formed marker is a JSON object; anything else (array/scalar/null)
		// is malformed → no banner.
		if (!is_array($marker) || $marker === [] || array_is_list($marker)) {
			return null;
		}
		return $marker;
	}

	/**
	 * Read a ~/.nos/<name> JSON sidecar as an object, else null (absent/malformed).
	 * Honest-absent — an unreadable sidecar never crashes the page. (rebootMarker()
	 * keeps its own inline read to preserve its gate test; this is the shared
	 * reader for the macOS os-update surface below.)
	 */
	private function readNosObject(string $name): ?array
	{
		$home = getenv('HOME') ?: '';
		if ($home === '') {
			return null;
		}
		$path = $home . '/.nos/' . $name;
		if (!is_file($path)) {
			return null;
		}
		$raw = @file_get_contents($path);
		if ($raw === false || $raw === '') {
			return null;
		}
		try {
			$data = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
		} catch (\JsonException) {
			return null;
		}
		if (!is_array($data) || $data === [] || array_is_list($data)) {
			return null;
		}
		return $data;
	}

	/**
	 * macOS-as-managed-upgrade surface (Increment 3c): the ARMED continuation plan
	 * (~/.nos/continuation-plan.json — a macOS update is staged; safe to update +
	 * restart) and the LAST settle result (~/.nos/os-resume-result.json —
	 * os_before -> os_after, clean/warnings) written by the login-agent resume.
	 * Returns null when neither sidecar is present (nothing to surface).
	 *
	 * @return array{armed:?array<string,mixed>, last_settle:?array<string,mixed>}|null
	 */
	public function osUpdateState(): ?array
	{
		$armed = $this->readNosObject('continuation-plan.json');
		$lastSettle = $this->readNosObject('os-resume-result.json');
		if ($armed === null && $lastSettle === null) {
			return null;
		}
		return ['armed' => $armed, 'last_settle' => $lastSettle];
	}

	/**
	 * Live coexistence tracks keyed by service (B4c), read from the local mirror
	 * (`coexistence_tracks`). Primary first (role='primary' / active=1), so the
	 * matrix renders the active version on top. A service with 0 or 1 track is
	 * still returned but the matrix only doubles when count > 1.
	 *
	 * @return array<string,array<int,array<string,mixed>>>
	 */
	private function coexistenceTracksByService(): array
	{
		$out = [];
		// active DESC → role='primary'/active=1 first; tag ASC for a stable order.
		foreach ($this->db->table('coexistence_tracks')->order('service ASC, active DESC, tag ASC') as $r) {
			$item = $r->toArray();
			$out[(string) $item['service']][] = $item;
		}
		return $out;
	}

	/**
	 * Decode an upgrade_recipes.reset_json cell into the spread shape the matrix +
	 * detail cards use (Phase 1). Mirrors how coexistence_supported is normalised,
	 * but for the resolved reset block:
	 *
	 *   - `reset`        — the decoded authored block (or [] when NULL/garbage).
	 *   - `scope`        — the reset.scope, defaulting to 'container' when absent.
	 *                      A NULL reset_json means the recipe authored no reset and
	 *                      the engine derives the real floor at apply time; for
	 *                      DISPLAY we never read it as 'none' (a recipe with restart-
	 *                      class steps must not look like a no-restart change).
	 *   - `session_risk` — DERIVED from scope (scope ∈ {host_app, host_reboot}),
	 *                      recomputed here rather than trusting any stored bool
	 *                      ("derived not authored" doctrine).
	 *
	 * @return array{reset:array<string,mixed>, scope:string, session_risk:bool}
	 */
	private function decodeReset(?string $resetJson): array
	{
		$decoded = ($resetJson !== null && $resetJson !== '')
			? json_decode($resetJson, true)
			: null;
		// Normalize to an array BEFORE reading any key — a truthy scalar reset_json
		// (e.g. a bare number/string that json_decode returns as int/string) would
		// otherwise trigger an "array offset on scalar" warning on $reset['scope'].
		$reset = is_array($decoded) ? $decoded : [];
		// A malformed authored block could carry a non-array affected_* value;
		// force arrays so the Latte `|implode` in the disruption badge is type-safe.
		foreach (['affected_services', 'affected_host_apps'] as $k) {
			if (isset($reset[$k]) && !is_array($reset[$k])) {
				$reset[$k] = [];
			}
		}
		$scope = is_string($reset['scope'] ?? null) ? $reset['scope'] : 'container';
		return [
			'reset'        => $reset,
			'scope'        => $scope,
			'session_risk' => in_array($scope, ['host_app', 'host_reboot'], true),
		];
	}

	/**
	 * Resolve a single recipe's reset block by service+recipe_id — the SAME
	 * decode the matrix runs per row, but scoped to the recipe being planned.
	 * Used by planUpgradeWithMode() to snapshot reset_scope + session_risk onto
	 * the queued row. An unknown recipe (no row) decodes a NULL reset_json → the
	 * 'container' display floor (a recipe with restart-class steps must never read
	 * as no-restart), session_risk false.
	 *
	 * @return array{reset:array<string,mixed>, scope:string, session_risk:bool}
	 */
	private function resetForRecipe(string $service, string $recipeId): array
	{
		$recipe = $this->db->table('upgrade_recipes')
			->where('service', $service)->where('recipe_id', $recipeId)->fetch();
		return $this->decodeReset($recipe !== null ? ($recipe->reset_json ?? null) : null);
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
	 * @return array{ok:bool, status:string, detail:string, upgrade_id:int|null, coexistence_planned_id:int|null, reset_scope?:string, session_risk?:bool, run_mode?:string}
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
		?string $notes = null,
		string $runMode = 'attached'
	): array {
		$mode = ($mode === 'coexist') ? 'coexist' : 'migration';
		// Phase 2: run_mode is the operator's chosen execution shape. Validate it
		// against the closed set; anything else falls back to 'attached' (the only
		// safe default — never trust a body value into a free-text column).
		$runMode = in_array($runMode, ['attached', 'detached', 'stage_then_reboot'], true)
			? $runMode : 'attached';
		// Phase 2: resolve THIS recipe's authored reset block (same source the
		// matrix decodes for the disruption preview) so the queued row snapshots the
		// blast radius. session_risk is RECOMPUTED from the resolved scope, never
		// trusted from the client ("derived not authored" doctrine — see decodeReset).
		$reset = $this->resetForRecipe($service, $recipeId);
		$resetScope = $reset['scope'];
		$sessionRisk = $reset['session_risk'];
		// Defence in depth (mirrors the JS gate, which only offers stage_then_reboot
		// for a host_reboot scope): a crafted POST of stage_then_reboot against a
		// non-host_reboot recipe is downgraded so the stored snapshot stays honest.
		if ($runMode === 'stage_then_reboot' && $resetScope !== 'host_reboot') {
			$runMode = $sessionRisk ? 'detached' : 'attached';
		}
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
			// Phase 2: snapshot the resolved reset scope + the derived session_risk
			// + the operator's run_mode onto the queued row (columns already exist —
			// reset_scope TEXT / session_risk INTEGER / run_mode TEXT). These are a
			// UI/audit snapshot; the engine re-resolves the AUTHORED reset at apply
			// time via reset_scope.resolve_reset() (source of truth there).
			$update = [
				'plan_mode'      => $mode,
				'plan_choice_at' => gmdate('c'),
				'reset_scope'    => $resetScope,
				'session_risk'   => $sessionRisk ? 1 : 0,
				'run_mode'       => $runMode,
			];
			if ($coexistencePlannedId !== null) {
				$update['coexistence_planned_id'] = $coexistencePlannedId;
			}
			$this->db->table('upgrades_planned')->where('id', $upgradeId)->update($update);
		}

		return $result + [
			'upgrade_id'             => $upgradeId,
			'coexistence_planned_id' => $coexistencePlannedId,
			// Phase 2: hand back the snapshotted execution-shape fields so the
			// presenter can fold them into the plan_choice_recorded audit payload.
			'reset_scope'            => $resetScope,
			'session_risk'           => $sessionRisk,
			'run_mode'               => $runMode,
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
	 * All recipes for a given service — built OFFLINE from the local
	 * upgrade_recipes catalog, the SAME source matrix() reads.
	 *
	 * F4 (2026-06-19): the /upgrades/<service> detail page rendered EMPTY because
	 * this method sourced its `{service, docs_url, recipes:[]}` from a live Bone
	 * call (`GET /api/upgrades/<service>`) that returns null/empty here — while
	 * matrix() (the /upgrades list, which renders recipes fine) reads the local
	 * SQLite table. The detail page is the single recipe-rendering surface (F2
	 * deep-link target `#recipe-<id>`), so it MUST NOT depend on a live Bone call.
	 *
	 * Recipes come from `SELECT … FROM upgrade_recipes WHERE service = ?`, ordered
	 * `to_version DESC` (matrix's order → [0] is the latest target). Each recipe
	 * is mapped to the keys service.latte reads (id, from_regex, to, severity,
	 * notes, changelog_url, coexistence_supported, applied). `applied` is a
	 * best-effort flag from the local upgrades_applied mirror.
	 *
	 * BoxAPI is kept ONLY as an OPTIONAL best-effort overlay (e.g. an `upstream`
	 * latest-version field): it NEVER empties the recipe list and a Bone outage
	 * is invisible to the operator.
	 *
	 * Returns null ONLY when the service has no recipes at all (so the presenter's
	 * `notFound` stays correct — true iff there is genuinely nothing to render).
	 *
	 * @return array{service:string, docs_url:?string, recipes:array<int,array<string,mixed>>, upstream?:?string}|null
	 */
	public function forService(string $service): ?array
	{
		// Applied recipe ids for this service (local mirror) → the per-card
		// "applied" flag. Best-effort; an empty/absent mirror just means no flags.
		$applied = [];
		foreach ($this->db->table('upgrades_applied')->where('service', $service) as $a) {
			if (!empty($a->recipe_id)) {
				$applied[(string) $a->recipe_id] = true;
			}
		}

		$recipes = [];
		$docsUrl = null;
		foreach (
			$this->db->table('upgrade_recipes')
				->where('service', $service)
				->order('to_version DESC') as $r
		) {
			$row = $r->toArray();
			$recipeId = (string) ($row['recipe_id'] ?? '');
			// docs_url for the "Upstream docs" link — first non-empty recipe value.
			if ($docsUrl === null && !empty($row['docs_url'])) {
				$docsUrl = (string) $row['docs_url'];
			}
			$recipes[] = [
				// service.latte recipe-card keys (mapped from the catalog columns).
				'id'                    => $recipeId,
				'recipe_id'             => $recipeId,
				'from_regex'            => $row['from_pattern'] ?? null,
				'from_pattern'          => $row['from_pattern'] ?? null,
				'to'                    => $row['to_version'] ?? null,
				'to_version'            => $row['to_version'] ?? null,
				'severity'              => $row['severity'] ?? 'minor',
				// `title` is the catalog's human description → the card's notes line;
				// `docs_url` doubles as the per-recipe changelog link.
				'notes'                 => $row['title'] ?? null,
				'title'                 => $row['title'] ?? null,
				'changelog_url'         => $row['docs_url'] ?? null,
				'docs_url'              => $row['docs_url'] ?? null,
				'coexistence_supported' => !empty($row['coexistence_supported']),
				// Reset-scope (Phase 1): per-recipe card carries the resolved reset
				// block + scalar scope + derived session_risk, mirroring the matrix()
				// spread (NULL reset_json → 'container' floor; session_risk recomputed).
				'reset'                 => ($cardReset = $this->decodeReset($row['reset_json'] ?? null))['reset'],
				'reset_scope'           => $cardReset['scope'],
				'session_risk'          => $cardReset['session_risk'],
				'applied'               => isset($applied[$recipeId]),
			];
		}

		// notFound when the service has no recipes at all (presenter's `notFound`).
		if ($recipes === []) {
			return null;
		}

		$out = [
			'service'  => $service,
			'docs_url' => $docsUrl,
			'recipes'  => $recipes,
		];

		// Best-effort BoxAPI overlay: enrich with the live `upstream` latest
		// version when Bone answers, but NEVER let a Bone outage empty the page.
		// The recipe cards already come from the local catalog above.
		try {
			$resp = $this->box->get('/api/upgrades/' . rawurlencode($service));
			if (($resp['status'] ?? 500) < 400 && is_array($resp['body'] ?? null)) {
				$upstream = $resp['body']['upstream'] ?? null;
				if ($upstream !== null && $upstream !== '') {
					$out['upstream'] = (string) $upstream;
				}
			}
		} catch (\Throwable) {
			// Bone unreachable — the local catalog is authoritative; ignore.
		}

		return $out;
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

	/**
	 * Launch the upgrade DETACHED (run_mode=detached, or a session_risk recipe
	 * that plain apply() refuses with 409). Bone shells to nos-upgrade-detached.sh
	 * so the run survives the operator's session dying. Phase-4 plan->detached.
	 */
	public function applyDetached(string $service, string $recipeId): array
	{
		return $this->box->post(
			'/api/upgrades/' . rawurlencode($service) . '/' . rawurlencode($recipeId) . '/apply-detached',
		);
	}
}
