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
	 * The judges already failing BEFORE this ceremony ran, or null when no
	 * baseline was established (an indeterminate/unreachable baseline leaves
	 * attribution OFF — conservative: never excuse a failure we could not
	 * measure a baseline against).
	 *
	 * @var array<int,string>|null
	 */
	private ?array $baselineFailingJudges = null;

	/**
	 * @param ?callable(array<int,string>): array{exit:int,stdout:string,stderr:string} $spawn
	 *        Replaces the PROCESS, never the verdict — the reader below still
	 *        computes satisfaction from what the process returned.
	 */
	/**
	 * @param ?callable(): bool $deliverableExists
	 *        Asked ONLY when the agent declared one. Returns whether the
	 *        artifact this ceremony owes is on record for THIS session. A
	 *        reader, never the thing that produced the work.
	 */
	public function __construct(
		private readonly string $repoRoot,
		private readonly mixed $spawn = null,
		private readonly mixed $deliverableExists = null,
	) {
	}

	/**
	 * Run the gate set ONCE before the ceremony's first iteration and record
	 * which judges were already failing. A failure the ceremony inherits is
	 * not a failure it caused (roadmap agentkit-baseline-gate-attribution,
	 * fee 59).
	 *
	 * MEASURED 2026-09-04: the proposer/librarian/surveyor all judge on `live`
	 * (nos-smoke + cortex-corpus-diff), and BOTH judges are ambient — nos-smoke
	 * probes the running estate, cortex-corpus-diff compares two live services;
	 * neither reads the tree, so no proposal or brief can move them. A single
	 * night of corpus-diff lag (transient embed lag, self-healed the next
	 * night) needs_revisioned every ceremony sharing the set — ~400k tokens for
	 * zero landed work, each spending a pointless revision iteration on a
	 * condition it could not touch.
	 *
	 * Cost: one extra gate run per session. Cheap for `live` (~6s); a `repo`
	 * baseline pays a full pytest. Accepted — it is what makes attribution
	 * honest, and it is zero model tokens.
	 *
	 * CEILING (ponytail): the comparison is over the SET of failing judges, so
	 * it excuses a judge that was already failing and is still failing. A
	 * ceremony whose very JOB is to fix that judge (a curator judged by
	 * cortex-corpus-diff) needs the judge's numeric DELTA, not the set — do not
	 * lean on this for a ceremony that owns its gate. The ceremonies that run
	 * today own neither `live` judge.
	 */
	public function baseline(string $gateset): void
	{
		$done = $this->run([
			(string) (getenv('NOS_LOOP_BIN') ?: 'nos-loop'),
			'judge', '--gate-set', $gateset, '--wait', '--json',
		]);
		$payload = json_decode(trim($done['stdout']), true);
		$verdict = is_array($payload) && is_array($payload['verdict'] ?? null)
			? $payload['verdict']
			: [];
		$result = is_string($verdict['result'] ?? null) ? $verdict['result'] : '';
		// Only a run that reached a real verdict establishes a baseline. `pass`
		// yields an empty failing set (so any later fail is a NEW one and stays
		// attributable); `fail` yields the inherited set. Indeterminate leaves
		// it null and attribution stays off.
		if ($result === 'pass' || $result === 'fail') {
			$this->baselineFailingJudges = $this->failingJudges($verdict);
		}
	}

	/**
	 * The set of judge names in a verdict whose result is not `pass`
	 * (fail OR indeterminate — a judge that could not run is not a judge that
	 * passed). Read from the verdict's per-judge `runs`, never parsed from the
	 * joined reason prose.
	 *
	 * @param array<string,mixed> $verdict
	 * @return array<int,string>
	 */
	private function failingJudges(array $verdict): array
	{
		$runs = is_array($verdict['runs'] ?? null) ? $verdict['runs'] : [];
		$fails = [];
		foreach ($runs as $run) {
			if (is_array($run) && ($run['result'] ?? null) !== 'pass'
				&& is_string($run['judge'] ?? null)) {
				$fails[$run['judge']] = true;
			}
		}
		return array_keys($fails);
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
		// BEFORE the deliverable, the attribution: a gate FAIL whose failing
		// judges were ALL already failing at baseline is inherited weather, not
		// this ceremony's regression. Only a real `fail` with a real identity
		// qualifies — an indeterminate is not a measured failure to inherit.
		// A NEW failing judge (one not in the baseline set) makes the whole
		// verdict attributable again, and the detail names it.
		$preExisting = false;
		if (!$satisfied && $result === 'fail' && $gateRunId !== null
			&& $this->baselineFailingJudges !== null) {
			$iterationFails = $this->failingJudges($verdict);
			$newFails = array_values(array_diff($iterationFails, $this->baselineFailingJudges));
			$preExisting = $iterationFails !== [] && $newFails === [];
		}
		// FOURTH THING, and it is about the AGENT rather than the tree.
		// Measured 2026-08-29 (session 53de6409): the surveyor passed both
		// judges and was satisfied having filed nothing. `nos-smoke` and
		// `cortex-corpus-diff` say the estate is healthy; neither has an
		// opinion about whether this ceremony did its own work. Where the
		// agent declared its deliverable, its ABSENCE unmakes satisfaction —
		// and the detail says so, so the revision has something to act on
		// instead of guessing which judge was unhappy.
		// The deliverable is the ceremony's OWN work and is required whether the
		// gate passed cleanly or only failed on inherited weather — a proposer
		// that filed nothing is unsatisfied even on a green estate.
		$missingDeliverable = false;
		if (($satisfied || $preExisting) && is_callable($this->deliverableExists)) {
			$missingDeliverable = ($this->deliverableExists)() === false;
		}
		// Satisfaction is a clean pass OR an inherited-only failure — never with
		// the deliverable missing (that IS the ceremony's failure).
		$satisfied = ($satisfied || $preExisting) && !$missingDeliverable;
		// Only a SATISFIED iteration may hold the pass rank. A `pass` that lost
		// one of the three — no uuid, or a client that exited non-zero after
		// printing it — used to score 2 here, which outranked a clean fail and
		// tripped the peak-stop on a verdict nobody can stand behind.
		$score = $satisfied ? self::RANK['pass'] : min(self::RANK[$result] ?? 0, self::RANK['fail']);
		if ($missingDeliverable) {
			$detail = 'the gate set passed, but this ceremony filed no deliverable — or filed '
			  . 'an empty one. The gates '
			  . 'judge the tree; the work you owe is an artifact keyed to this session. '
			  . 'File it, then the run can be satisfied.';
		} elseif ($preExisting && $satisfied) {
			$inherited = implode(', ', $this->failingJudges($verdict));
			$detail = "gate set `{$gateset}` failed on a condition that predates this run "
			  . "({$inherited}) — inherited, not introduced here, and no new judge failed. "
			  . 'This ceremony introduced no regression; the estate condition is someone '
			  . 'else\'s to fix.';
		} else {
			$detail = $this->detail($gateset, $done, $verdict, $satisfied);
		}

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
