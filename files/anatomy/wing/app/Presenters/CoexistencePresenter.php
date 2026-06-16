<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\CoexistenceRepository;

/**
 * /coexistence — per-service dual-version tracks with a reversible primary /
 * secondary toggle (B4c), the queued-provision dequeue, and the destructive
 * cleanup path.
 *
 * RBAC (B4c): every mutating verb here (toggle-as-primary, deactivate-secondary,
 * cancel-queued) flips live routing or the coexistence queue, so the whole
 * presenter is Tier-1 — the same boundary as UpgradesPresenter. Enforced by the
 * declarative `$minAccessTier = 1` (BasePresenter::startup() routes it through
 * requireTier) rather than an easy-to-forget startup() override. Was UNGATED
 * (the maps flagged it) — any forward-authed identity incl. tier-4 nos-guests
 * could read the page; with browser mutators added, the gate is load-bearing.
 */
final class CoexistencePresenter extends BasePresenter
{
	protected string $activeTab = 'coexistence';

	// RBAC: Tier-1 only (parity with /upgrades). Gated by default in
	// BasePresenter::startup() via this one property; pinned by
	// tests/anatomy/test_coexistence_presenter_tier1.py.
	protected ?int $minAccessTier = 1;

	public function __construct(
		private CoexistenceRepository $coexistence,
	) {
	}

	/**
	 * Reshape the flat per-service track list (Bone /api/coexistence → one row
	 * per tag, each carrying `active`/`role`/`tag`/`version`/…) into an explicit
	 * primary/secondary PAIR plus the queued-provision rows, so the template can
	 * render the reversible toggle without re-deriving roles.
	 *
	 * Template vars:
	 *   services:    array<string, array{
	 *       active_track:?string, primary:?array, secondaries:list<array>,
	 *       tracks:list<array>, queued:list<array>
	 *   }>
	 *   totalTracks: int
	 *   serviceCount:int
	 *   now:         string  — ISO-8601 for TTL countdown rendering
	 */
	public function renderDefault(): void
	{
		$raw = $this->coexistence->allTracks();

		// Queued (status='planned') provisions are NEVER read today (gap #4) —
		// surface them keyed by service so each gets a Cancel control.
		$queuedByService = [];
		foreach ($this->coexistence->listPlanned() as $p) {
			$queuedByService[(string) $p['service']][] = $p;
		}

		$services = [];
		$total = 0;
		// Union of services that have live tracks AND services with only queued rows.
		$serviceNames = array_unique(array_merge(array_keys($raw), array_keys($queuedByService)));
		sort($serviceNames);
		foreach ($serviceNames as $service) {
			$tracks = $raw[$service] ?? [];
			$total += count($tracks);

			// The active/primary track: prefer an explicit role='primary', else
			// the Bone-computed active flag (role='primary' ⟺ active=1 invariant).
			$primary = null;
			$secondaries = [];
			$activeTag = null;
			foreach ($tracks as $t) {
				$isPrimary = (($t['role'] ?? '') === 'primary') || !empty($t['active']);
				if ($isPrimary && $primary === null) {
					$primary = $t;
					$activeTag = $t['tag'] ?? null;
				} else {
					// A5 (§6.6): the just-demoted prior primary carries
					// demoted_from_primary_at (stamped by promote_track, round-trips
					// via Bone /api/coexistence). It is THE one-click-rollback target
					// — re-promote it to revert. At most one secondary is ever
					// stamped (only the previous-primary branch sets it), so the
					// template's "exactly one rollback target" assumption holds.
					$t['is_rollback_target'] = !empty($t['demoted_from_primary_at']);
					$secondaries[] = $t;
				}
			}

			$services[$service] = [
				'active_track' => $activeTag,
				'primary'      => $primary,
				'secondaries'  => $secondaries,
				'tracks'       => $tracks,
				'queued'       => $queuedByService[$service] ?? [],
			];
		}

		$this->template->services     = $services;
		$this->template->totalTracks  = $total;
		$this->template->serviceCount = count($services);
		$this->template->now          = gmdate('c');
	}

	/**
	 * POST /coexistence/<service>/toggle-primary — the reversible operator
	 * cutover (B4c). The browser CSRF form (typed-confirm "PRIMARY" in the
	 * widget) posts target_tag here; we proxy to CoexistenceRepository::promote
	 * (Bone promote_track) which flips active_track + role atomically (the prior
	 * primary is demoted in the same txn → the single-primary index never trips).
	 *
	 * dry_run=false: this is the committed toggle. Identity is the forward-auth
	 * operator (never body-supplied), matching UpgradesPresenter::actionQueueUpgrade.
	 */
	public function actionTogglePrimary(string $service): void
	{
		$this->requirePostMethod();
		$tag = (string) ($this->getHttpRequest()->getPost('target_tag') ?? '');
		if ($tag === '') {
			$this->flashMessage('Refused — target_tag is required to toggle the primary track.', 'error');
			$this->redirect('Coexistence:default');
		}
		$resp = $this->coexistence->promote($service, $tag, false);
		[$msg, $type] = $this->classify(
			$resp,
			"Toggled {$service} primary → {$tag}.",
			"Toggle to {$tag} failed",
		);
		$this->flashMessage($msg, $type);
		$this->redirect('Coexistence:default');
	}

	/**
	 * POST /coexistence/<service>/deactivate-secondary — stop a non-primary
	 * track (B4c). docker compose stop (data + override kept), so it's reversible
	 * by re-promoting within the TTL. Bone refuses the active primary unless force
	 * AND a failover target exists (G-DEACTIVATE-NOT-PRIMARY). Operator path =
	 * window.confirm (non-destructive), no typed phrase.
	 */
	public function actionDeactivateSecondary(string $service): void
	{
		$this->requirePostMethod();
		$tag = (string) ($this->getHttpRequest()->getPost('tag') ?? '');
		if ($tag === '') {
			$this->flashMessage('Refused — tag is required to deactivate a secondary track.', 'error');
			$this->redirect('Coexistence:default');
		}
		$force = (bool) $this->getHttpRequest()->getPost('force');
		$resp = $this->coexistence->deactivate($service, $tag, $force, false);
		[$msg, $type] = $this->classify(
			$resp,
			"Deactivated {$service}/{$tag} (data kept).",
			"Deactivate of {$tag} failed",
		);
		$this->flashMessage($msg, $type);
		$this->redirect('Coexistence:default');
	}

	/**
	 * POST /coexistence/<service>/copy-data — manual, re-runnable "Copy data"
	 * into a secondary track (A4 / Q3). The relocated B5 data move: runs the
	 * track's recorded migration data-transform into the SECONDARY's empty
	 * cluster, idempotently, then stamps data_copied_at. NO pointer flip — the
	 * operator re-runs it right before a promote for freshness. Non-destructive
	 * (writes only into the empty secondary) → window.confirm, no typed phrase.
	 * dry_run=false: this is the committed copy. Identity is the forward-auth
	 * operator (never body-supplied), matching actionDeactivateSecondary.
	 */
	public function actionCopyData(string $service): void
	{
		$this->requirePostMethod();
		$tag = (string) ($this->getHttpRequest()->getPost('tag') ?? '');
		if ($tag === '') {
			$this->flashMessage('Refused — tag is required to copy data into a track.', 'error');
			$this->redirect('Coexistence:default');
		}
		$resp = $this->coexistence->copyData($service, $tag, false);
		[$msg, $type] = $this->classify(
			$resp,
			"Copied data into {$service}/{$tag} (re-run before Promote for freshness).",
			"Copy data into {$tag} failed",
		);
		$this->flashMessage($msg, $type);
		$this->redirect('Coexistence:default');
	}

	/**
	 * POST /coexistence/<service>/cancel — the missing dequeue (B4c). Pure
	 * Wing-DB op: a queued (status='planned') provision was never provisioned, so
	 * there is no container/override/vhost to tear down. Refuses when there's no
	 * planned row. cancelled_by is the forward-auth operator identity.
	 */
	public function actionCancel(string $service): void
	{
		$this->requirePostMethod();
		$tag = (string) ($this->getHttpRequest()->getPost('tag') ?? '');
		if ($tag === '') {
			$this->flashMessage('Refused — tag is required to cancel a queued provision.', 'error');
			$this->redirect('Coexistence:default');
		}
		$cancelledBy = (string) ($this->getHttpRequest()->getHeader('X-Authentik-Username') ?? 'operator');
		$cancelledBy = $cancelledBy !== '' ? $cancelledBy : 'operator';
		$result = $this->coexistence->cancelPlanned($service, $tag, $cancelledBy);
		[$msg, $type] = $result['ok']
			? ["Cancelled queued provision {$service}/{$tag}.", 'success']
			: ["Refused — {$result['detail']}.", 'error'];
		$this->flashMessage($msg, $type);
		$this->redirect('Coexistence:default');
	}

	/**
	 * Map a BoxAPI passthrough response (status + body) to a flash (message,type).
	 * Bone's promote/deactivate return {status:int, body:{...}}; a 2xx is success,
	 * anything else surfaces the error detail (G-* guard refusal) to the operator.
	 *
	 * @param array<string,mixed> $resp
	 * @return array{0:string,1:string}
	 */
	private function classify(array $resp, string $okMsg, string $failPrefix): array
	{
		$status = (int) ($resp['status'] ?? 502);
		if ($status < 400) {
			return [$okMsg, 'success'];
		}
		$body = $resp['body'] ?? [];
		$detail = is_array($body)
			? (string) ($body['error'] ?? $body['detail'] ?? ('HTTP ' . $status))
			: ('HTTP ' . $status);
		return ["{$failPrefix} — {$detail}", 'error'];
	}
}
