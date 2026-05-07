<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use Nette\Database\Explorer;

/**
 * Wing /api/v1/metrics — Prometheus exposition (Anatomy A13.2, 2026-05-07).
 *
 * Aggregates wing.db events into the metrics surface scraped by Alloy
 * → Prometheus → Grafana dashboard 40-e2e-journeys.
 *
 * Why a presenter (not a sidecar exporter):
 *   wing.db is the single source of truth (anatomy doctrine). Every other
 *   read/write path goes through Wing's HTTP layer. A standalone Python
 *   exporter would either duplicate Wing's read logic or hold an exclusive
 *   sqlite handle competing with the daemon. PHP serves the same engine,
 *   reuses Bone client wiring for cross-call sanity, and is naturally
 *   tracked by every contracts-drift CI gate.
 *
 * Auth: anonymous READ. The endpoint is bound to 127.0.0.1:9000 only
 * (see Caddyfile); Alloy scrapes via loopback. If Wing is ever exposed
 * on a routable interface, the Traefik file-provider already gates
 * /api/v1/* behind authentik forward-auth for tier-1 surfaces.
 *
 * Output: standard Prometheus exposition format, text/plain;version=0.0.4
 *
 * Today this presenter only emits e2e-journey metrics (one shape).
 * Future expansion: pulse_jobs counts, conductor heartbeat, gitleaks
 * findings open count. Each new metric family is a private method
 * appended to render(); no schema migration required.
 */
final class MetricsPresenter extends BaseApiPresenter
{
	/**
	 * /metrics is intentionally public — no Bearer required. Listed in
	 * publicActions so BaseApiPresenter::startup() doesn't fail-shut.
	 */
	protected array $publicActions = ['default'];

	public function __construct(
		private Explorer $db,
	) {
	}

	public function actionDefault(): void
	{
		$lines = [];

		$lines[] = '# HELP nos_e2e_journey_runs_total Total e2e journey runs by name and final status.';
		$lines[] = '# TYPE nos_e2e_journey_runs_total counter';
		foreach ($this->journeyRunCounts() as $row) {
			$lines[] = sprintf(
				'nos_e2e_journey_runs_total{journey="%s",status="%s"} %d',
				$this->lblEscape($row['journey']),
				$this->lblEscape($row['status']),
				$row['count'],
			);
		}

		$lines[] = '';
		$lines[] = '# HELP nos_e2e_journey_step_duration_ms_sum Sum of step durations (ms) by journey + step.';
		$lines[] = '# HELP nos_e2e_journey_step_duration_ms_count Count of step samples by journey + step.';
		$lines[] = '# TYPE nos_e2e_journey_step_duration_ms_sum counter';
		$lines[] = '# TYPE nos_e2e_journey_step_duration_ms_count counter';
		foreach ($this->stepDurations() as $row) {
			$lbl = sprintf(
				'{journey="%s",step="%s",status="%s"}',
				$this->lblEscape($row['journey']),
				$this->lblEscape($row['step']),
				$this->lblEscape($row['status']),
			);
			$lines[] = "nos_e2e_journey_step_duration_ms_sum{$lbl} {$row['sum_ms']}";
			$lines[] = "nos_e2e_journey_step_duration_ms_count{$lbl} {$row['count']}";
		}

		$lines[] = '';
		$lines[] = '# HELP nos_e2e_journey_last_run_timestamp Unix timestamp of the most recent end event per journey.';
		$lines[] = '# TYPE nos_e2e_journey_last_run_timestamp gauge';
		foreach ($this->journeyLastRunTimestamps() as $row) {
			$lines[] = sprintf(
				'nos_e2e_journey_last_run_timestamp{journey="%s",status="%s"} %d',
				$this->lblEscape($row['journey']),
				$this->lblEscape($row['status']),
				$row['ts'],
			);
		}

		$lines[] = '';
		$lines[] = '# HELP nos_pulse_jobs Pulse job catalog state (1 = matches state, 0 otherwise).';
		$lines[] = '# TYPE nos_pulse_jobs gauge';
		foreach ($this->pulseJobStates() as $row) {
			$lines[] = sprintf(
				'nos_pulse_jobs{job_id="%s",state="%s"} 1',
				$this->lblEscape($row['id']),
				$this->lblEscape($row['state']),
			);
		}

		$payload = implode("\n", $lines) . "\n";

		$resp = $this->getHttpResponse();
		$resp->setHeader('Content-Type', 'text/plain; version=0.0.4; charset=utf-8');
		$resp->setHeader('Cache-Control', 'no-store');
		echo $payload;
		$this->terminate();
	}

	// ── Aggregations ───────────────────────────────────────────────────

	/**
	 * @return list<array{journey: string, status: string, count: int}>
	 */
	private function journeyRunCounts(): array
	{
		$rows = $this->db->query(
			"SELECT json_extract(result_json, '$.journey') AS journey,
			        json_extract(result_json, '$.status')  AS status,
			        COUNT(*) AS n
			 FROM events
			 WHERE type = 'e2e_journey_end'
			 GROUP BY journey, status"
		)->fetchAll();
		$out = [];
		foreach ($rows as $r) {
			$out[] = [
				'journey' => (string) ($r->journey ?? 'unknown'),
				'status'  => (string) ($r->status  ?? 'unknown'),
				'count'   => (int) $r->n,
			];
		}
		return $out;
	}

	/**
	 * @return list<array{journey: string, step: string, status: string, sum_ms: int, count: int}>
	 */
	private function stepDurations(): array
	{
		$rows = $this->db->query(
			"SELECT json_extract(result_json, '$.journey')     AS journey,
			        json_extract(result_json, '$.step')        AS step,
			        json_extract(result_json, '$.status')      AS status,
			        SUM(CAST(json_extract(result_json, '$.duration_ms') AS INTEGER)) AS sum_ms,
			        COUNT(*) AS n
			 FROM events
			 WHERE type = 'e2e_journey_step'
			 GROUP BY journey, step, status"
		)->fetchAll();
		$out = [];
		foreach ($rows as $r) {
			$out[] = [
				'journey' => (string) ($r->journey ?? 'unknown'),
				'step'    => (string) ($r->step    ?? 'unknown'),
				'status'  => (string) ($r->status  ?? 'unknown'),
				'sum_ms'  => (int) ($r->sum_ms ?? 0),
				'count'   => (int) $r->n,
			];
		}
		return $out;
	}

	/**
	 * @return list<array{journey: string, status: string, ts: int}>
	 */
	private function journeyLastRunTimestamps(): array
	{
		$rows = $this->db->query(
			"SELECT json_extract(result_json, '$.journey') AS journey,
			        json_extract(result_json, '$.status')  AS status,
			        MAX(strftime('%s', ts))                AS ts
			 FROM events
			 WHERE type = 'e2e_journey_end'
			 GROUP BY journey, status"
		)->fetchAll();
		$out = [];
		foreach ($rows as $r) {
			$out[] = [
				'journey' => (string) ($r->journey ?? 'unknown'),
				'status'  => (string) ($r->status  ?? 'unknown'),
				'ts'      => (int) ($r->ts ?? 0),
			];
		}
		return $out;
	}

	/**
	 * @return list<array{id: string, state: string}>
	 */
	private function pulseJobStates(): array
	{
		$rows = $this->db->query(
			"SELECT id,
			        CASE
			          WHEN paused = 1 AND paused_reason LIKE 'emergency-halt:%' THEN 'emergency_halted'
			          WHEN paused = 1 THEN 'manually_paused'
			          ELSE 'unpaused'
			        END AS state
			 FROM pulse_jobs
			 WHERE removed_at IS NULL"
		)->fetchAll();
		$out = [];
		foreach ($rows as $r) {
			$out[] = [
				'id'    => (string) $r->id,
				'state' => (string) $r->state,
			];
		}
		return $out;
	}

	private function lblEscape(string $value): string
	{
		// Prometheus label values: backslash, doublequote, newline are special.
		return str_replace(
			['\\', '"', "\n"],
			['\\\\', '\\"', '\\n'],
			$value,
		);
	}
}
