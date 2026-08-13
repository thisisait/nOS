<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Ansible callback events. Schema mirrors state/schema/event.schema.json.
 * All writes go through insert(); no PDO outside this class.
 */
final class EventRepository
{
	/** @var string[] Whitelisted event types (see event.schema.json). */
	public const VALID_TYPES = [
		'playbook_start', 'playbook_end',
		'play_start', 'play_end',
		'task_start', 'task_ok', 'task_changed', 'task_failed',
		'task_skipped', 'task_unreachable',
		'handler_start', 'handler_ok',
		'migration_start', 'migration_step_ok', 'migration_step_failed', 'migration_end',
		'upgrade_start', 'upgrade_step_ok', 'upgrade_end',
		'patch_start', 'patch_step_ok', 'patch_step_failed', 'patch_end',
		'coexistence_provision', 'coexistence_cutover', 'coexistence_cleanup',
		'agent_run_start', 'agent_run_end',
		// Conductor-emitted introspection events (A8 + Phase 5, 2026-05-07).
		// agent_run_start/end bookend the runner's subprocess lifecycle;
		// these are what the conductor itself writes between them as it walks
		// through a Pulse-fired task. Without this whitelist the conductor
		// falls back to `task_ok` and loses semantic clarity in the audit
		// trail (caught during the 2026-05-07 first ceremony).
		'conductor_self_test_step', 'conductor_report',
		// Agent approval workflow (A11 2026-05-07; A11's /approvals UI retired
		// 2026-08-08 — the event TYPES survive it).
		//   agent_approval_request   — AgentQuestionRepository::ask(kind='approval')
		//   agent_approval_decision  — emitted ONLY on the winning conditional
		//                              UPDATE in AgentQuestionRepository
		// Both share `actor_action_id` (the question uuid) so a request + its
		// decision pair via `WHERE actor_action_id=?`. Decision payload carries
		// `result_json: {verdict, operator_username, via, waited_seconds}`.
		'agent_approval_request', 'agent_approval_decision',
		// agents-inbox (2026-08-08): an agent asks, the run suspends, the answer
		// may arrive from any channel. An APPROVAL keeps the two types above —
		// same surface, different shape of answer — so every audit query keyed
		// on them keeps working across the A11 retirement.
		// These two carry the rest: free-text questions and choices.
		//   agent_question_asked     — AgentQuestionRepository::ask()
		//   agent_question_answered  — emitted ONLY on the winning conditional
		//     UPDATE in ::answer(), so the lineage carries exactly one decision
		//     per question. Twin rule: both names must also exist in Bone's
		//     VALID_TYPES or a Bone-proxied replay of these rows 400s.
		'agent_question_asked', 'agent_question_answered',
		// Big-red-button platform halt (A12 — /admin emergency control, 2026-05-07).
		//   admin_emergency_halt     — Tier-1 operator halts all Pulse cron firing
		//   admin_emergency_resume   — Tier-1 operator resumes after halt
		// Both share actor_action_id (one halt-resume cycle = one UUID); the halt
		// row's result_json records {jobs_affected, operator_username, note?}, the
		// resume row records {jobs_unhalted, operator_username, note?}.
		'admin_emergency_halt', 'admin_emergency_resume',
		// E2E journey telemetry (A13 — non-interactive end-to-end testing, 2026-05-07).
		//   e2e_journey_start  — fixture setup, one per journey run
		//   e2e_journey_step   — each named step within the journey (HTTP call,
		//                         DB query, etc.), result_json carries
		//                         {step, status, duration_ms, note?}
		//   e2e_journey_end    — fixture teardown, result_json carries
		//                         {steps, passed, failed, duration_ms_total}
		// All three share `actor_action_id` (one journey run = one UUID) so a
		// SELECT WHERE actor_action_id=? reconstructs the whole journey.
		// Aggregated by /api/v1/metrics into Prometheus counters/histograms
		// and surfaced in Grafana dashboard 40-e2e-journeys.
		'e2e_journey_start', 'e2e_journey_step', 'e2e_journey_end',
		// AgentKit lifecycle (A14 — AIT runtime, 2026-05-07). Every agent
		// session emits start + end; coordinator sessions also emit thread_*
		// events, outcome-driven sessions emit iteration events. Every event's
		// actor_action_id == agent_sessions.uuid so a SELECT joins the lineage.
		// Tools used by the agent emit agent_tool_use; LLM call counts surface
		// in agent_session_end.result_json.tokens.
		'agent_session_start', 'agent_session_end',
		'agent_thread_start', 'agent_thread_end',
		'agent_iteration_start', 'agent_iteration_end',
		'agent_tool_use', 'agent_tool_result',
		'agent_message',          // primary thread observation of LLM output
		'agent_grader_decision',  // satisfied | needs_revision | failed
		'agent_webhook_dispatch', // outbound webhook fired
		'agent_webhook_receipt',  // inbound webhook ack from subscriber
		'agent_vault_resolved',   // credential pulled at session start (no plaintext)
		// Backend attribution (2026-08-13). Both were emitted by Runner before
		// they were listed here, and the twin-parity gate did not object —
		// parity held because they were missing from BOTH lists. A check that
		// compares two artefacts to each other cannot see them being equally
		// wrong; `test_an_emitted_event_type_is_whitelisted.py` now derives the
		// question from the code that emits instead.
		//   agent_model_fallback   — a fallback served instead of the primary;
		//     carries the UNMATCHED error message, which is the only evidence
		//     a rule for a foreign backend's phrasing could be written from.
		//   agent_binding_disarmed — an agent.yml declares a backend that is
		//     not armed; the default served. Mirrors prepared-not-armed, so a
		//     committed binding cannot half-arm an estate.
		'agent_model_fallback', 'agent_binding_disarmed',
		// User invitations (A15 — operator-issued Authentik invites, 2026-05-17).
		//   user_invitation_issued   — operator mints an invitation from /users/invite
		//   user_invitation_revoked  — operator revokes an outstanding (unredeemed) invitation
		// Issue-row's result_json carries {invitation_uuid, invitation_pk, tenant,
		// target_groups, target_apps, expires_at}. Revoke-row carries
		// {invitation_pk, invitation_uuid}. Both rows source='wing'.
		'user_invitation_issued', 'user_invitation_revoked',
		// Right-to-erasure fan-out (C3 — tasks/gdpr-forget.yml, 2026-05-25).
		//   gdpr_forget_user — one row per Art. 17 erasure run; result_json carries
		//   {subject, dsar_id, services_planned, services_erased, dry_run}. Paired
		//   with a gdpr_dsar row (request_type=erase) which is the legal record.
		'gdpr_forget_user',
		// Right-of-access export (Art-15 — tasks/gdpr-export.yml). Forward-ready
		// (no task emits it yet; the paired gdpr_dsar row, request_type='access',
		// is the legal record). result_json would carry {subject, dsar_id,
		// request_type:'access', services_planned, services_captured,
		// manual_pending, portability_eligible, dry_run, bundle_dir}.
		'gdpr_export_user',
		// Consent registry (Art. 6(1)(a) + Art. 7). Permit-only / forward-ready
		// — NO live producer yet (record-consent.php writes gdpr_consent
		// directly, does not emit). Matches the user_invitation_* precedent.
		//   consent_granted   — result_json: {consent_id, subject, activity,
		//                        processing_id, tos_version_hash, source}.
		//   consent_withdrawn — result_json: {consent_id?, subject, activity, rows}.
		// MUST stay aligned with Bone's events.py VALID_TYPES (drift silently
		// 400s a future consent audit event) — pinned by test_consent_registry.py.
		'consent_granted', 'consent_withdrawn',
		// ── Devlog platform (docs/devlog/README.md, 2026-06-12) ──────────
		// WordPress devlog writes audited via Bone (actor_id=agent:devlog).
		// MUST stay aligned with Bone's events.py VALID_TYPES — pinned by
		// tests/anatomy/test_devlog_event_types.py.
		'devlog_entry_created', 'devlog_entry_updated', 'devlog_entry_deleted',
		'devlog_sync_run', 'devlog_published',
		// ── Agentic upgrade→migration→coexistence epic — 8 NEW types (B1) ─
		// Twin rule (NON-NEGOTIABLE, one commit): every type here MUST also be
		// in Bone's events.py VALID_TYPES or an agent's Bone-proxied POST 400s
		// (the 2026-05-17 remediator incident). Pinned by the extended
		// tests/anatomy/test_devlog_event_types.py twin-parity gate. Emitter /
		// FK-column / result_json contracts:
		//   plan_choice_recorded — UpgradesPresenter::actionPlanChoice; upgrade_id;
		//     {service, recipe_id, plan_mode, coexistence_planned_id?, data_copy, port_offset}.
		//   migration_authored    — migration-author agent; migration_id (holds uuid);
		//     {service, recipe_id, migration_uuid, artifact_kind, artifact_path,
		//     from_version, to_version}.
		//   migration_pr_opened   — migration-author via migration-pr.sh; migration_id;
		//     {migration_uuid, forge, mr_url, forge_branch}.
		//   migration_promoted    — operator forge-merge (webhook / --mark-merged);
		//     migration_id; {migration_uuid, committed_sha, applied_migration_id?}.
		//   migration_rejected    — operator reject; migration_id; {migration_uuid, rejected_reason}.
		//   coexistence_promote   — toggle-as-primary; coexist_svc;
		//     {coexistence_service, from_tag, to_tag, ttl_until}.
		//   coexistence_demote    — deactivate-secondary / implicit demote; coexist_svc;
		//     {coexistence_service, tag, from_role, to_role}.
		//   coexistence_cancel    — cancel queued; coexist_svc;
		//     {coexistence_service, tag, planned_id, reason}.
		'plan_choice_recorded',
		'migration_authored', 'migration_pr_opened',
		'migration_promoted', 'migration_rejected',
		'coexistence_promote', 'coexistence_demote', 'coexistence_cancel',
		// ── A4 (Q3/2026-06-16): manual re-runnable "Copy data" action ──────
		// The relocated B5 data move (explicit verb, not auto-at-cutover).
		// Emitted by Api\CoexistencePresenter::actionCopyData on a COMMITTED
		// copy only (dry_run=false AND Bone 2xx); coexist_svc; result_json
		// {coexistence_service, tag, source_migration_id, data_copied_at}. Twin
		// of Bone's events.py — pinned by test_devlog_event_types.py.
		'coexistence_copy_data',
		// ── A3 (Q5/2026-06-16): Wing "Promote to migration" Tier-1 button ──
		// The OPERATOR's supervision event for the button press — distinct from
		// the spawned agent's own agent_session_*/agent_tool_* lineage.
		//   migration_promote_requested — UpgradesPresenter::actionPromoteToMigration;
		//     actor_id=operator (X-Authentik-Username, NEVER the agent); source='wing';
		//     result_json {service, recipe_id, session_uuid, agent}. Twin of Bone's
		//     events.py — pinned by test_devlog_event_types.py.
		'migration_promote_requested',
		// ── F3 (2026-06-18): Unqueue / Cancel a planned upgrade (Tier-1) ───
		// The operator resets a planned upgrade from the /upgrades matrix (the
		// machinery path to re-run plan-choice for a re-test). Emitted by
		// UpgradesPresenter::emitUpgradeUnqueued, actor_id=operator
		// (X-Authentik-Username, NEVER the agent), source='wing'; reuses
		// UpgradeRepository::cancelPlanned (planned → cancelled); uses
		// upgrade_id; result_json {service, recipe_id, target_version,
		// planned_by}. Twin of Bone's events.py — pinned by
		// test_devlog_event_types.py.
		'upgrade_unqueued',
	];

	public function __construct(
		private Explorer $db,
	) {
	}

	/**
	 * Insert an event row. Returns the new event id.
	 * Caller must have validated payload shape already.
	 */
	public function insert(array $payload): int
	{
		$row = [
			'ts'           => (string) ($payload['ts'] ?? gmdate('c')),
			'run_id'       => (string) ($payload['run_id'] ?? ''),
			'type'         => (string) ($payload['type'] ?? ''),
			'playbook'     => $payload['playbook']     ?? null,
			'play'         => $payload['play']         ?? null,
			'task'         => $payload['task']         ?? null,
			'role'         => $payload['role']         ?? null,
			'host'         => $payload['host']         ?? null,
			'duration_ms'  => isset($payload['duration_ms']) ? (int) $payload['duration_ms'] : null,
			'changed'      => array_key_exists('changed', $payload)
				? ((bool) $payload['changed'] ? 1 : 0)
				: null,
			'result_json'  => isset($payload['result']) && is_array($payload['result'])
				? json_encode($payload['result'])
				: null,
			'migration_id' => $payload['migration_id'] ?? null,
			'upgrade_id'   => $payload['upgrade_id']   ?? null,
			'patch_id'     => $payload['patch_id']     ?? null,
			'coexist_svc'  => $payload['coexistence_service'] ?? null,
			// Anatomy P1 (2026-05-05). Closes CLAUDE.md "Wing /events
			// schema mismatch" tech debt — Bone POST handler accepted
			// `source` in JSON but the INSERT silently dropped it.
			// Free-text attribution hint ("callback" / "operator" /
			// "agent:<n>") complementing A10 actor_id below.
			'source'           => $payload['source']           ?? null,
			// A10 actor audit (2026-05-08). actor_id = Authentik client_id
			// of the writer (operator / agent / plugin). actor_action_id =
			// UUID grouping events that belong to one logical action
			// (e.g. agent_run_start + agent_run_end emitted by the same
			// conductor pulse run share an actor_action_id with the
			// pulse_runs row). acted_at = wall-clock time of the action;
			// usually = ts but kept separate so backfilled rows can record
			// the original action time vs row insert time.
			'actor_id'         => $payload['actor_id']         ?? null,
			'actor_action_id'  => $payload['actor_action_id']  ?? null,
			'acted_at'         => $payload['acted_at']         ?? null,
			// Tamper-evident hash-chain (gov P1). NULL on the default
			// chain-off path -> WORM triggers stay dormant. Set below when on.
			'prev_hash'        => null,
			'row_hash'         => null,
		];

		// Default-OFF: when WING_AUDIT_CHAIN_ENABLED!='1' or no secret, take the
		// byte-identical legacy insert (prev_hash/row_hash NULL). Chain ON:
		// serialize the tail read + sign inside one write txn so prev_hash can't
		// race. Algorithm is shared with bin/verify-audit-chain.php via
		// AuditChain; the Python writer (Bone) mirrors it in clients/wing.py.
		if (getenv('WING_AUDIT_CHAIN_ENABLED') === '1' && ($key = AuditChain::chainKey()) !== null) {
			$pdo = $this->db->getConnection()->getPdo();
			$ownTxn = !$pdo->inTransaction();
			if ($ownTxn) {
				$pdo->exec('BEGIN IMMEDIATE');
			}
			try {
				$prev = $this->db->getConnection()
					->query('SELECT row_hash FROM events WHERE row_hash IS NOT NULL ORDER BY id DESC LIMIT 1')
					->fetchField();
				$prev = ($prev === false || $prev === null) ? AuditChain::GENESIS : (string) $prev;
				$row['prev_hash'] = $prev;
				$row['row_hash'] = AuditChain::rowHash($prev, $row, $key);
				$this->db->table('events')->insert($row);
				$id = (int) $pdo->lastInsertId();
				if ($ownTxn) {
					$pdo->exec('COMMIT');
				}
				return $id;
			} catch (\Throwable $e) {
				if ($ownTxn && $pdo->inTransaction()) {
					$pdo->exec('ROLLBACK');
				}
				throw $e;
			}
		}

		$this->db->table('events')->insert($row);
		return (int) $this->db->getConnection()->getPdo()->lastInsertId();
	}

	/**
	 * Query events with filters. Supports run_id, type, since (ISO-8601),
	 * migration_id, upgrade_id, coexist_svc. `limit` caps at 500.
	 *
	 * @return array{items: array<int,array<string,mixed>>, total: int}
	 */
	public function query(array $filters = [], int $limit = 100): array
	{
		$limit = max(1, min(500, $limit));
		$query = $this->db->table('events')->order('id DESC');

		if (!empty($filters['run_id'])) {
			$query->where('run_id', $filters['run_id']);
		}
		if (!empty($filters['type'])) {
			$query->where('type', $filters['type']);
		}
		if (!empty($filters['since'])) {
			$query->where('ts >= ?', $filters['since']);
		}
		if (!empty($filters['migration_id'])) {
			$query->where('migration_id', $filters['migration_id']);
		}
		if (!empty($filters['upgrade_id'])) {
			$query->where('upgrade_id', $filters['upgrade_id']);
		}
		if (!empty($filters['patch_id'])) {
			$query->where('patch_id', $filters['patch_id']);
		}
		if (!empty($filters['coexist_svc'])) {
			$query->where('coexist_svc', $filters['coexist_svc']);
		}
		if (!empty($filters['source'])) {
			$query->where('source', $filters['source']);
		}
		if (!empty($filters['actor_id'])) {
			$query->where('actor_id', $filters['actor_id']);
		}
		if (!empty($filters['actor_action_id'])) {
			$query->where('actor_action_id', $filters['actor_action_id']);
		}

		$total = (clone $query)->count('*');
		$query->limit($limit);

		$items = [];
		foreach ($query->fetchAll() as $row) {
			$item = $row->toArray();
			if (!empty($item['result_json'])) {
				$item['result'] = json_decode($item['result_json'], true);
			}
			$items[] = $item;
		}

		return ['items' => $items, 'total' => $total];
	}

	// A11's three approval readers (listPendingApprovals /
	// countPendingApprovals / listRecentDecisions) were deleted with the
	// /approvals surface on 2026-08-08. "Pending" is a RESOLUTION question and
	// the event log structurally cannot answer it race-free — two operators
	// deciding in the same instant both append, and a reader that filters on
	// merely HAVING a decision calls approve+reject "decided". The open set
	// now comes from agent_questions (AgentQuestionRepository::listOpen /
	// countOpen); the lineage here remains the audit trail.

	/**
	 * All events tied to a migration_id (chronological).
	 */
	public function listForMigration(string $migrationId): array
	{
		$items = [];
		foreach ($this->db->table('events')
			->where('migration_id', $migrationId)
			->order('id ASC')
			->fetchAll() as $row) {
			$item = $row->toArray();
			if (!empty($item['result_json'])) {
				$item['result'] = json_decode($item['result_json'], true);
			}
			$items[] = $item;
		}
		return $items;
	}

	/**
	 * All events tied to an upgrade_id (chronological).
	 */
	public function listForUpgrade(string $upgradeId): array
	{
		$items = [];
		foreach ($this->db->table('events')
			->where('upgrade_id', $upgradeId)
			->order('id ASC')
			->fetchAll() as $row) {
			$item = $row->toArray();
			if (!empty($item['result_json'])) {
				$item['result'] = json_decode($item['result_json'], true);
			}
			$items[] = $item;
		}
		return $items;
	}

	/**
	 * All events tied to a patch_id (chronological). Mirrors listForUpgrade.
	 */
	public function listForPatch(string $patchId): array
	{
		$items = [];
		foreach ($this->db->table('events')
			->where('patch_id', $patchId)
			->order('id ASC')
			->fetchAll() as $row) {
			$item = $row->toArray();
			if (!empty($item['result_json'])) {
				$item['result'] = json_decode($item['result_json'], true);
			}
			$items[] = $item;
		}
		return $items;
	}

	/**
	 * Aggregated counts by type over the last N days. Used for timeline badges.
	 *
	 * @return array<string,int>
	 */
	public function countsByType(int $days = 30): array
	{
		$since = (new \DateTimeImmutable("-{$days} days"))->format('Y-m-d\TH:i:s\Z');
		$out = [];
		foreach ($this->db->query(
			'SELECT type, COUNT(*) AS n FROM events WHERE ts >= ? GROUP BY type',
			$since,
		)->fetchAll() as $row) {
			$out[$row['type']] = (int) $row['n'];
		}
		return $out;
	}
}
