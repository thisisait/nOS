<?php

declare(strict_types=1);

namespace App\AgentKit\Outcome;

/**
 * The outcome loop's oracle: a named gate set, run through the loop engine,
 * read by the runner. Satisfaction is the exit code — not a model's opinion of
 * its own work, and not a second model's opinion either.
 *
 * IT SHELLS OUT TO `nos-loop`, and that is not laziness. DECISION 6 of the
 * agentic-loop contract makes Bone's HTTP the only implementation of judgment
 * and every other harness a client; nothing outside Bone may import
 * `judges` (gate: test_loop_determinism_across_harnesses.py). A gate runner
 * living here would be a second oracle wearing the same name, drifting from
 * the one the ledger seals. The CLI already holds the address and the
 * evaluator token, exactly as tools/loop-pr.py does.
 *
 * It also holds the loop's bookkeeping, because "which iteration do we report"
 * is a question about the SCORES, and the scores are here:
 *
 *   * BEST, not last. A run that peaks at iteration 1 and does not beat it
 *     reports iteration 1. The last attempt is the one the model happened to
 *     stop on, which is only the best one by accident.
 *   * ONE iteration past an unbeaten peak, then stop (arXiv:2607.25886 —
 *     78.26% of self-continued searches end below their own peak).
 *
 * ponytail: the score is the verdict's own three-valued rank
 * (indeterminate 0 < fail 1 < pass 2). A finer one — how MANY judges passed —
 * would need the per-run rows behind the sealed verdict, which the client does
 * not expose; if the peak rule ever needs that resolution, add a reader for
 * loop_judge_runs rather than a second judge runner here.
 *
 * INDETERMINATE IS NOT A PASS anywhere in this file, and a verdict with no
 * uuid is not one either: a run that cannot be named cannot be replayed, and
 * agent_iterations refuses to record a satisfied row without one.
 */
final class GateOracle
{
	/** verdict result → score. Absence and refusal rank BELOW a clean fail. */
	private const RANK = ['indeterminate' => 0, 'fail' => 1, 'pass' => 2];

	/** @var array<int, array{score:int,satisfied:bool,gate_run_id:?string,detail:string,final_text:string}> */
	private array $history = [];

	private int $peak = -1;
	private int $peakScore = -1;
	private int $sincePeak = 0;

	/**
	 * @param ?callable(array<int,string>): array{exit:int,stdout:string,stderr:string} $spawn
	 *        Replaces the PROCESS, never the verdict — the reader below still
	 *        computes satisfaction from what the process returned.
	 */
	public function __construct(
		private readonly string $repoRoot,
		private readonly mixed $spawn = null,
	) {
	}

	/**
	 * Run the gate set for one iteration and record the score.
	 *
	 * @return array{satisfied:bool,gate_run_id:?string,score:int,detail:string}
	 */
	public function judge(int $iteration, string $gateset, string $finalText = ''): array
	{
		$done = $this->run([
			(string) (getenv('NOS_LOOP_BIN') ?: 'nos-loop'),
			'judge', '--gate-set', $gateset, '--wait', '--json',
		]);
		$payload = json_decode(trim($done['stdout']), true);
		$verdict = is_array($payload) && is_array($payload['verdict'] ?? null)
			? $payload['verdict']
			: [];

		$gateRunId = isset($verdict['uuid']) && is_string($verdict['uuid']) && trim($verdict['uuid']) !== ''
			? $verdict['uuid']
			: null;
		$result = is_string($verdict['result'] ?? null) ? $verdict['result'] : '';
		// Three independent things must agree before this is satisfaction: the
		// process exited 0, the sealed verdict says pass, and it has an
		// identity. Any one of them missing is a run nobody can stand behind.
		$satisfied = $done['exit'] === 0 && $result === 'pass' && $gateRunId !== null;
		// Only a SATISFIED iteration may hold the pass rank. A `pass` that lost
		// one of the three — no uuid, or a client that exited non-zero after
		// printing it — used to score 2 here, which outranked a clean fail and
		// tripped the peak-stop on a verdict nobody can stand behind.
		$score = $satisfied ? self::RANK['pass'] : min(self::RANK[$result] ?? 0, self::RANK['fail']);
		$detail = $this->detail($gateset, $done, $verdict, $satisfied);

		$this->history[$iteration] = [
			'score' => $score,
			'satisfied' => $satisfied,
			'gate_run_id' => $gateRunId,
			'detail' => $detail,
			'final_text' => $finalText,
		];
		if ($score > $this->peakScore) {
			$this->peakScore = $score;
			$this->peak = $iteration;
			$this->sincePeak = 0;
		} else {
			$this->sincePeak++;
		}

		return [
			'satisfied' => $satisfied,
			'gate_run_id' => $gateRunId,
			'score' => $score,
			'detail' => $detail,
		];
	}

	/** False once one iteration has been spent past the peak without beating it. */
	public function shouldContinue(): bool
	{
		return $this->sincePeak < 1;
	}

	/**
	 * The unsatisfied run's outcome word. A JUDGE THAT CANNOT RUN MUST NOT BE
	 * REPORTED AS WORK THAT FAILED: a peak score of 0 means no gate set ever
	 * reached a real verdict (requirements absent, sandbox failure, no uuid) —
	 * absence is UNKNOWN, never a verdict on the work. Only a peak that saw a
	 * genuine FAIL may say `needs_revision`/`max_iterations_reached`.
	 * Gate: test_an_unrunnable_judge_is_not_failed_work.py.
	 */
	public function outcome(bool $stoppedAtPeak): string
	{
		if ($this->peakScore <= 0) {
			return 'indeterminate';
		}
		return $stoppedAtPeak ? 'needs_revision' : 'max_iterations_reached';
	}

	/**
	 * The iteration to report: highest score, earliest on a tie.
	 *
	 * @return ?array{iteration:int,score:int,satisfied:bool,gate_run_id:?string,detail:string,final_text:string}
	 */
	public function best(): ?array
	{
		if ($this->peak < 0) {
			return null;
		}
		return ['iteration' => $this->peak] + $this->history[$this->peak];
	}

	/**
	 * @param array<int, string> $argv
	 * @return array{exit:int,stdout:string,stderr:string}
	 */
	private function run(array $argv): array
	{
		if ($this->spawn !== null) {
			return ($this->spawn)($argv);
		}
		// Array form: PHP execs the binary directly, no /bin/sh.
		$pipes = [];
		$proc = proc_open(
			$argv,
			[1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
			$pipes,
			is_dir($this->repoRoot) ? $this->repoRoot : null,
		);
		if (!is_resource($proc)) {
			return ['exit' => 4, 'stdout' => '', 'stderr' => 'nos-loop could not be spawned'];
		}
		$stdout = (string) stream_get_contents($pipes[1]);
		$stderr = (string) stream_get_contents($pipes[2]);
		fclose($pipes[1]);
		fclose($pipes[2]);
		return ['exit' => proc_close($proc), 'stdout' => $stdout, 'stderr' => $stderr];
	}

	/**
	 * @param array{exit:int,stdout:string,stderr:string} $done
	 * @param array<string, mixed> $verdict
	 */
	private function detail(string $gateset, array $done, array $verdict, bool $satisfied): string
	{
		$tree = is_string($verdict['tree_sha'] ?? null) ? substr($verdict['tree_sha'], 0, 12) : 'unknown';
		if ($satisfied) {
			return "gate set `{$gateset}` passed on tree {$tree}.";
		}
		$result = is_string($verdict['result'] ?? null) ? $verdict['result'] : 'no verdict';
		// The sealed verdict stores evidence as a canonical-JSON STRING
		// (ledger.seal_verdict `_canonical_json`), and this method used to
		// accept only an array — so every real feedback ended at the colon
		// and the agent revised blind (ceremony ea044f04, 2026-08-29).
		// Gate: test_gate_oracle_reads_sealed_evidence.py.
		$evidence = $verdict['evidence'] ?? null;
		if (is_string($evidence)) {
			$evidence = json_decode($evidence, true);
		}
		$evidence = is_array($evidence) ? $evidence : [];
		$reason = is_string($evidence['reason'] ?? null) && $evidence['reason'] !== ''
			? $evidence['reason']
			: trim($done['stderr']);
		// The oracle's raw output IS the revision feedback when no grader is
		// declared, so it must carry which judge said what, not just a word.
		return "gate set `{$gateset}` returned {$result} on tree {$tree} (exit {$done['exit']}): "
			. mb_strcut($reason, 0, 4000, 'UTF-8');
	}
}
