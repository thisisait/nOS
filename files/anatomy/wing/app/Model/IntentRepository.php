<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Intents: an operator's apply filed by Wing, executed by the medulla, recorded by Wing
 * (row wing-apply-through-medulla; rulings 2026-11-11, 11-13, 11-14).
 *
 * The shape is agent_questions': this table is the RESOLUTION (one row per intent, whether it
 * was picked and how it ended), events are the LINEAGE (intent_filed, intent_executed). Every
 * transition is one conditional UPDATE whose WHERE carries the precondition, and the affected-row
 * count is the verdict, so an intent executes once however many medulla ticks race for it.
 * The medulla never writes this table: it asks Wing to pick, and reports the outcome to Wing.
 */
final class IntentRepository
{
	/** The verbs an intent may name. Slice 1: an upgrade recipe, dry run only. */
	public const VERBS = ['upgrade.apply'];

	public function __construct(
		private Explorer $db,
		private EventRepository $events,
	) {
	}

	/**
	 * File one intent for the person Wing identified. Returns its uuid.
	 *
	 * @param array<string, string> $target
	 */
	public function file(string $verb, array $target, string $actorId, int $tier, bool $dryRun = true): string
	{
		if (!in_array($verb, self::VERBS, true)) {
			throw new \InvalidArgumentException("unknown intent verb {$verb}");
		}
		$uuid = self::uuid();
		$now = gmdate('Y-m-d\TH:i:s\Z');
		$this->db->table('intents')->insert([
			'uuid' => $uuid,
			'verb' => $verb,
			'target_json' => json_encode($target, JSON_THROW_ON_ERROR),
			'dry_run' => $dryRun ? 1 : 0,
			'actor_id' => $actorId,
			'tier' => $tier,
			'filed_at' => $now,
		]);
		$this->events->insert([
			'ts' => $now, 'type' => 'intent_filed', 'run_id' => 'intent-' . $uuid, 'source' => 'wing',
			'actor_id' => $actorId, 'actor_action_id' => $uuid,
			'result' => ['verb' => $verb, 'target' => $target, 'dry_run' => $dryRun],
		]);
		return $uuid;
	}

	/**
	 * Unpicked intents, oldest first: what the medulla may ask to pick.
	 *
	 * @return list<array<string, mixed>>
	 */
	public function due(int $limit = 10): array
	{
		$out = [];
		foreach ($this->db->table('intents')->where('picked_at', null)->order('id ASC')->limit($limit) as $r) {
			$out[] = [
				'uuid' => $r->uuid, 'verb' => $r->verb, 'target' => json_decode((string) $r->target_json, true),
				'dry_run' => (bool) $r->dry_run, 'filed_at' => $r->filed_at,
			];
		}
		return $out;
	}

	/** Stamp picked_at once. True for the one caller that won, false for every other. */
	public function pick(string $uuid, string $pickedBy): bool
	{
		return $this->db->table('intents')->where('uuid', $uuid)->where('picked_at', null)
			->update(['picked_at' => gmdate('Y-m-d\TH:i:s\Z'), 'picked_by' => $pickedBy]) === 1;
	}

	/**
	 * Record how a picked intent ended: once, and only by the token that picked it.
	 * Emits intent_executed (the lineage) on the winning UPDATE only.
	 */
	public function outcome(string $uuid, string $reportedBy, int $rc, string $summary): bool
	{
		$now = gmdate('Y-m-d\TH:i:s\Z');
		$won = $this->db->table('intents')->where('uuid', $uuid)->where('picked_by', $reportedBy)
			->where('outcome_at', null)->update(['outcome_rc' => $rc, 'outcome_at' => $now]) === 1;
		if ($won) {
			$this->events->insert([
				'ts' => $now, 'type' => 'intent_executed', 'run_id' => 'intent-' . $uuid, 'source' => 'medulla',
				'actor_id' => $reportedBy, 'actor_action_id' => $uuid,
				'result' => ['rc' => $rc, 'summary' => mb_substr($summary, 0, 500)],
			]);
		}
		return $won;
	}

	private static function uuid(): string
	{
		$b = random_bytes(16);
		$b[6] = chr((ord($b[6]) & 0x0f) | 0x40);
		$b[8] = chr((ord($b[8]) & 0x3f) | 0x80);
		return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($b), 4));
	}
}
