<?php

declare(strict_types=1);

namespace App\Presenters;

use Nette\Database\Explorer;

/**
 * Wing /pulse — scheduled-job health.
 *
 * Wing has recorded every pulse run since 2026-05-04 and rendered none of them.
 * `keap:keap-features-sync` failed on every fire from 2026-07-14 (a script
 * committed 100644 that pulse could not exec), writing exit_code 255 into this
 * database each night, and nothing showed it. The job that never succeeds looks
 * exactly like the job that runs perfectly when neither is on a screen.
 *
 * So the view is ordered by what is WRONG, not alphabetically or by recency:
 * failing jobs first, then never-fired, then healthy. A screen sorted by name
 * makes the operator do the scan that the screen exists to do for them.
 */
final class PulsePresenter extends BasePresenter
{
	protected string $activeTab = 'pulse';

	/** Runs shown in the recent-activity list. */
	private const RUN_LIMIT = 40;

	public function __construct(
		private Explorer $db,
	) {
	}

	public function renderDefault(?string $job = null): void
	{
		$jobs = $this->db->query(
			"SELECT j.id, j.plugin_name, j.job_name, j.schedule, j.paused, j.paused_reason,
			        j.last_fired_at, j.next_fire_at, j.max_runtime_s, j.jitter_min,
			        (SELECT COUNT(*) FROM pulse_runs r WHERE r.job_id = j.id) AS runs,
			        (SELECT COUNT(*) FROM pulse_runs r WHERE r.job_id = j.id AND r.exit_code = 0) AS ok,
			        (SELECT COUNT(*) FROM pulse_runs r WHERE r.job_id = j.id AND r.exit_code <> 0) AS bad,
			        (SELECT COUNT(*) FROM pulse_runs r WHERE r.job_id = j.id AND r.exit_code IS NULL) AS unfinished,
			        (SELECT r.exit_code FROM pulse_runs r WHERE r.job_id = j.id
			           ORDER BY r.fired_at DESC LIMIT 1) AS last_exit,
			        (SELECT r.stderr_tail FROM pulse_runs r WHERE r.job_id = j.id AND r.exit_code <> 0
			           ORDER BY r.fired_at DESC LIMIT 1) AS last_error
			   FROM pulse_jobs j
			  WHERE j.removed_at IS NULL",
		)->fetchAll();

		// Health classification. `unfinished` is its own state and NOT folded into
		// failing: a run that started and never reported back means the daemon died
		//
		// `overdue` ADDED 2026-08-07, and its absence was the estate's largest
		// blind spot. This match had no staleness arm, so a job that ran cleanly
		// every night for a fortnight and then STOPPED FOREVER kept bad=0,
		// unfinished=0, last_exit=0, paused=0 and a non-null last_fired_at — and
		// fell through to `default => 'ok'`, sorted to the BOTTOM of the page, with
		// its last successful timestamp printed beside it. The one signal that
		// catches a dead daemon is that Wing advances next_fire_at only on FINISH,
		// so a Pulse that stopped leaves every scheduled time frozen in the past.
		//
		// Measured while this was still true: keap:keap-features-sync exited
		// 255 / 255 / 3 on three consecutive nights (2026-07-25..27) and nothing
		// in the estate reacted. A silent stop is quieter than that.
		//
		// The rule is NOT invented here — it is the face's, in
		// files/anatomy/face/src/lib/anatomy/pulse.ts, which has had it since
		// 2026-08-05 while its own backend disagreed. One law, one shape; the two
		// are compared by tests/anatomy/test_overdue_is_one_rule.py.
		// mid-job, which is a different fault from a command that exited non-zero.
		$rows = [];
		foreach ($jobs as $j) {
			$r = (array) $j;
			$r['overdue_by'] = self::overdueBySeconds($r);
			$r['health'] = match (true) {
				(int) $r['bad'] > 0 && (int) $r['ok'] === 0 => 'broken',
				(int) $r['unfinished'] > 0                  => 'stuck',
				(int) $r['last_exit'] !== 0 && $r['last_exit'] !== null => 'failing',
				$r['overdue_by'] !== null                   => 'overdue',
				(int) $r['paused'] === 1                    => 'paused',
				$r['last_fired_at'] === null                => 'never',
				default                                     => 'ok',
			};
			$rows[] = $r;
		}

		$rank = ['broken' => 0, 'stuck' => 1, 'failing' => 2, 'overdue' => 3, 'never' => 4, 'paused' => 5, 'ok' => 6];
		usort($rows, fn (array $a, array $b) => [$rank[$a['health']], $a['id']] <=> [$rank[$b['health']], $b['id']]);

		$counts = array_fill_keys(array_keys($rank), 0);
		foreach ($rows as $r) {
			$counts[$r['health']]++;
		}

		$runs = $this->db->query(
			'SELECT run_id, job_id, fired_at, finished_at, exit_code, duration_ms, stderr_tail
			   FROM pulse_runs'
			. ($job !== null ? ' WHERE job_id = ?' : '')
			. ' ORDER BY fired_at DESC LIMIT ?',
			...($job !== null ? [$job, self::RUN_LIMIT] : [self::RUN_LIMIT]),
		)->fetchAll();

		$this->template->jobs      = $rows;
		$this->template->counts    = $counts;
		$this->template->runs      = $runs;
		$this->template->jobFilter = $job;
		// An operator halt stops every job; without it on this screen, a wholly
		// idle pulse reads as "nothing scheduled" instead of "you halted it".
		$this->template->halted = (bool) $this->db
			->query("SELECT COUNT(*) FROM pulse_jobs WHERE paused = 1 AND paused_reason LIKE 'emergency%'")
			->fetchField();
	}

	/**
	 * Seconds a job is late past its own grace window, or null if it is not late.
	 *
	 * GRACE = max(15 min, jitter_min * 2). Jitter is added to next_fire_at
	 * upstream (PulseRepository::computeNextFireAt) and the daemon polls on an
	 * interval, so a job is LEGITIMATELY a few minutes late every night. Flagging
	 * that would train the operator to ignore the flag, which is the same defect
	 * as not flagging at all, arrived at from the other side.
	 *
	 * PAUSED IS NOT LATE. A paused job has nothing scheduling it, so "overdue"
	 * would be a statement about a clock nobody is running. Conflating them also
	 * lets a deliberate pause hide a job that has ALSO never run — pause is a
	 * flag that coexists with a state, not a state.
	 *
	 * A NULL next_fire_at is not late either: the job has never been scheduled,
	 * which `never` already says, and guessing here would double-report it.
	 *
	 * @param  array<string, mixed> $job
	 */
	private static function overdueBySeconds(array $job): ?int
	{
		if ((int) ($job['paused'] ?? 0) === 1) {
			return null;
		}
		$next = $job['next_fire_at'] ?? null;
		if ($next === null || $next === '') {
			return null;
		}
		$due = strtotime((string) $next);
		if ($due === false) {
			return null;
		}
		$grace = max(15 * 60, ((int) ($job['jitter_min'] ?? 0)) * 60 * 2);
		$late  = time() - $due;
		return $late > $grace ? $late : null;
	}
}
