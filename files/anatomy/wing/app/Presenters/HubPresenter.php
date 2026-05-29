<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\HubCardRepository;
use App\Model\SystemRepository;

/**
 * Hub — central dashboard showing all self-hosted systems.
 * Reads from SQLite `systems` table (populated by registry ingest +
 * manual/scan entries). Replaces the old "Components" tab — all data
 * is unified here. P1a overlays the plugin-harvested hub_card icon (+ tier)
 * so the per-plugin icons render and the viewer's tier is available for
 * RBAC-aware presentation.
 */
final class HubPresenter extends BasePresenter
{
	protected string $activeTab = 'hub';

	public function __construct(
		private SystemRepository $systems,
		private HubCardRepository $cards,
	) {
	}

	public function renderDefault(): void
	{
		$stats = $this->systems->stats();
		$tree = $this->systems->tree();
		$byStack = $this->systems->byStack();

		// P1a — overlay the plugin hub_card icon (+ tier) onto each system by
		// normalised slug. Render-time only; no DB write. Systems without a
		// matching plugin card keep their existing fields.
		$cardsBySlug = $this->cards->bySlug();
		foreach ($byStack as $stack => $systems) {
			foreach ($systems as $i => $sys) {
				$slug = strtolower(str_replace('_', '-', (string) ($sys['id'] ?? '')));
				if (isset($cardsBySlug[$slug])) {
					$byStack[$stack][$i]['icon'] = $cardsBySlug[$slug]['icon'] ?? null;
					$byStack[$stack][$i]['card_tier'] = $cardsBySlug[$slug]['tier'] ?? null;
				}
			}
		}

		// Viewer's RBAC tier (1 = most privileged). Defaults to 1 (show all) when
		// no nos-group header is present, so /hub never blanks out for an
		// edge-token caller; the template can dim/badge by card_tier vs this.
		$this->template->viewerTier = $this->callerHasGroup('nos-providers') || $this->callerHasGroup('nos-admins') ? 1
			: ($this->callerHasGroup('nos-managers') ? 2
			: ($this->callerHasGroup('nos-users') ? 3
			: ($this->callerHasGroup('nos-guests') ? 4 : 1)));

		// Collect unique stacks and categories for filter buttons
		$stacks = [];
		$categories = [];
		foreach ($this->systems->list()['systems'] as $sys) {
			if ($sys['category'] !== 'stack') {
				$s = $sys['stack'] ?? 'other';
				$stacks[$s] = ($stacks[$s] ?? 0) + 1;
				$c = $sys['category'] ?? 'other';
				$categories[$c] = ($categories[$c] ?? 0) + 1;
			}
		}
		ksort($stacks);
		ksort($categories);

		$this->template->stats = $stats;
		$this->template->tree = $tree;
		$this->template->byStack = $byStack;
		$this->template->stacks = $stacks;
		$this->template->categories = $categories;
	}
}
