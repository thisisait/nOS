<?php

declare(strict_types=1);

namespace App\Presenters;

use App\AgentKit\OperatorTrigger;
use App\AgentKit\OperatorTriggerException;
use App\Model\EventRepository;
use App\Model\MigrationAuthoredRepository;
use App\Model\UpgradeRepository;

/**
 * /upgrades — matrix of services with upgrade availability.
 * /upgrades/<service> — recipes + history for a single service.
 */
final class UpgradesPresenter extends BasePresenter
{
	protected string $activeTab = 'upgrades';

	// RBAC: queuing an upgrade (actionQueueUpgrade) mutates upgrades_planned,
	// which the engine auto-applies under `--tags upgrade`. Tier-1 only — gated
	// by default in BasePresenter::startup() via this one property (matches the
	// forward-auth tier-1 boundary on wing.<tld>; defense-in-depth so a future
	// edge-config slip can't expose the queue to a lower tier).
	protected ?int $minAccessTier = 1;

	public function __construct(
		private UpgradeRepository $upgrades,
		private EventRepository $events,
		// B4c: the per-service Proposals strip surfaces the agent-authored
		// migrations_authored drafts (with the local-forge MR link). Read-only
		// here; the producer write is the bearer Api\MigrationsPresenter.
		private MigrationAuthoredRepository $authored,
		// A3.2 (Q5/2026-06-16): the "Promote to migration" button fires the
		// native AgentKit migration-author through the SHARED spawn path (also
		// used by the bearer Api\AgentsPresenter). One audited place keeps the
		// actor-as-itself / operator-as-supervisor split honest.
		private OperatorTrigger $operatorTrigger,
	) {
	}

	/**
	 * Template vars:
	 *   services: list<array{
	 *     id:string, installed:?string, stable:?string, latest:?string,
	 *     severity:?string, recipe_available:bool
	 *   }>
	 *   countsBySeverity: array<string,int>
	 *   upgradeAvailable: int
	 */
	public function renderDefault(): void
	{
		$services = $this->upgrades->matrix();

		$counts = ['patch' => 0, 'minor' => 0, 'breaking' => 0];
		$available = 0;
		foreach ($services as $s) {
			if (!empty($s['recipe_available'])) {
				$available++;
			}
			$sev = $s['severity'] ?? null;
			if ($sev !== null && isset($counts[$sev])) {
				$counts[$sev]++;
			}
		}

		// $matrix is the variable the /upgrades template reads (both are set).
		$this->template->matrix = $services;
		$this->template->services = $services;
		$this->template->countsBySeverity = $counts;
		$this->template->upgradeAvailable = $available;
		$this->template->plannedCount = count($this->upgrades->listPlanned());
	}

	/**
	 * POST /upgrades/<service>/<recipe>/queue — operator queues an upgrade
	 * (W5-B2). Mirrors the bearer API but for the browser: CSRF-gated,
	 * planned_by is the forward-auth operator identity. The upgrade-engine
	 * applies the queue under --tags upgrade.
	 */
	public function actionQueueUpgrade(string $service, string $recipe): void
	{
		$this->requirePostMethod();
		$target = $this->getHttpRequest()->getPost('target_version');
		$force = (bool) $this->getHttpRequest()->getPost('force');
		$plannedBy = (string) ($this->getHttpRequest()->getHeader('X-Authentik-Username') ?? 'operator');
		$result = $this->upgrades->planUpgrade(
			$service,
			$recipe,
			is_string($target) && $target !== '' ? $target : null,
			$plannedBy !== '' ? $plannedBy : 'operator',
			null,
			$force,
		);
		[$msg, $type] = match ($result['status']) {
			'queued'         => ["Queued {$service}/{$recipe} — applies on: ansible-playbook main.yml --tags upgrade", 'success'],
			'already_queued' => ["{$service}/{$recipe} is already queued.", 'info'],
			'mismatch'       => ["Refused — {$result['detail']}", 'error'],
			default          => [$result['detail'], 'info'],
		};
		$this->flashMessage($msg, $type);
		$this->redirect('Upgrades:default');
	}

	/**
	 * POST /upgrades/<service>/cancel-planned (F3, 2026-06-18) — the Tier-1
	 * "Unqueue" control on a planned row. Resets a planned upgrade back to
	 * unqueued so the operator can re-run the plan-choice flow to TEST it — via
	 * the machinery, NOT a hand DB poke. Reuses UpgradeRepository::cancelPlanned
	 * (flips status planned → cancelled by id; no parallel path).
	 *
	 * Tier-1 inherited ($minAccessTier=1, BasePresenter::startup). CSRF via
	 * requirePostMethod. The operator identity is read from the forward-auth
	 * header (never the body) and travels as the audit actor_id. The matrix maps
	 * one planned row per service, so the route keys on <service>; an optional
	 * posted recipe_id disambiguates if more than one recipe is queued.
	 */
	public function actionCancelPlanned(string $service): void
	{
		$this->requirePostMethod();
		$triggeredBy = (string) ($this->getHttpRequest()->getHeader('X-Authentik-Username') ?? 'operator');
		$triggeredBy = $triggeredBy !== '' ? $triggeredBy : 'operator';
		$recipeWanted = (string) ($this->getHttpRequest()->getPost('recipe_id') ?? '');

		// Resolve the planned row id from service (and recipe, when posted) — the
		// only place we read the queue; cancelPlanned() then guards on status.
		$planned = null;
		foreach ($this->upgrades->listPlanned() as $row) {
			if ((string) ($row['service'] ?? '') !== $service) {
				continue;
			}
			if ($recipeWanted !== '' && (string) ($row['recipe_id'] ?? '') !== $recipeWanted) {
				continue;
			}
			$planned = $row;
			break;
		}

		if ($planned === null || !isset($planned['id'])) {
			$this->flashMessage("Refused — no planned upgrade for {$service} to unqueue.", 'error');
			$this->redirect('Upgrades:default');
		}

		$this->upgrades->cancelPlanned((int) $planned['id']);
		$this->emitUpgradeUnqueued($service, $planned, $triggeredBy);

		$recipe = (string) ($planned['recipe_id'] ?? '');
		$this->flashMessage(
			"Unqueued {$service}" . ($recipe !== '' ? "/{$recipe}" : '')
			. " — Plan it again to re-run the plan-choice flow.",
			'success',
		);
		$this->redirect('Upgrades:default');
	}

	/**
	 * Best-effort upgrade_unqueued emit (F3) — the operator's unqueue supervision
	 * event. actor_id is the operator; result carries the row identity so the
	 * audit reconstructs which queued upgrade was reset. Never blocks the cancel:
	 * an audit failure must not surface as a UI error after the row already
	 * flipped to cancelled.
	 *
	 * @param array<string,mixed> $planned
	 */
	private function emitUpgradeUnqueued(string $service, array $planned, string $triggeredBy): void
	{
		try {
			$this->events->insert([
				'type'       => 'upgrade_unqueued',
				'task'       => 'unqueue-planned: ' . $service
					. (isset($planned['recipe_id']) ? '/' . (string) $planned['recipe_id'] : ''),
				'source'     => 'wing',
				'actor_id'   => $triggeredBy,
				'upgrade_id' => isset($planned['id']) ? (string) $planned['id'] : null,
				'result'     => [
					'service'        => $service,
					'recipe_id'      => $planned['recipe_id'] ?? null,
					'target_version' => $planned['target_version'] ?? null,
					'planned_by'     => $planned['planned_by'] ?? null,
				],
			]);
		} catch (\Throwable) {
			// audit failure must not block the operator's action.
		}
	}

	/**
	 * POST /upgrades/<service>/<recipe>/plan-choice — the browser commit target
	 * for the plan-choice modal (B4b). The operator picks one of two paths in the
	 * modal, the hidden CSRF form posts here:
	 *   (a) plan_mode='migration' → in-place upgrade, no coexistence track
	 *   (b) plan_mode='coexist'   → coexisting new version with a data copy
	 *
	 * CSRF-gated (requirePostMethod); planned_by is the forward-auth operator
	 * identity (never body-supplied), matching actionQueueUpgrade. Reuses the same
	 * repo method as the bearer API (UpgradeRepository::planUpgradeWithMode) so the
	 * browser + agent paths write identical rows. Emits plan_choice_recorded
	 * (Wing-side EventRepository::insert directly, like UsersPresenter), then
	 * redirects to /coexistence (mode b) or /upgrades (mode a) with a flash —
	 * preserving the redirect+flash UX (no JSON, no fetch).
	 */
	public function actionPlanChoice(string $service, string $recipe): void
	{
		$this->requirePostMethod();
		$req = $this->getHttpRequest();
		$mode = $req->getPost('plan_mode') === 'coexist' ? 'coexist' : 'migration';
		$target = $req->getPost('target_version');
		$portOffsetRaw = $req->getPost('port_offset');
		$portOffset = is_numeric($portOffsetRaw) ? (int) $portOffsetRaw : 100;
		// data_copy defaults TRUE (path (b) means "with a copy of the data"); an
		// explicit '0'/'' unchecks it. Irrelevant for mode 'migration'.
		$dataCopyRaw = $req->getPost('data_copy');
		$dataCopy = $dataCopyRaw === null ? true : (bool) $dataCopyRaw;
		$force = (bool) $req->getPost('force');
		$plannedBy = (string) ($req->getHeader('X-Authentik-Username') ?? 'operator');
		$plannedBy = $plannedBy !== '' ? $plannedBy : 'operator';

		$result = $this->upgrades->planUpgradeWithMode(
			$service,
			$recipe,
			is_string($target) && $target !== '' ? $target : null,
			$plannedBy,
			$mode,
			$portOffset,
			$dataCopy,
			$force,
		);

		if (!empty($result['ok'])) {
			$this->emitPlanChoiceRecorded($service, $recipe, $mode, $result, $dataCopy, $portOffset, $plannedBy);
		}

		[$msg, $type] = match ($result['status']) {
			'queued'         => $mode === 'coexist'
				? ["Planned {$service}/{$recipe} — coexist track queued; provision under: ansible-playbook main.yml --tags coexistence (after the migration MR is merged).", 'success']
				: ["Planned {$service}/{$recipe} — applies on: ansible-playbook main.yml --tags upgrade.", 'success'],
			'already_queued' => ["{$service}/{$recipe} is already queued.", 'info'],
			'mismatch'       => ["Refused — {$result['detail']}", 'error'],
			default          => [$result['detail'] ?? 'No change.', 'info'],
		};
		$this->flashMessage($msg, $type);
		// Mode (b) lands on /coexistence where the queued track + primary/secondary
		// controls live; mode (a) stays on /upgrades.
		$this->redirect($mode === 'coexist' ? 'Coexistence:default' : 'Upgrades:default');
	}

	/**
	 * Best-effort plan_choice_recorded emit (upgrade_id-keyed §2.6 — mirrors the
	 * bearer Api\UpgradesPresenter::emitPlanChoice). Never blocks the plan-choice
	 * write: an audit failure must not abort the operator's action.
	 *
	 * @param array<string,mixed> $result
	 */
	private function emitPlanChoiceRecorded(string $service, string $recipe, string $mode, array $result, bool $dataCopy, int $portOffset, string $plannedBy): void
	{
		try {
			$this->events->insert([
				'type'       => 'plan_choice_recorded',
				'task'       => 'plan-choice ' . $mode . ': ' . $service . '/' . $recipe,
				'source'     => 'wing',
				'actor_id'   => $plannedBy,
				'upgrade_id' => isset($result['upgrade_id']) ? (string) $result['upgrade_id'] : null,
				'result'     => [
					'service'                => $service,
					'recipe_id'              => $recipe,
					'plan_mode'              => $mode,
					'coexistence_planned_id' => $result['coexistence_planned_id'] ?? null,
					'data_copy'              => $dataCopy,
					'port_offset'            => $portOffset,
				],
			]);
		} catch (\Throwable) {
			// audit failure must not block the plan-choice write.
		}
	}

	// A3.2: the migration-author runs AS ITSELF — its own Authentik client
	// (authentik_agent_clients[nos-migration-author], holds nos:migration:write).
	// The operator who pressed the button is captured separately as triggered_by
	// (in the prompt + the supervision event), NEVER as the agent's actor_id.
	// Doctrine: the agent's audit identity is its scope; the operator supervises.
	private const MIGRATION_AUTHOR_AGENT = 'migration-author';
	private const MIGRATION_AUTHOR_ACTOR = 'nos-migration-author';

	/**
	 * POST /upgrades/<service>/<recipe>/promote-to-migration (A3.2, Q5) —
	 * the Tier-1 "Promote to migration" button. Fires the NATIVE AgentKit
	 * migration-author (OperatorTrigger spawn → agent_sessions/threads/iterations
	 * + OTel → Wing /agents + Grafana 22-ai-agents), which writes the migration
	 * YAML + a default.config.yml version bump (gated migration-file-write tool)
	 * and reports under `## Migration author report`. The forge MR (GATE 2) is
	 * the wall — the button makes NOTHING live.
	 *
	 * Tier-1 inherited ($minAccessTier=1, BasePresenter::startup). CSRF via
	 * requirePostMethod. The operator identity is read from the forward-auth
	 * header (never the body) and travels as NOS_TRIGGERED_BY + the audit
	 * actor_id of the supervision event; the agent spawns under its OWN client.
	 * Guarded by migrationGap() so a missing recipe / no-gap never opens an empty
	 * session.
	 */
	public function actionPromoteToMigration(string $service, string $recipe): void
	{
		$this->requirePostMethod();
		$triggeredBy = (string) ($this->getHttpRequest()->getHeader('X-Authentik-Username') ?? 'operator');
		$triggeredBy = $triggeredBy !== '' ? $triggeredBy : 'operator';

		// Guard: refuse if the recipe doesn't exist (no empty session).
		if (!$this->migrationGap($service, $recipe)) {
			$this->flashMessage(
				"Refused — no recipe '{$recipe}' for {$service} to promote (nothing to author).",
				'error',
			);
			$this->redirect('Upgrades:service', ['service' => $service]);
		}

		// Per-run context the migration-author's system prompt reads (the flat
		// profile documents these env keys). NOS_TRIGGERED_BY records the
		// supervising operator WITHOUT making them the agent's actor.
		$prompt = "Promote the merged recipe to a migration record.\n"
			. "NOS_MIGRATION_SERVICE={$service}\n"
			. "NOS_MIGRATION_RECIPE_ID={$recipe}\n"
			. "NOS_TRIGGERED_BY={$triggeredBy}\n";
		$env = [
			'NOS_MIGRATION_SERVICE'   => $service,
			'NOS_MIGRATION_RECIPE_ID' => $recipe,
			'NOS_TRIGGERED_BY'        => $triggeredBy,
		];

		try {
			$res = $this->operatorTrigger->spawn(
				agent: self::MIGRATION_AUTHOR_AGENT,
				actorId: self::MIGRATION_AUTHOR_ACTOR,
				prompt: $prompt,
				env: $env,
			);
		} catch (OperatorTriggerException $exc) {
			$this->flashMessage("Could not start the migration-author agent — {$exc->getMessage()}", 'error');
			$this->redirect('Upgrades:service', ['service' => $service]);
		}

		$sessionUuid = (string) $res['session_uuid'];
		// Audit the OPERATOR's supervision action (operator identity, NOT the
		// agent's). Best-effort: an audit failure must not abort the spawn.
		$this->emitPromoteRequested($service, $recipe, $sessionUuid, $triggeredBy);

		$this->flashMessage(
			"Started migration-author for {$service}/{$recipe} — it writes a migration YAML + version bump, "
			. "then opens a review MR (GATE 2; nothing goes live). "
			. "Lineage: /agents/migration-author/sessions/{$sessionUuid}",
			'success',
		);
		$this->redirect('Upgrades:service', ['service' => $service]);
	}

	/**
	 * True when the named recipe exists for the service (a real migration
	 * candidate) — the guard that keeps actionPromoteToMigration from spawning an
	 * empty session for a typo'd or absent recipe id. Reads the offline matrix
	 * (same source the page renders), so it never depends on a live Bone call.
	 */
	private function migrationGap(string $service, string $recipe): bool
	{
		if ($service === '' || $recipe === '') {
			return false;
		}
		foreach ($this->upgrades->matrix() as $row) {
			if ((string) ($row['service'] ?? $row['id'] ?? '') !== $service) {
				continue;
			}
			foreach (($row['recipes'] ?? []) as $r) {
				if ((string) ($r['id'] ?? '') === $recipe) {
					return true;
				}
			}
		}
		return false;
	}

	/**
	 * Best-effort migration_promote_requested emit (A3.4) — the operator's
	 * button-press supervision event, distinct from the agent's own
	 * `agent_session_` / `agent_tool_` lineage. actor_id is the operator; result
	 * carries the spawned session_uuid so the supervision row deep-links the run.
	 * Never blocks the spawn: an audit failure must not surface as a UI error
	 * after the agent already started.
	 */
	private function emitPromoteRequested(string $service, string $recipe, string $sessionUuid, string $triggeredBy): void
	{
		try {
			$this->events->insert([
				'type'     => 'migration_promote_requested',
				'task'     => 'promote-to-migration: ' . $service . '/' . $recipe,
				'source'   => 'wing',
				'actor_id' => $triggeredBy,
				'result'   => [
					'service'      => $service,
					'recipe_id'    => $recipe,
					'session_uuid' => $sessionUuid,
					'agent'        => self::MIGRATION_AUTHOR_AGENT,
				],
			]);
		} catch (\Throwable) {
			// audit failure must not block the operator's action.
		}
	}

	/**
	 * Template vars:
	 *   service:  string
	 *   data:     array|null  — { service, docs_url, recipes: [...] } from BoxAPI
	 *   history:  list<array> — past applied upgrades for this service
	 *   drafts:   list<array> — agent-authored migration proposals (B4c): the
	 *                           Proposals strip above the recipe cards, each with
	 *                           a Review MR → (local forge) + Lineage deep-link.
	 *   notFound: bool
	 */
	public function renderService(string $service): void
	{
		$data = $this->upgrades->forService($service);
		$this->template->service = $service;
		$this->template->data = $data;
		$this->template->notFound = $data === null;
		$this->template->history = $this->upgrades->history($service);
		$this->template->drafts = $this->authored->forService($service);
	}
}
