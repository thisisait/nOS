<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\BoneClient;
use App\Model\CoexistenceRepository;
use App\Model\MigrationRepository;
use App\Model\PatchRepository;

/**
 * Runtime state surface — BoxAPI proxy + local SQLite mirror sync.
 *
 * GET  /api/v1/state                  — proxy BoxAPI ~/.nos/state.yml verbatim
 * GET  /api/v1/state/services         — services subset of state.yml
 * GET  /api/v1/state/services/<id>    — single service entry
 * POST /api/v1/state/sync             — refresh SQLite mirrors from state.yml (idempotent)
 */
final class StatePresenter extends BaseApiPresenter
{
	public function __construct(
		private BoneClient $box,
		private MigrationRepository $migrations,
		private CoexistenceRepository $coexistence,
		private PatchRepository $patches,
	) {
	}

	public function actionDefault(): void
	{
		$this->requireMethod('GET');
		$this->proxy($this->box->get('/api/state'));
	}

	public function actionServices(?string $id = null): void
	{
		$this->requireMethod('GET');
		$path = '/api/state/services' . ($id !== null ? '/' . rawurlencode($id) : '');
		$this->proxy($this->box->get($path));
	}

	/**
	 * Pull the current state from BoxAPI, then upsert the mirror tables so
	 * read queries can answer even if BoxAPI later goes offline.
	 */
	public function actionSync(): void
	{
		$this->requireMethod('POST');
		$resp = $this->box->get('/api/state');
		if ($resp['status'] >= 400 || !is_array($resp['body'])) {
			$this->getHttpResponse()->setCode((int) ($resp['status'] ?? 502));
			$this->sendJson(['error' => 'unable to fetch state from BoxAPI', 'detail' => $resp['body']]);
		}

		$state = $resp['body'];
		$migrationsCount = 0;
		$tracksCount = 0;
		$patchesCount = 0;

		foreach (($state['migrations_applied'] ?? []) as $rec) {
			try {
				$this->migrations->upsertApplied($rec);
				$migrationsCount++;
			} catch (\Throwable) {
				// skip malformed records; keep syncing the rest
			}
		}

		foreach (($state['patches_applied'] ?? []) as $rec) {
			if (!is_array($rec)) {
				continue;
			}
			try {
				$this->patches->recordApplied($rec);
				$patchesCount++;
			} catch (\Throwable) {
				// skip malformed records; keep syncing the rest
			}
		}

		foreach (($state['coexistence'] ?? []) as $service => $svcBlock) {
			$activeTag = $svcBlock['active_track'] ?? null;
			foreach (($svcBlock['tracks'] ?? []) as $track) {
				if (!is_array($track)) {
					continue;
				}
				if ($activeTag !== null) {
					$track['active'] = ($track['tag'] ?? null) === $activeTag;
				}
				try {
					$this->coexistence->upsertTrack((string) $service, $track);
					$tracksCount++;
				} catch (\Throwable) {
					// ignore malformed
				}
			}
		}

		$this->sendSuccess([
			'synced'     => true,
			'migrations' => $migrationsCount,
			'patches'    => $patchesCount,
			'tracks'     => $tracksCount,
		]);
	}

	private function proxy(array $resp): never
	{
		$status = (int) ($resp['status'] ?? 502);
		$body = $resp['body'] ?? ['error' => 'empty response from BoxAPI'];
		$this->getHttpResponse()->setCode($status);
		$this->sendJson(is_array($body) ? $body : ['body' => $body]);
	}
}
